# Experiment 2 — Semantic Discovery (precision@1)

Measures how accurately the Gateway Agent finds the right resource for a
natural language query. Compares BM25 (lexical) against embedding-based
(semantic) retrieval across 25 queries and 11 registered resources.

---

## Overview

When the Principal Agent (PA) needs a capability it does not have locally,
its Resolver posts a query to the GA:

```
POST /ga/resources/search
{"query": "send an email to Francisco", "capabilities": ["email"], "max_results": 5}
```

This experiment sends 25 such queries **through that exact endpoint** — the
FastAPI app served via `TestClient`, with the same payload shape the PA's
`GAClient.search()` builds — and checks whether the top-ranked resource is
the correct one (precision@1).

> **Note:** Nothing in the experiment calls the retrieval functions directly.
> The server resolves its GA context through `axon.config.json` exactly as
> `axon ga serve` does, so the code path is identical to production:
> `POST /ga/resources/search` → `search_resources` → `retrieval.search` →
> `GAConfig.resolve()` → strategy from `ga.json`.

---

## Prerequisites

- Python 3.11+ and `uv` ([docs](https://docs.astral.sh/uv/))
- Dependencies installed (`uv sync` from the repository root)
- For the embedding strategy only: [Ollama](https://ollama.com) running with
  the `nomic-embed-text` model pulled (`ollama pull nomic-embed-text`)

No running GA process is needed — the experiment is fully self-contained.

---

## Resources registered (11)

```
A2A agents:    code-review-agent, incident-manager-agent, documentation-agent
MCP HTTP:      medical-mcp, resend, legal-compass, climate-intelligence,
               finance-oracle, hr-nexus
MCP stdio:     health-search, supply-chain-tracker
```

All are built from the fixtures in `experiments/shared/features/` and
registered into an isolated temporary registry.

---

## Query breakdown

| Category | Count | Capabilities sent | What it tests |
|----------|-------|-------------------|---------------|
| Direct | 10 | Yes — tag the PA decomposer would extract | Basic matching; both strategies should score well |
| Paraphrase | 10 | Empty — pure ranking, no tag filter | Semantic generalization; embeddings advantage expected |
| Out-of-scope | 5 | Empty | Threshold filtering; correct answer is *no result* |

Direct queries carry `capabilities` because that is how the PA posts when its
decomposer extracted a good tag — the GA filters by skill-tag intersection
*before* ranking. Paraphrase and out-of-scope queries send `capabilities: []`
so the ranking engine is tested on its own.

---

## How to run

From the repository root:

```bash
# BM25 only — no external dependencies
uv run experiments/ga/exp2_retrieval/run.py

# Embeddings only — requires Ollama with nomic-embed-text
uv run experiments/ga/exp2_retrieval/run.py --strategy embedding

# Both strategies, saving detailed per-query results
uv run experiments/ga/exp2_retrieval/run.py --strategy both --save
```

If Ollama is not reachable, the embedding strategy is skipped with a clear
message — BM25 still runs.

---

## How it works

1. Creates a `tempfile.TemporaryDirectory()` and writes an `axon.config.json`
   inside it with **two GA contexts sharing one registry**:
   `exp2-keyword` (BM25) and `exp2-embedding` (Ollama)
2. Registers the 11 fixture resources into the shared registry
3. `os.chdir(tmp)` so the server's `GAConfig.resolve()` finds the experiment
   config — the same resolution chain production uses
4. For each strategy, sets `AXON_GA_CONTEXT` (exactly how `axon ga serve`
   injects the context) and POSTs all 25 queries to `/ga/resources/search`
5. Compares the top-1 result against `expected` in `queries.json`
6. Restores cwd and env; the temp directory is deleted on exit

---

## Expected output

With Ollama running (`--strategy both`):

```
  Experiment 2 — Semantic Discovery
  ────────────────────────────────────────────────────────────────────
  Strategy     Correct  Total    P@1   Direct    Para    OOS
  ────────────────────────────────────────────────────────────────────
  BM25              14     20   0.70    10/10    4/10   5/5
  Embeddings        19     20   0.95    10/10    9/10   5/5
  ────────────────────────────────────────────────────────────────────
```

| Estratégia | Consultas diretas (10) | Paráfrases (10) | P@1 geral | OOS filtradas |
|------------|------------------------|-----------------|-----------|---------------|
| BM25 | 10/10 (1,00) | 4/10 (0,40) | 14/20 (0,70) | 5/5 |
| Embeddings (nomic-embed-text) | 10/10 (1,00) | 9/10 (0,90) | 19/20 (0,95) | 5/5 |

Out-of-scope queries are excluded from precision@1 since the correct answer
is "no result" — they are counted separately in the OOS column.

> **Note:** Exact embedding numbers depend on the Ollama model version
> (measured with `nomic-embed-text` v1.5). BM25 numbers are deterministic.

---

## Retrieval techniques

Three techniques in `ga/retrieval.py` produce these numbers:

### BM25 with stopword removal (keyword strategy)

Okapi BM25 (`k1=1.5`, `b=0.75`, Lucene-style non-negative IDF) over each
resource's name, description, skill descriptions and tags. Function words
are removed at tokenization — without this, an out-of-scope query like
*"what year did the Berlin Wall fall"* scores > 0 on every resource just
from "the", and OOS filtering never fires. Resources with score 0 are
always dropped, which is what makes BM25's OOS filtering perfect: zero
term overlap is an unambiguous "I don't know".

### Per-skill multi-vector index with max-pooling (embedding strategy)

Each resource is embedded as **one vector per skill** (plus one for
name + description), not as a single concatenated blob. A resource's score
is the *maximum* cosine over its vectors. Concatenation dilutes: a 4-skill
agent's vector is the average of unrelated capabilities, so no single query
sits close to it. Max-pooling lets a query match the one skill it is
actually about. This raised in-scope scores (+0.05–0.10) while leaving
out-of-scope scores flat — widening the separation the threshold needs.

### Task prefixes for the embedding model

`nomic-embed-text` is trained with task prefixes: queries must be embedded
as `search_query: ...` and documents as `search_document: ...`. The embedder
applies these automatically per model (mxbai-embed-large gets its own query
prompt). Asymmetric prefixes move queries and documents into the part of the
space the model was trained to align — without them, paraphrase accuracy
drops and the in-scope/out-of-scope distributions overlap.

### Calibrated threshold

With the three techniques above, the score distributions separate cleanly
on this corpus:

```
in-scope matches     : 0.52 – 0.85
out-of-scope queries : 0.44 – 0.49
```

`embedding_threshold: 0.5` (set in the experiment's GA context config)
filters all 5 out-of-scope queries while keeping every correct match.

> **Warning:** The threshold is corpus- and model-specific. The 0.5 value
> holds for `nomic-embed-text` with prefixes and max-pooling on this
> 11-resource registry; re-calibrate when changing model or registry scale.

---

## Findings

- **BM25 cannot bridge vocabulary gaps.** *"what has the doctor prescribed
  for Mr. Silva"* shares no token with `health-search`'s text ("physician",
  "prescriptions") — BM25 returns nothing. Six of its ten paraphrase misses
  fail this way, which is the honest baseline for lexical retrieval.
- **Embeddings' one miss is a semantic collision**: *"does storing our
  customers' CPF numbers violate privacy rules"* lands on `health-search`
  (patient records ≈ stored personal data) instead of `legal-compass`.
  Ironically BM25 gets this one right via the term "privacy" — evidence
  that BM25 ∪ embeddings > either alone, and rank-fusion is the natural
  next step.
- **OOS filtering needs both a model that separates and queries that are
  genuinely out of scope.** Early versions of this experiment used
  *"what's the weather forecast"* (≈ climate-intelligence) and *"translate
  this paragraph"* (≈ documentation-agent) as OOS — embedding space
  correctly saw them as adjacent. OOS queries must be distant from every
  registered capability, or they test query design, not retrieval.

---

## Isolation — no real state touched

All registry writes go to a `GAPaths` inside a temporary directory. The
`axon.config.json` the server reads lives in that same temp dir (the
experiment `chdir`s into it and restores your cwd afterwards). The
`AXON_GA_CONTEXT` env var is restored to its previous value on exit.

---

## Fixtures used

| File | Purpose |
|------|---------|
| `experiments/shared/features/agent_cards/*.json` | 3 A2A agent cards (skills + tags drive retrieval) |
| `experiments/shared/features/mcp_manifest/*.json` | 8 MCP manifests (tool descriptions + tags drive retrieval) |
| `experiments/ga/exp2_retrieval/queries.json` | The 25 queries with expected top-1 resource |

---

## Thesis reference

Section 4.3.3 — Camada de Recuperação Semântica
Section 3.4.1 — Experimento 2 (Descoberta Semântica)
Table 5.1    — precision@1 by strategy
