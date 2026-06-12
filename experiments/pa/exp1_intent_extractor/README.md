# Experiment 1 (PA) — IntentExtractor + Domain Skills

Validates Axon's skill architecture at its most sensitive point: the
**intent extraction** prompt can be specialized to a domain — a hospital, a
law firm — without breaking the extractor's contract.

---

## What this experiment proves

The IntentExtractor separates three concerns by design:

| Layer | File | Who owns it |
|-------|------|-------------|
| BEHAVIOR | `pa/skills/intent_extraction.md` (+ optional `domains/<name>.md`) | the operator — free to edit |
| OUTPUT_CONTRACT | hardcoded in `intent_extractor.py` | the framework |
| CONTEXT_TEMPLATE | `pa/context/assembler.py` | the framework |

Because the output contract is *not* in the editable skill, an operator can
append an entire domain context — entities, defaults, intent interpretations —
and the extractor still emits the same structured `Objective`. This experiment
proves that claim with 12 queries across three configurations: default prompt,
`hospital.md`, and `legal_firm.md`.

Three specific guarantees are tested:

1. **Non-ambiguous queries stay READY** with or without a skill — the domain
   extension does not break base behavior.
2. **Ambiguous queries CLARIFY by default but become READY with the skill** —
   the domain defaults (report format, recipient, active context) resolve the
   gap, and they are recorded honestly in `assumptions`, never fabricated.
3. **The skill does not cause hallucination** — a query with no discernible
   goal (`help with João`) still CLARIFIES even with the hospital skill loaded.

The contrast pairs are the heart of the experiment: `amb_02`/`amb_03` and
`amb_04`/`amb_05` run the *same query* with and without the skill and expect
*opposite outcomes*.

---

## Prerequisites

- Python 3.11+ and `uv` ([docs](https://docs.astral.sh/uv/))
- [Ollama](https://ollama.com) running locally with `deepseek-r1:14b`
  (the PA's default model), or pass `--model` to use another

---

## How it works

1. The runner **installs** `skills/hospital.md` and `skills/legal_firm.md`
   into `src/axon/pa/skills/domains/` — literally the operation an operator
   performs to add a domain. It refuses to overwrite an existing domain and
   removes the files afterwards (`try/finally`).
2. For each configuration it builds the extractor through the production
   path — no shortcuts:

   ```python
   config = PAConfig(intent_extractor=IntentExtractorConfig(domain="hospital"))
   extractor = IntentExtractor(config)   # loads base skill + domain extension
   ```

3. Each case calls `extractor.extract(query)` and classifies the result:
   `objective.clarification is None` → **READY**, otherwise **CLARIFY**.
4. For READY cases, every `expected_values` entry must appear somewhere in
   the serialized Objective (inputs, assumptions, goal or constraints).
   For CLARIFY cases, the result column shows how many questions were asked.

---

## How to run

From the repository root:

```bash
uv run experiments/pa/exp1_intent_extractor/run.py

# different model / save per-case details
uv run experiments/pa/exp1_intent_extractor/run.py --model llama3.1:8b --save

# run a single case file
uv run experiments/pa/exp1_intent_extractor/run.py --cases fun.json
```

> **Note:** Results depend on the LLM. The reference run below used
> `deepseek-r1:14b` at temperature 0 (~10 s per query on an M-series Mac).

---

## Expected output

```
  Experiment 1 — IntentExtractor + Domain Skills
  ──────────────────────────────────────────────────────────────────────────────
  ID        Query                              Skill          Expected  Result
  ──────────────────────────────────────────────────────────────────────────────
  amb_01    help with João                     hospital.md    CLARIFY   ✓  1
  amb_02    generate the report                hospital.md    READY     ✓  all
  amb_03    generate the report                —              CLARIFY   ✓  1
  amb_04    review the contract                legal_firm.md  READY     ✓  —
  amb_05    review the contract                —              CLARIFY   ✓  1
  amb_06    help me with my project            —              CLARIFY   ✓  1
  fun_01    presentation about ducks for kids  duck_studio.md READY     ✓  all
  fun_02    the usual                          duck_studio.md READY     ✓  all
  fun_03    the usual                          —              CLARIFY   ✓  1
  na_01     look up the medical record of pa…  hospital.md    READY     ✓  all
  na_02     check for drug interactions betw…  hospital.md    READY     ✓  all
  na_03     send the discharge summary of pa…  hospital.md    READY     ✓  all
  na_04     draft a legal opinion on service…  legal_firm.md  READY     ✓  all
  na_05     review contract 2026-047 for LGP…  legal_firm.md  READY     ✓  all
  na_06     create a 5-slide pitch deck abou…  —              READY     ✓  all
  ──────────────────────────────────────────────────────────────────────────────
  15/15 passed
```

Result column: for READY, `all` means every expected value was found in the
Objective (`—` = nothing specific to check); for CLARIFY, the number of
clarification questions asked.

---

## Reading the contrast pairs

What the extractor actually produced for `generate the report`
(reference run, deepseek-r1:14b):

**With `hospital.md` (amb_02 → READY):**

```
goal:        Generate a clinical report for the patient in context
assumptions: ["Report format: PDF"]
```

**Without a skill (amb_03 → CLARIFY):**

```
question: What type of report would you like me to generate?
          For example, financial analysis, market research, or project status.
```

Same query, same model, same output contract — the only variable is the
domain skill, and it cleanly flips the outcome. Note that the skill's
defaults surface as *assumptions* (which the user can correct), never as
fabricated facts: that is the base skill's "never fabricate factual data"
rule surviving the domain extension intact.

---

## The duck domain — domain-agnosticism, demonstrated

`skills/duck_studio.md` is deliberately silly: a kids' edutainment studio
whose defaults include *"at least one duck pun per slide (non-negotiable
studio policy)"* and a mascot named Captain Quackbeard. It exists to prove
the mechanism is domain-agnostic — the same machinery that resolves hospital
defaults resolves duck puns:

```
fun_01  "presentation about ducks for kids"  → READY
        assumptions: 5 slides, rubber-duck yellow theme, duck puns included
fun_02  "the usual"                          → READY
        goal: create a duck facts presentation for ducklings (ages 4–6)
fun_03  "the usual" (no skill)               → CLARIFY
```

> **Note:** The dumb example earned its keep. The first run of `fun_03`
> exposed a real gap in the base skill: "the usual" with no skill produced
> the hallucinated goal *"Proceed with the usual task as per standard
> procedures"*. The base `intent_extraction.md` now has explicit rules for
> unresolvable references — routines ("the usual") and definite references
> with no referent ("the contract", "the report") must trigger clarification
> instead of a generic invented goal. Both rules defer to domain context, so
> a skill that *defines* "the usual" (like Quack Studios does) still wins.

---

## Files

| File | Purpose |
|------|---------|
| `skills/hospital.md` | Clinical domain: entities, defaults (PDF, responsible physician), intent interpretations |
| `skills/legal_firm.md` | Legal domain: entities, defaults (DOCX, responsible partner, LGPD), intent interpretations |
| `skills/duck_studio.md` | Deliberately silly domain — proves the mechanism is domain-agnostic |
| `cases/non_ambiguous.json` | 6 fully-specified queries — must be READY in every configuration |
| `cases/ambiguous.json` | 6 underspecified queries — contrast pairs with/without skill |
| `cases/fun.json` | 3 duck cases, including the "the usual" contrast pair |
| `results/run_*.json` | Per-case details: full Objective, latency, missing values (with `--save`) |

---

## Thesis reference

Section 4.5.1 — Extração de Intenção e Skills de Domínio
Section 3.4.2 — Experimento 1 do PA (IntentExtractor)
