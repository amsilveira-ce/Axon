# Small demo — PA pipeline end to end (up to the Resolver)

A reproducible walkthrough: bring everything up, check it's healthy, then run a
query through the Principal Agent and watch the full roadmap —
**IntentExtraction → Decomposer (subtasks + Plan + DAG) → Resolver**.

The Executor does not exist yet, so the pipeline stops cleanly at the end of the
Resolver (resources assigned, ready to run).

---

## 0. Prerequisites (one-time)

- **Workspace initialized**: `axon.config.json` + `.axon/` exist. If not: `axon init`.
- **Ollama running** with the configured model (default `deepseek-r1:14b`):
  ```bash
  curl -s http://localhost:11434/api/tags   # should list your models
  ```
- **Secrets** in `.env` (auto-loaded — no manual export needed):
  ```dotenv
  TAVILY_API_KEY=tvly-...        # for the Tavily resource (api_key)
  ```
  The arXiv tool needs no token (`auth: none`).
- **Dependencies installed**: `uv sync` (the arXiv tool uses the `arxiv` lib,
  already declared in `pyproject.toml`).
- **The arXiv deep-research tool registered** in the `ga-corp` gateway (one-time):
  ```bash
  AXON_GA_CONTEXT=ga-corp axon add mcp arxiv \
    --stdio "python pocs/tools/mcp_server_arxiv.py" \
    --tag deep_research \
    --description "Deep research on arXiv: one call searches, fetches and synthesizes recent papers"
  ```
  Because it is `mcp_stdio`, the Resolver later marks it `callable_by=ga_proxy`
  (the PA asks the GA to run it). Remove with `axon add remove arxiv`.

---

## 1. Bring everything up

Start the Gateway Agent that holds the remote resources (`tavily`, `arxiv`).
The PA already lists it under `pa.gateways` (`http://0.0.0.0:4005`):

```bash
AXON_GA_CONTEXT=ga-corp python -m uvicorn axon.ga.server:app --host 0.0.0.0 --port 4005
```

Leave it running in its own terminal. (On macOS the client reaches `0.0.0.0`;
on Linux/containers use `127.0.0.1:4005` in the config instead.)

Local tools (`calculator`, `web_search`, `file_reader`, `datetime`) need **no
server** — the PA launches them on demand over stdio.

---

## 2. Check it's healthy

```bash
# GA is reachable and how many resources it has
curl -s http://127.0.0.1:4005/health

# the PA's view: which gateways are connected and online
axon pa gateway list

# resources across gateways + eligibility under the current policy
axon pa gateway resources
```

Expected (with `TAVILY_API_KEY` set):

```
ga-corp  http://0.0.0.0:4005
resource   pricing    auth        status
tavily     gratuito   api_key ✓   ✓ pronto
arxiv      gratuito   no-auth     ✓ pronto
2/2 prontos
```

Also worth a glance:

```bash
axon pa policy        # allow_paid / max_cost_per_call / match_threshold / fallback
```

---

## 3. Run it

### A. Full roadmap with a real DAG (resolves locally — always works)

```bash
axon pa intent test -q "Search the web for the GDP of the United States, China and Germany, then calculate their combined total"
```

What you see, stage by stage:

- **1. IntentExtraction** — the Objective (goal, success, hints).
- **2. Decomposer** — two subtasks with a dependency, the Plan, and the **DAG**:
  ```
  ◆ DAG
  │  edges    s1 → s2
  │  layers   L0: s1 │ L1: s2
  ```
- **3. Resolver** — both capabilities (`web_search`, `calculation`) are local, so
  `step1 ✓` for each (zero gateway calls), and the assignments table shows
  `source = local pool`.

Shorter alternative (datetime + date math):

```bash
axon pa intent test -q "What is today's date, and what date will it be 90 days from now?"
```

### B. Reaching the Gateway — the `ga_proxy` path (arXiv)

```bash
axon pa intent test -q "Do a deep research on arXiv about graph neural networks for recommendation systems"
```

If the Decomposer emits the capability `deep_research`, the Resolver does:

```
[Resolver] step2 ✓ subtask=s1 capability=deep_research → arxiv via http://0.0.0.0:4005
  callable_by = ga_proxy        # PA would ask the GA to execute it
  ga_url      = http://0.0.0.0:4005
  binding     = mcp_stdio
```

**Caveat:** the Decomposer currently only sees the *local* capabilities, so it
often maps research requests to `web_search` (local) instead of `deep_research`,
and the arXiv resource is not reached. The `ga_proxy` path is demonstrated
deterministically (no LLM) by:

```bash
python pocs/poc_resolver/run_huggingface.py   # GA discovery + policy/token steps
```

and was validated directly against the live GA (arxiv → `callable_by=ga_proxy`).
Once the Decomposer is fed the connected gateways' capabilities, query B resolves
to arXiv naturally.

---

## Notes / known limits

- **Executor runs the plan.** After the Resolver, the Executor calls each
  resource (`ga_proxy` → the GA's `/invoke`; `pa_direct` → A2A/MCP), records
  `Fact`/`Failure`, and persists the run to
  `{data_dir}/pa/traces/{session_id}/{request_id}.json`. Replay it with
  `axon pa inspect --session <id>`.
- **Tokens are never persisted.** The Resolver's Step 4 only *verifies* a token
  resolves; the secret stays in the environment and is re-resolved at call time.
- **arXiv rate limits.** The `deep_research_arxiv` tool uses the `arxiv` lib,
  which throttles to ~1 request / 3s and retries automatically; heavy back-to-back
  calls just wait their turn rather than erroring.

See [docs/resolver.md](docs/resolver.md) for the full Resolver explanation.
