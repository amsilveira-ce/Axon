# Experiment 2 (PA) — ResourceManifest as the execution contract

Integration test of the PA's three execution clients. Each client receives
a hand-built `ResourceManifest` — no Agent Card fetch, no GA discovery —
and must complete a real protocol round-trip against a live mock server:

```
Path 1 — A2A (pa_direct)
  PA → A2AClient → JSON-RPC message/send → mock A2A server (a2a SDK)

Path 2 — MCP HTTP (pa_direct)
  PA → MCPClient → MCP streamable HTTP → mock FastMCP server
       TokenResolver injects the Bearer header from the env var

Path 3 — ga_proxy (stdio)
  PA → GAClient → POST /ga/resources/{id}/invoke → real GA → subprocess
```

This is not a decoupling proof-of-concept — it validates that the three
clients *work*: that the manifest alone carries enough information for
each transport, auth scheme and delegation mode.

---

## What each path proves

| Path | Client | Proof |
|------|--------|-------|
| 1 | `A2AClient` | The manifest's `protocol_binding=JSONRPC` + `endpoint` are enough to build the SDK transport, send a task and extract the agent's text response |
| 2 | `MCPClient` | The manifest's `auth.env_var` is enough for the credential chain: TokenResolver reads the env var, the client injects `Authorization: Bearer …`, and the server — which **rejects unauthenticated handshakes with 401** — accepts the call |
| 3 | `GAClient` | `callable_by=ga_proxy` + `ga_url` are enough to delegate: the PA never spawns the stdio process; the GA does, and returns the tool result |

Every successful call produces a `Fact` with correct provenance
(`a2a` / `mcp`) — the same append-only record the Executor builds in a
real run.

> **Note:** Path 2 includes a negative sub-check: with the env var unset,
> `TokenResolver.resolve()` must return `None` and the MCP handshake must
> fail with 401. The `[TokenResolver] token not configured` warning and the
> `401 Unauthorized` error in the output are **expected** — they are the
> negative check executing, not a failure.

---

## The mock servers

All mocks speak the real protocols — no shortcut REST routes:

| Server | Built with | Why it's protocol-correct |
|--------|-----------|---------------------------|
| `servers/mock_a2a_server.py` | the same `a2a` SDK the client uses (`AgentExecutor` + `DefaultRequestHandler` + JSON-RPC routes) | wire format correct by construction |
| `servers/mock_mcp_http_server.py` | FastMCP streamable HTTP + an ASGI wrapper that 401s without the expected Bearer token | full MCP handshake (`initialize` → `tools/list` → `tools/call`) |
| `servers/mock_stdio_server.py` | FastMCP stdio — executed by the **GA** as a subprocess | the PA never touches this process |

The GA itself is real too: `run.py` boots `axon.ga.server.app` under
uvicorn against an isolated temp context (`axon.config.json` +
`AXON_GA_CONTEXT`, the same resolution chain as `axon ga serve`) with
`mock-health-search` registered in its registry.

---

## How to run

From the repository root — fully self-contained, no external services:

```bash
uv run experiments/pa/exp2_resource_manifest/run.py

# without path 3 (no GA boot, no stdio subprocess)
uv run experiments/pa/exp2_resource_manifest/run.py --skip-ga-proxy
```

---

## Expected output

```
  exp2 — ResourceManifest as the execution contract
  ────────────────────────────────────────────────────────────────────────────
  Path             Client      Result  Detail
  ────────────────────────────────────────────────────────────────────────────
  a2a_path         A2AClient   ✓       Fact(provenance=a2a, len=150)
  mcp_http_path    MCPClient   ✓       Fact(provenance=mcp, token_resolved=True, 401_without_token=True)
  ga_proxy_path    GAClient    ✓       Fact(provenance=mcp, via=ga_proxy, subprocess=GA-side)
  ────────────────────────────────────────────────────────────────────────────
  3/3 passed
```

After the table, `run.py` asserts the invariant that matters: every `Fact`
in the `AgentState` was produced from a manifest and carries `a2a` or
`mcp` provenance.

---

## Files

| File | Purpose |
|------|---------|
| `manifests.py` | The three hand-built ResourceManifests — the only input the clients see |
| `servers/mock_a2a_server.py` | A2A agent (JSON-RPC) answering with a canned review |
| `servers/mock_mcp_http_server.py` | Auth-gated MCP HTTP server with two drug tools |
| `servers/mock_stdio_server.py` | MCP stdio server spawned by the GA (patient lookup) |
| `run.py` | Orchestrates servers + GA, runs the three paths, prints the table |

---

## Thesis reference

Section 4.5.3 — O ResourceManifest como Contrato de Execução
Section 3.4.2 — Experimento 2 do PA (Clientes de Execução)
