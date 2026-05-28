# POC — A2A Client for the Planning Agent (PA)

This POC answers a single question:

> **Does the `ResourceManifest` carry everything the Planning Agent needs to call
> a remote A2A agent — with no further round-trip to the Gateway Agent (GA)?**

The answer is **yes**, and this POC proves it end to end: it hand-builds a
`ResourceManifest`, hands it to a PA-style executor, and uses that single object
to stand up a real [A2A](https://a2a-protocol.org) client and drive the
[`content_planner`](../agents/content_planner) agent across four runtime modes
(sync, streaming, auth, push).

---

## 1. Background — where the manifest comes from

In Axon the responsibilities are split:

- **GA (Gateway Agent)** — discovers resources, applies policy/auth filtering, and
  emits a `ResourceManifest` describing *one* resource the PA is allowed to call.
- **PA (Planning Agent)** — receives the manifest and **executes** the resource.
  It must do this from the manifest alone; it does not call back to the GA.

This POC isolates the **execution half**. There is no GA running here — instead
[`main.py`](main.py) builds the manifest by hand (see `make_manifest`),
simulating exactly what the GA would deliver after discovery + policy filtering.
Everything downstream of that manifest is the same code the PA would run in
production.

---

## 2. Architecture

Three moving parts:

| Component | Role | Where |
|-----------|------|-------|
| **Content Planner agent** | The remote A2A agent (server). Google ADK + LiteLLM/Ollama, exposed over JSON-RPC. Supports streaming **and** push notifications. | [`../agents/content_planner`](../agents/content_planner), `http://localhost:4115` |
| **PA executor** | Translates a `ResourceManifest` into a configured A2A client and drives the call. This is the heart of the POC. | [`pa_a2a_client_simulation/executor.py`](pa_a2a_client_simulation/executor.py) |
| **PA webhook server** | Receives push notifications from the remote agent when a task completes. Booted in-process, only for the push run. | [`pa_a2a_client_simulation/server.py`](pa_a2a_client_simulation/server.py), `http://localhost:8001/webhook/task-complete` |

```
                          make_manifest()               ┌───────────────────────────┐
   ┌──────────────┐   (simulates GA output)             │   Content Planner agent   │
   │   main.py    │ ─────────────────────────┐          │   (remote A2A server)     │
   │  4 scenarios │                           │          │   http://localhost:4115   │
   └──────────────┘                           ▼          │   JSONRPC · stream · push │
          │                       ┌───────────────────┐  └───────────────────────────┘
          │   ResourceManifest    │    PA executor    │            ▲   │
          └──────────────────────▶│   executor.py     │── send ────┘   │
                                  │                   │   message      │ result
                                  │ build_agent_card  │◀───────────────┘
                                  │ build_client_cfg  │
                                  │ build_a2a_client  │   push notification (run 4 only)
                                  │ build_request     │            │
                                  │ execute / _push   │◀───────────┐│
                                  └───────────────────┘            ││
                                            ▲                ┌──────┴┴───────────┐
                                            └────────────────│  PA webhook server │
                                              push_results   │  server.py :8001   │
                                                             └────────────────────┘
```

---

## 3. How the PA turns a `ResourceManifest` into a running A2A client

This is the core of the proof. The executor reads **only a handful of fields**
from the manifest — and every one of them is present in the object the GA emits.
Each field maps to exactly one client decision:

| `ResourceManifest` field | Read by | Drives |
|--------------------------|---------|--------|
| `endpoint` | `build_agent_card` | `AgentInterface.url` — *where* to connect |
| `protocol_binding` | `build_agent_card` | `AgentInterface.protocol_binding` — *which transport* (JSONRPC / GRPC / HTTP_JSON) |
| `a2a_capabilities.streaming` | `build_agent_card` + `build_client_config` | `send_message` (single response) vs `send_message_streaming` (SSE) |
| `a2a_capabilities.pushNotifications` | `build_client_config` | attaches a `TaskPushNotificationConfig` pointing at the PA webhook |
| `auth.scheme` | `build_agent_card` + `build_a2a_client` | declares the security scheme and installs the `AuthInterceptor` |
| `auth.env_var` | `ManifestCredentialService` | resolves the **actual token** at call time from the environment |
| `auth.header` | `AuthConfig` | the HTTP header name (`Authorization`, `X-Api-Key`, …) |

> Every other field on the manifest (`name`, `description`, `capability_tags`,
> `match_score`, `success_count`, …) exists for **discovery, ranking and policy** —
> the executor never touches it. The fact that the executor needs so little, and
> that all of it lives on the manifest, *is* the result this POC is demonstrating.

### The pipeline

```
ResourceManifest
  → build_agent_card()      minimal AgentCard the A2A ClientFactory needs:
                            where (endpoint), how (protocol_binding),
                            streaming capability, and the auth scheme
  → build_client_config()   client behaviour: streaming on/off, default push config
  → build_a2a_client()      create_client() + AuthInterceptor (only when auth != none)
  → build_request()         per-call SendMessageRequest: the prompt, optional
                            skill.outputModes, optional per-request push URL
  → execute() / execute_with_push()
                            drives send_message, collects the chunks, returns
                            the full result (or awaits the webhook for push)
```

### Auth flow — the token is never in the manifest

The manifest carries *how* to authenticate (`scheme`, `header`, `env_var`) but
**never the secret itself**. At call time `ManifestCredentialService` reads the
token from the environment variable named by `auth.env_var` and feeds it to the
SDK's `AuthInterceptor`, which builds the real header. This mirrors production:
the GA filters out any resource whose token is missing *before* emitting the
manifest, so a manifest that reaches the executor always has a resolvable token.

---

## 4. Project structure

```
poc_a2a_client/
├── main.py                          # Entry point — builds the manifest, runs 4 scenarios
├── pa_a2a_client_simulation/
│   ├── executor.py                  # ResourceManifest → A2AClient (the proof)
│   └── server.py                    # PA-side webhook server for push notifications
└── README.md
```

---

## 5. Prerequisites

1. **Ollama + the model** the content_planner uses (see its
   [README](../agents/content_planner/README.md)):
   ```bash
   ollama pull gemma3:12b
   ollama serve
   ```
2. **The content_planner agent running** on `http://localhost:4115`:
   ```bash
   cd ../agents/content_planner
   uv run python __main__.py
   ```
3. **An environment for this POC that has the `a2a-sdk` client.** The SDK is not a
   root dependency of Axon — the simplest path is to reuse the content_planner's
   `.venv` (it already ships `a2a-sdk[http-server]`, `starlette`, and `uvicorn`),
   or install `a2a-sdk[http-server]` into whichever env you run the POC with.
   `main.py` adds `../../src` to `sys.path`, so `axon.types` resolves regardless
   of the active environment.

---

## 6. Running the POC

With the content_planner already serving on `:4115`, in a second terminal:

```bash
cd pocs/poc_a2a_client
python main.py
```

`main.py` boots the PA webhook server itself when it reaches the push run — you
only need to start the content_planner manually.

---

## 7. The four runs — and what each one is expected to prove

`main.py` builds a *different manifest* for each run and drives the same executor.
Together they show that flipping a field on the `ResourceManifest` is enough to
change the PA's runtime behaviour. (The console labels them in Portuguese as
*Cenário 1, 2, 3, 5* — the numbering matches the source.)

### Run 1 · Synchronous HTTP  *(`a2a_capabilities.streaming = False`)*
The PA builds a JSON-RPC client and calls `send_message` once, receiving a single
response.
**Expected:** the full content outline produced by the content_planner is printed
in one block.

### Run 2 · SSE streaming  *(`a2a_capabilities.streaming = True`)*
Because both the manifest capability and the client config now request streaming,
the SDK switches to `send_message_streaming` and the result arrives as a sequence
of Server-Sent-Event chunks. The executor concatenates them.
**Expected:** the same outline as Run 1, but delivered incrementally over SSE and
reassembled before being returned to the PA.

### Run 3 · Invalid bearer token  *(`auth.scheme = bearer`, wrong token)*
The manifest declares bearer auth and points at an env var holding `"wrong-token"`.
The executor's `AuthInterceptor` builds a real `Authorization: Bearer wrong-token`
header and sends it.
**Expected (intent):** the remote agent rejects the call with **401**, and the POC
prints `✓ Falhou como esperado` — proving the manifest's `auth` block is turned
into an enforced credential, not just metadata.
**Caveat:** the bundled content_planner does **not** currently validate tokens, so
against *this* agent the call is accepted and the POC prints
`✗ Deveria ter falhado`. The run still demonstrates that the header is built and
sent from the manifest; seeing the 401 requires a remote agent that enforces
bearer auth.

### Run 4 · Push notification  *(`a2a_capabilities.pushNotifications = True`, printed as "Cenário 5")*
The PA starts its webhook server (`:8001/webhook/task-complete`) and sends a
request that returns immediately, with a `TaskPushNotificationConfig` pointing at
that webhook. The content_planner processes the task asynchronously and POSTs the
completed result back to the PA. `execute_with_push` captures the `task_id`, waits
up to 30 s for the webhook payload, and falls back to the directly-collected
response if none arrives.
**Expected:** the outline is printed, delivered via the webhook callback (or the
direct fallback if the push does not arrive within the timeout).

---

## 8. What this proves

Across all four runs the executor is fed nothing but a `ResourceManifest`. From
that one object it correctly chooses the transport, toggles streaming, builds and
sends auth headers, and wires up push callbacks — never consulting the GA again.

**The `ResourceManifest` is a complete, self-sufficient execution contract for an
A2A agent.**
