# Experiment 3 — Integrity Monitoring

Validates the Gateway Agent's health monitor: how it detects that a
registered resource stopped responding (**liveness**), how it detects that
a resource changed its contract while still alive (**drift**), and why MCP
resources are intentionally excluded (**credential boundary**).

---

## What this experiment proves

| # | Claim | Mechanism |
|---|-------|-----------|
| 1 | The GA detects when a resource stops responding | liveness probe (GET agent card) |
| 2 | The GA detects when a resource changed its contract | HMAC fingerprint comparison |
| 3 | These are two **distinct** states, not one | `online` / `offline` / `drift` |
| 4 | MCP resources are intentionally excluded | credential boundary, zero requests |

The third point is the architectural contribution: **drift is not offline**.
The agent is alive and responding, but what it offers no longer matches what
was registered. The distinction gives the operator actionable information:

- `offline` → *"fix the connection"*
- `drift` → *"re-validate the contract before trusting this resource again"*

That distinction is exactly what justifies the fingerprint mechanism — a
liveness probe alone cannot tell the two apart.

---

## How drift detection works

At registration, `validate_agent` computes a fingerprint of the agent card
**keyed by the admission token**:

```
fingerprint = HMAC-SHA256(key=token, message={url, name, version, skill_ids})[:16]
```

On every monitor cycle, `health.check_agent` re-fetches the live card,
recovers the same admission token from `tokens.json` (`used_by == resource.id`),
recomputes the HMAC and compares:

```
        GET /.well-known/agent-card.json
                      │
        ┌─────────────┴─────────────┐
   no response                 responds
        │                           │
     OFFLINE          HMAC(token, live card) == stored?
                            │               │
                          yes              no
                            │               │
                         ONLINE           DRIFT
```

> **Note:** Because the fingerprint is HMAC-keyed, drift detection is also
> tamper-evident: an attacker who substitutes the agent cannot forge a
> matching fingerprint without the admission token.

## Why MCP is not monitored

- **stdio** — there is no server to ping; the process only exists during a
  tool call.
- **HTTP** — a real probe would require presenting the operator's API key.
  The GA stores only the *name* of the env var, never the secret
  (credential boundary), so it cannot — and must not — authenticate.

The monitor logs `monitoring not applicable: mcp` and preserves the stored
status. Scenario 4 proves the implementation respects this: a request
counter sits on the registered MCP endpoint and must stay at **zero** across
every cycle of the experiment.

---

## Prerequisites

- Python 3.11+ and `uv` ([docs](https://docs.astral.sh/uv/))
- Dependencies installed (`uv sync` from the repository root)
- No Ollama, no running GA, no network beyond `127.0.0.1` mock servers

---

## How to run

From the repository root:

```bash
uv run experiments/ga/exp3_integrity/run.py
```

The runner:

1. Creates an isolated temporary GA directory (registry + tokens)
2. Registers `code-review-agent` through the **full production path**
   (token generation → card with embedded token → `validate_agent` →
   HMAC fingerprint → `mark_used`)
3. Registers `resend` (MCP HTTP, endpoint pointed at a local
   request-counting mock) and `health-search` (MCP stdio)
4. Executes the four scenario modules in `scenarios/` in order — each runs
   a real `health.run_cycle()` against the registry
5. Prints per-check results and exits non-zero if any scenario fails

---

## The four scenarios

Each scenario is a module in `scenarios/`, executed in order against the
same registry. The A2A scenarios form a state machine:

```
online ──(server killed)──► offline ──(same card returns)──► online ──(card modified)──► drift
```

### Scenario 1 — Liveness (`01_liveness.py`)

Kill the mock A2A server, run a cycle. The probe gets `connection refused`
→ status transitions `online → offline` and is persisted to the registry.
The MCP request counter must not move during the same cycle.

### Scenario 2 — Recovery (`02_recover.py`)

Restart the server with the **same** agent card, run a cycle. The probe
succeeds, the recomputed HMAC matches the stored fingerprint → status
transitions `offline → online`. Both directions of the liveness transition
work.

### Scenario 3 — Drift (`03_drift.py`)

Restart the server with a **modified** card (one extra skill appended).
The probe succeeds — liveness is fine — but the recomputed HMAC diverges
→ status becomes `drift`, NOT `offline`. The server is alive; the contract
changed. This is the scenario that justifies fingerprints existing at all.

### Scenario 4 — MCP boundary (`04_mcp_boundary.py`)

Run a full cycle with `health-search` (stdio) and `resend` (HTTP)
registered. Asserts: zero HTTP requests reached the MCP endpoint across
**all** cycles of the experiment, MCP statuses unchanged, and the log
contains `monitoring not applicable: mcp`.

---

## Expected output

```
  Experiment 3 — Integrity Monitoring
  ────────────────────────────────────────────────────
  Scenario 1 — liveness detection
    ✓ server stopped
    ✓ health check triggered
    ✓ status: online → offline
    ✓ no MCP request during cycle

  Scenario 2 — recovery
    ✓ server restarted (same card)
    ✓ status: offline → online
    ✓ fingerprint: match (no drift)

  Scenario 3 — drift detection
    ✓ server restarted (modified card)
    ✓ liveness: OK (server responded)
    ✓ fingerprint: diverged
    ✓ status: online → drift
    ✓ drift ≠ offline (server is alive)

  Scenario 4 — MCP boundary
    ✓ health-search: no ping attempted (stdio)
    ✓ resend: no ping attempted (http, no credentials)
    ✓ 0 requests made to MCP endpoints
    ✓ log: monitoring not applicable: mcp

  ────────────────────────────────────────────────────
  4/4 passed
```

---

## Isolation — no real state touched

All registry and token operations go through a `GAPaths` pointing at a
`tempfile.TemporaryDirectory()`. The A2A agent and the MCP endpoint are
`127.0.0.1` mock servers started and stopped by the runner. Nothing reads
or writes your real `.axon/` directory, and no external network call is made
(`resend`'s real endpoint is overridden with the local counting mock).

---

## Fixtures used

| File | Purpose |
|------|---------|
| `experiments/shared/features/agent_cards/code_review_agent.json` | The monitored A2A agent — token embedded at runtime |
| `experiments/shared/features/mcp_manifest/resend.json` | MCP HTTP resource (endpoint overridden to the counting mock) |
| `experiments/shared/features/mcp_manifest/health_search.json` | MCP stdio resource |
| `experiments/shared/mock_a2a_server.py` | Restartable mock serving the agent card |
| `experiments/shared/mock_mcp_server.py` | Counts every request — must stay at 0 |

---

## Writing the results in the thesis

The narrative arc of the three A2A scenarios is a state machine —
`online → offline → online → drift` — where each transition is triggered
by a different condition and produces a different observable state. The key
result is that `drift` and `offline` are distinct: the operator gets
actionable information instead of a binary up/down.

The MCP scenario closes the section by confirming that the *absence* of
monitoring is not a bug — no request was attempted because the design
explicitly excludes it (credential boundary, thesis §4.4.2). The experiment
confirms the implementation respects that boundary.

---

## Thesis reference

Section 4.4.2 — Monitoramento de Integridade e o Limite de Credenciais
Section 3.4.1 — Experimento 3 (Monitoramento de Integridade)
