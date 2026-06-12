# Experiment 3 (PA) — Resolver: known resources, local tools, and the discovery cycle

Seven cases drive the **real Resolver and Executor** (no LLM — hand-built
plans, same `AgentState` assembly as `agent.py`) against live servers. Each
case showcases one selection behaviour of the Resolver, and every resolved
resource is actually **called** through the corresponding client:

```
                ┌─ step 1 ── local pool ──────────► MCPClient (stdio)    01 03 07
subtask ──►     │           ResourceCache ────────► A2AClient            02 04
 capability ──► │                                 └► GAClient (ga_proxy) 06
                └─ step 2 ── GA /resources/search ► GAClient (ga_proxy)  05
```

A `CountingGAFactory` wraps the GAClient the Resolver uses, so every case
also **proves when the network was (not) touched**: cases 01–04, 06 and 07
complete with **zero** GA queries; only case 05 performs exactly one.

---

## The cases

| ID | Shows | Proof |
|----|-------|-------|
| `01_local_tool` | capability covered by a local tool → step 1 | assigned `local-calculator`, `provenance=local`, result 42, 0 GA queries |
| `02_cached_agent` | resource **known from a previous run** (ResourceCache) | assigned without any GA query; real A2A round-trip; `provenance=a2a` |
| `03_local_beats_cached` | local tool and cached remote share a capability | pool order picks `local-weather`; the cached `cloud-weather` (dead endpoint) is never dialed |
| `04_history_ranking` | two known candidates for one capability | `success_count desc, failure_count asc`: senior-reviewer (5/1) beats flaky-reviewer (0/4) despite pool order favouring the flaky one |
| `05_ga_discovery` | unknown capability → step 2 | 1 GA search (BM25 match 0.81) → `callable_by=ga_proxy` → GA spawns the stdio process → manifest **persisted to the cache** |
| `06_cache_reuse` | the discovery cycle closing | same capability, NEW run: resolved at step 1 from cache, **0 GA queries**, still executed through the GA |
| `07_tool_cache` | Executor dedup within a run | two subtasks, same tool + params → 2 Facts, `calls_used=1`, second answered from `tool_cache` |

Selection criterion under test (`_find_in_pool`): capability tag match,
then `success_count` desc / `failure_count` asc, then pool order — which
gives local tools implicit priority **at equal history** (case 03; case 04
shows history overriding pool order).

---

## Production bug found (and fixed)

`executor._provenance` derived the Fact's provenance from
`assignment.ga_url` — empty for every step-1 assignment. An A2A agent
resolved from the **cache** therefore produced `provenance=local`, while the
very same resource in the run it was **discovered** produced
`provenance=a2a`: provenance changed across runs for the same resource.

Fixed: provenance is now derived from the manifest that executed
(`type=agent → a2a`; local-pool tools → `local`; other MCP → `mcp`).
Cases 02 (cached A2A → `a2a`) and 05+06 (same resource, discovery run and
cache run both → `mcp`) assert the consistent behaviour.

---

## The fixtures

| Piece | What it is |
|-------|-----------|
| `servers/tool_calculator.py`, `servers/tool_weather.py` | local stdio tools, loaded through the real `LocalResourcePool` from a generated `local_tools.json` |
| `servers/mock_a2a_server.py` | real a2a-SDK agent (JSON-RPC) backing the three cached agent manifests |
| `servers/mock_patient_stdio.py` | single-tool stdio server registered **in the GA**; spawned GA-side on `ga_proxy` invoke |
| seeded `ResourceCache` | four manifests written as if discovered in a previous run (including the dead `cloud-weather` and the flaky/senior pair) |
| real GA | `axon.ga.server.app` under uvicorn, isolated temp context, BM25 retrieval |

---

## How to run

From the repository root — fully self-contained, no Ollama, no external
services:

```bash
uv run experiments/pa/exp3_discovery_cycle/run.py
```

## Expected output

```
  exp3 — Resolver: known resources, local tools, and the discovery cycle
  ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
  ID                     Capability        Resolved via           Client     R   Detail
  ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
  01_local_tool          calculation       step1 · local pool     MCPClient  ✓   local-calculator → 21*2 = 42 · 0 GA queries
  02_cached_agent        code_review       step1 · cache          A2AClient  ✓   mock-code-review (known from previous run) · provenance=a2a · 0 GA queries
  03_local_beats_cached  weather           step1 · local pool     MCPClient  ✓   local-weather beat cached cloud-weather (dead endpoint never dialed)
  04_history_ranking     doc_review        step1 · cache+history  A2AClient  ✓   senior-reviewer (5 ok/1 fail) beat flaky-reviewer (0 ok/4 fail)
  05_ga_discovery        patient_records   step2 · GA search      GAClient   ✓   patient-search (match=0.81) · 1 GA query · GA spawned stdio · cached
  06_cache_reuse         patient_records   step1 · cache          GAClient   ✓   re-run resolved from cache · 0 GA queries · still invoked via ga_proxy
  07_tool_cache          calculation ×2    step1 + tool_cache     MCPClient  ✓   2 facts, calls_used=1 — duplicate answered from tool_cache
  ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
  7/7 passed
```

---

## Thesis reference

Section 4.5.4 — O ciclo de descoberta do Resolver (pool local, cache e GA)
Section 3.4.3 — Experimento 3 do PA (Resolver e ciclo de descoberta)
