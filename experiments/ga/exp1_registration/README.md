# Experiment 1 — Registration & Admission

This experiment validates the **GA registration and admission system** end-to-end.
It covers the full lifecycle of a resource entering the Axon registry: token issuance,
agent card validation, manifest ingestion, fingerprinting, and every rejection path.

---

## Overview

The Gateway Agent (GA) acts as a trust boundary. Before any resource — an A2A agent
or an MCP tool — can serve requests through Axon, it must be admitted. Admission
requires a **single-use token** (`axon_tk_...`) that proves the operator authorized
this specific registration.

This experiment runs 12 scenarios that together prove the following guarantee:

> **Only resources holding a valid, unconsumed, non-revoked admission token
> can enter the registry.**

The scenarios are split into two groups:

- **Positive** — the happy paths: a registration that should succeed, does.
- **Negative** — the rejection paths: every invalid state is caught before any
  token is consumed or any resource is persisted.

---

## Prerequisites

- Python 3.11+
- `uv` installed ([docs](https://docs.astral.sh/uv/))
- Dependencies installed (`uv sync` from the repository root)
- No running GA process needed — the experiment is fully self-contained

---

## Concepts

### Admission tokens

Before registering a resource, an operator generates a token:

```bash
axon token generate --name my-agent
# → axon_tk_Xv2...  (stored in tokens.json as status=pending)
```

The token is **single-use**. Once a resource is successfully registered, the token
is marked `used` and can never be reused. If registration fails for any reason
(unreachable agent, invalid schema, duplicate name), the token stays `pending`
so the operator can retry.

### A2A vs MCP registration

There are two registration paths, each validated differently:

| Path | Source | Live call? | Token location |
|------|--------|-----------|----------------|
| A2A agent | Live `/.well-known/agent-card.json` | Yes | Embedded in the agent card |
| MCP tool | Manifest file (YAML or JSON) | No | Passed by the operator via `--token` |

A2A registration fetches the card from the running agent. The agent must embed
the admission token inside the card's `capabilities.extensions` block — this
proves the operator controls both the token and the agent.

MCP registration is offline: the operator presents the manifest and the token
together. No live server call is required.

### Fingerprinting

Every registered resource receives a **fingerprint** — a short HMAC-SHA256 digest
keyed by the admission token:

```
fingerprint = HMAC-SHA256(key=token, message=canonical_resource_payload)[:16]
```

Because the token is used as the HMAC key, the fingerprint cannot be reproduced
without the secret. It ties the registration cryptographically to the specific
token that admitted it, not just to the resource content. Later, when Axon checks
for drift (agent card changed, tools renamed), it recomputes and compares.

> **Note:** Auth env-var names are excluded from the fingerprint payload.
> Rotating a secret (e.g. `RESEND_API_KEY`) must not invalidate an otherwise
> unchanged registration.

---

## How to run

From the repository root:

```bash
uv run experiments/ga/exp1_registration/run.py
```

Or without `uv`:

```bash
python experiments/ga/exp1_registration/run.py
```

The experiment:
1. Creates an isolated temporary directory for all GA state (registry + tokens)
2. Starts a mock A2A HTTP server on port `18041` serving the test agent card
3. Runs all 12 scenarios in order against the temp directory
4. Prints the results and final registry state
5. Tears down the mock server and deletes the temp directory on exit

---

## Walkthrough

### Step 1 — Token is pending before use (`pos_04`)

The first check happens before any registration attempt. We inspect the token
that was just generated and assert it starts in the `pending` state.

This baseline matters: if the token were already `used` or `revoked` before
we even try to register, the whole experiment would be testing the wrong thing.

```python
tokens = list_tokens(paths)
t = next(t for t in tokens if t.token == a2a_token_value)
assert t.status.value == "pending"
```

---

### Step 2 — Register an A2A agent (`pos_01`)

We call `validate_agent(url, paths)`, which:

1. Fetches the agent card from `/.well-known/agent-card.json`
2. Validates the A2A schema (required fields, skills structure)
3. Finds the `axon` extension and extracts the token
4. Calls `verify_local(token, paths)` to check it exists and is `pending`
5. Computes the HMAC fingerprint keyed by the token

If all steps pass, we persist the resource and mark the token used:

```python
result = validate_agent(mock_url, paths)
assert result.ok

resource = Resource(
    id=f"res-{secrets.token_hex(3)}",
    type=ResourceType.agent,
    protocol_binding=ProtocolBinding.HTTP_JSON,
    name=result.agent_card.name,
    endpoint=mock_url,
    fingerprint=result.fingerprint,
    ...
)
add_resource(resource, paths)
mark_used(result.verified_token, resource.id, paths)
```

> **Note:** `validate_agent` returns `result.verified_token` — the raw
> `axon_tk_...` string extracted from the card. This is the value passed
> to `mark_used`, not a re-read from the token store.

---

### Step 3 — Token is consumed after registration (`pos_05`)

Immediately after `pos_01`, we re-read the token store and assert the status
changed to `used`. This confirms `mark_used` ran and persisted correctly.

```python
t = next(t for t in list_tokens(paths) if t.token == a2a_token_value)
assert t.status.value == "used"
```

---

### Step 4 — Register MCP tools from manifests (`pos_02`, `pos_03`)

MCP registration requires no live server. We load the manifest, generate a
dedicated admission token for it, build the `Resource`, and persist:

```python
# resend — MCP HTTP
manifest  = _load_manifest("resend")
mcp_token = generate("resend", paths)
resource  = _resource_from_manifest(manifest)
add_resource(resource, paths)
mark_used(mcp_token.token, resource.id, paths)
assert resource_exists("resend", paths)

# health-search — MCP stdio
manifest  = _load_manifest("health_search")
mcp_token = generate("health-search", paths)
resource  = _resource_from_manifest(manifest)
add_resource(resource, paths)
mark_used(mcp_token.token, resource.id, paths)
assert resource_exists("health-search", paths)
```

Each uses its own token. After both complete, three resources are registered
and three tokens are consumed.

---

### Step 5 — Revocation is permanent (`pos_06`)

We generate a new token, immediately revoke it, and assert that `verify_local`
raises `TokenVerificationError` with `"revoked"` in the message:

```python
tk = generate("revoke-test", paths)
revoke(tk.token, paths)

try:
    verify_local(tk.token, paths)
except TokenVerificationError as e:
    assert "revoked" in str(e).lower()
```

A revoked token cannot be reinstated. Any attempt to use it — whether by
the same operator or a replay attacker — will always fail.

---

### Step 6 — Rejection paths (`neg_01` – `neg_06`)

These scenarios test every way admission can fail. The key invariant in all
of them: **no token is consumed and no resource is persisted**.

| ID | What we do | What we expect |
|----|-----------|----------------|
| `neg_01` | `verify_local("not_a_valid_format", paths)` | `TokenVerificationError` — not found |
| `neg_02` | Mark a token used, then call `verify_local` again | `TokenVerificationError` — already used |
| `neg_03` | `verify_local` with a valid-format but unknown token | `TokenVerificationError` — not found |
| `neg_04` | `validate_agent("http://127.0.0.1:19999", paths)` (nothing listening) | `result.ok == False`; token stays `pending` |
| `neg_05` | Check `resource_exists("code-review-agent", paths)` (registered in `pos_01`) | Returns `True`; abort before `mark_used`; token stays `pending` |
| `neg_06` | `POST /ga/resources` without `X-Axon-PA-ID` header | HTTP `401` — header required |

#### Why `neg_04` matters

`validate_agent` catches the `httpx.ConnectError` at the card-fetch step and
returns `result.ok = False` without ever touching the token store. The operator
can fix the agent URL and retry using the same token.

#### Why `neg_05` matters

The duplicate check (`resource_exists`) fires **before** `mark_used` in the
registration flow. If we consumed the token first and then detected the duplicate,
the operator would lose a valid token for a registration that never happened.

#### Why `neg_06` is at the HTTP layer

The `X-Axon-PA-ID` check in `POST /ga/resources` runs before `GAConfig.resolve()`
is called. The server returns `401` without loading any GA context, reading any
config file, or touching the token store. This is tested via FastAPI's `TestClient`
so no actual server process is required.

---

## Expected output

When all 12 scenarios pass:

```
  Experiment 1 — Registration & Admission
  ────────────────────────────────────────────────────────────────────
  Positive scenarios
    ✓ pos_04  Token status is pending before use
    ✓ pos_01  A2A agent registered successfully
    ✓ pos_05  Token consumed after registration
    ✓ pos_02  MCP HTTP tool registered from manifest
    ✓ pos_03  MCP stdio tool registered from manifest
    ✓ pos_06  Token revocation prevents future use

  Negative scenarios
    ✓ neg_01  Invalid token format rejected
    ✓ neg_02  Consumed token rejected
    ✓ neg_03  Unknown token rejected
    ✓ neg_04  Unreachable agent rejected, token preserved
    ✓ neg_05  Duplicate resource rejected, token preserved
    ✓ neg_06  Request without X-Axon-PA-ID rejected
  ────────────────────────────────────────────────────────────────────
  12/12 passed

  Registry state
    resources : 4 (code-review-agent, resend, health-search, consumed-test-resource)
    tokens     : 4 used, 2 pending, 1 revoked
```

### Reading the registry state

The final counts reflect every token and resource created across all 12 scenarios:

| Count | Explanation |
|-------|------------|
| 4 resources | `code-review-agent` (pos_01) + `resend` (pos_02) + `health-search` (pos_03) + `consumed-test-resource` (neg_02) |
| 4 used | one per successful registration above |
| 2 pending | `unreachable-agent` (neg_04) + `code-review-agent-dup` (neg_05) — both aborted before `mark_used` |
| 1 revoked | `revoke-test` (pos_06) |

> **Note:** `neg_02` intentionally registers a dummy resource (`consumed-test-resource`)
> so we can produce a genuinely consumed token to test against. That is why the resource
> count is 4 rather than 3.

---

## Isolation — no real tokens or files touched

Every token operation (`generate`, `mark_used`, `revoke`, `verify_local`) receives
the `paths` argument pointing to a `tempfile.TemporaryDirectory()` created at the
start of `main()`. Nothing is read from or written to your real `.axon/` directory —
the GA state lives entirely inside the temp dir and is deleted when the experiment exits.

The one scenario that uses the live FastAPI app (`neg_06`, via `TestClient`) never
reaches `GAConfig.resolve()` because the `X-Axon-PA-ID` check fires first and returns
`401` before any real GA context is loaded.

---

## Fixtures used

| File | Purpose |
|------|---------|
| `experiments/shared/features/agent_cards/code_review_agent.json` | Base A2A agent card — the admission token is embedded at runtime before the mock server starts |
| `experiments/shared/features/mcp_manifest/resend.json` | MCP HTTP tool manifest (email sending) |
| `experiments/shared/features/mcp_manifest/health_search.json` | MCP stdio tool manifest (health data) |
| `experiments/shared/mock_a2a_server.py` | Lightweight `HTTPServer` that serves the agent card at `/.well-known/agent-card.json` |

---

## Key invariants verified

| Invariant | Scenarios |
|-----------|-----------|
| Single-use tokens are consumed exactly once | pos_04 → pos_01 → pos_05 |
| Validation failure does not consume the token | neg_04 |
| Duplicate check fires before `mark_used` | neg_05 |
| Revocation is permanent | pos_06 |
| `X-Axon-PA-ID` is enforced at the HTTP layer, before any GA context loads | neg_06 |
| MCP resources require no live server for registration | pos_02, pos_03 |

---

## Next steps

Once this experiment passes, the natural progression is:

- **Experiment 2 — Health & Drift Detection**: verify that registered agents are
  probed periodically and that fingerprint mismatches (card changed after registration)
  are surfaced correctly
- **Experiment 3 — MCP Client POC**: validate that the PA can invoke registered
  MCP tools through the GA proxy using the stored manifests
- **`axon ga resource list`** — inspect the real registry state in your active GA context

---

### Thesis reference

Section 4.4 — Registro de Recursos e o Token Axon

Section 3.4.1 — Validação do Gateway Agent (Experimento 1)
