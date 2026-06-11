# Third-Party MCP Resources

Axon can register and call **MCP servers it does not own** — Tavily, Notion, Resend, and any other server that speaks the Model Context Protocol. Unlike A2A agents (which self-attest via a token embedded in their card), third-party MCP servers require a different validation approach: a **live connection** that proves the server exists, is reachable, and exposes the tools it claims to offer.

This guide covers:

- Why MCP resources follow a different registration flow than A2A agents
- The core concepts: `ResourceManifest`, `TokenResolver`, and `MCPClient`
- Step-by-step tutorials for every supported transport and authentication scenario
- The internal registration pipeline and what gets persisted
- Known limitations and what is on the roadmap

> **Note:** If you are registering an **A2A agent** instead of an MCP server, see [Architecture → Protocol](architecture.md#protocol). The two flows diverge at the proof-of-validity step, which is explained in the next section.

---

## Overview: Why MCP resources differ from A2A agents

Every resource registration must answer one question: **is this resource real and authorized?**

For A2A agents, Axon answers it with self-attestation:

1. You run `axon token generate` and embed the token inside the agent's card (`capabilities.extensions[axon].params.token`).
2. At registration, the Gateway Agent (GA) fetches the card and verifies the token.
3. The resource itself carries the proof — it "opts in" by holding your token.

**Third-party MCP servers break this model.** You do not control Tavily's server, so there is nowhere to embed a token. The self-attestation mechanism has no place to live.

Axon solves this by shifting the proof to a **live connection**: it actually connects to the server, calls `list_tools()`, and fingerprints the result. That connection is the proof — it demonstrates the server exists, is reachable at the declared endpoint, and serves the tools it claims to offer.

The table below contrasts the two flows side by side:

| Property | A2A agent | Third-party MCP |
|---|---|---|
| Who presents the proof | The **resource** (in its card) | The **operator** (you, at `axon add mcp`) |
| What the proof establishes | "This resource opted into my registry" | "I, an authorized operator, sanctioned this resource" |
| Proof the resource is real | Fetch the agent card | **Live connection** + `list_tools()` |
| Fingerprint source | Hash of the agent card | Hash of `(binding + endpoint/command + tools)` |
| Token requirement | Required (in the card) | Optional admission token you supply |

> **Tip:** An `axon_token` can still be used with MCP resources — but it functions as an **admission token** that *you* present at registration, not something the resource carries. It authorizes you as the operator, not the server.

---

## Core concepts

Before running any commands, it helps to understand the three objects that make the system work. They are introduced here and revisited in the architecture section with more detail.

### `ResourceManifest` — the contract

A `ResourceManifest` is the single object that captures everything the Personal Agent (PA) needs to reach a resource and authenticate with it. It has two orthogonal axes:

- **Transport** (`protocol_binding`) — *how to reach the server*: `mcp_http`, `mcp_sse`, or `mcp_stdio`
- **Auth** (`AuthConfig`) — *how to authenticate*: a scheme (`none`, `bearer`, `api_key`, `oauth`) plus a location (`header`, `query`, `env`) for API keys

No per-resource code is needed. Every server is described by the same structure.

### `TokenResolver` — runtime secret injection

The `TokenResolver` (`axon.pa.token_resolver`) turns an `AuthConfig` into a concrete credential at call time. It auto-loads `.env` from the project root (without overriding real shell exports), reads the named env var, and produces a `ResolvedAuth` that knows where to place the credential:

- `header` → injects an HTTP header (`Authorization`, `X-Api-Key`, etc.)
- `query` → appends `?param=<token>` to the request URL
- `env` → injects the secret into the stdio child process environment

**Secrets are never stored in the registry.** Only the *name* of the env var is persisted. The value is resolved fresh at each call.

### `MCPClient` — the universal transport driver

`axon.pa.clients.mcp_client.MCPClient` consumes a `ResourceManifest`, obtains credentials from `TokenResolver`, and constructs the appropriate transport. The same client is used both at registration time (to validate the server) and at execution time (to call its tools).

---

## Supported scenarios

Every combination of transport and authentication scheme below is handled by the same `MCPClient`. Real-world examples:

| Server | Transport | Auth scheme | Auth location | Notes |
|--------|-----------|-------------|---------------|-------|
| Tavily | `mcp_http` | `api_key` | `query` | Key sent as `?tavilyApiKey=...` |
| Resend | `mcp_stdio` | `api_key` | `env` | Key injected into the child process env |
| Notion | `mcp_http` | `oauth` | — | Browser-based OAuth, delegated to fastmcp |
| Hugging Face | `mcp_http` | `bearer` | `header` | `Authorization: Bearer hf_...` |
| (generic) | any | `none` | — | No authentication |

**`AuthScheme` values:** `none`, `bearer`, `api_key`, `oauth`

**`AuthLocation` values** (applicable when scheme is `api_key`): `header`, `query`, `env`

---

## Tutorial: Registering an MCP resource

All MCP registrations go through `axon add mcp`, which writes the resource into the **active Gateway context**.

> **Note:** Check your active context with `axon ga list` and switch it with `axon ga use <name>` before registering.

### Command syntax

```
axon add mcp NAME  <transport flag>  [auth flags]  [--token ...]  [--tag ...]
```

#### Transport flags — choose exactly one

| Flag | Transport | Example value |
|------|-----------|---------------|
| `--http URL` | Streamable HTTP | `https://mcp.tavily.com/mcp/` |
| `--sse URL` | SSE (legacy) | `https://example.com/sse` |
| `--stdio "CMD"` | Local subprocess | `"npx -y resend-mcp"` |

#### Auth flags

| Flag | Meaning |
|------|---------|
| `--auth none\|bearer\|api_key\|oauth` | Credential type (default: `none`) |
| `--location header\|query\|env` | Where the `api_key` is placed (default: `header`) |
| `--header NAME` | Header name when `location=header` (e.g. `X-Api-Key`) |
| `--param NAME` | Query param name when `location=query` (e.g. `tavilyApiKey`) |
| `--env-var NAME` | Env var that holds the secret (e.g. `RESEND_API_KEY`) |
| `--scope SCOPE` | OAuth scope (repeatable) |

#### Other flags

| Flag | Meaning |
|------|---------|
| `--token axon_tk_...` | Optional admission token — verified and consumed at registration |
| `--tag TAG` | Capability tag for retrieval (repeatable) |
| `--description TEXT` | Human-readable description |

---

### Scenario 1: API key in the query string (Tavily)

Tavily's MCP server authenticates via an API key appended to the request URL as a query parameter.

**Step 1.** Export your Tavily key or add it to `.env`:

```dotenv
TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxx
```

**Step 2.** Register the resource:

```bash
axon add mcp tavily \
  --http https://mcp.tavily.com/mcp/ \
  --auth api_key --location query --param tavilyApiKey \
  --env-var TAVILY_API_KEY \
  --tag web_search
```

**Expected output:**

```
Connecting to https://mcp.tavily.com/mcp/ ...
Discovered 5 tools: tavily_search, tavily_extract, ...
Fingerprinting resource ...
Resource "tavily" registered in context "default".
```

> **Tip:** The `--tag` flag controls retrieval matching. Add tags that reflect what the server does (e.g. `web_search`, `research`) so the PA can route tasks to it correctly.

---

### Scenario 2: API key in the subprocess environment (Resend)

Resend's MCP server is a local stdio process. The API key is injected directly into the child process environment — it never appears on the network.

**Step 1.** Add your Resend key to `.env`:

```dotenv
RESEND_API_KEY=re_xxxxxxxxxxxxxxxx
```

**Step 2.** Register the resource:

```bash
axon add mcp resend \
  --stdio "npx -y resend-mcp" \
  --auth api_key --location env \
  --env-var RESEND_API_KEY \
  --tag email
```

> **Note:** For `location=env`, Axon reads the secret from `RESEND_API_KEY` at registration time and also injects it under the same name into the subprocess environment at call time. The source and target share the same env var name.

---

### Scenario 3: OAuth browser flow (Notion)

Notion uses OAuth. There is no static secret to configure — the browser flow runs during the live-connect validation step.

**Register the resource:**

```bash
axon add mcp notion \
  --http https://mcp.notion.com/mcp \
  --auth oauth \
  --tag docs
```

When the live connection runs, fastmcp will open your browser to complete authorization. The OAuth token is held in memory for the duration of the process.

> **Warning:** OAuth tokens are not persisted to disk. On every fresh process, an OAuth resource will re-authorize via the browser. Persistent token storage is planned for a future release.

---

### Scenario 4: Bearer token in an HTTP header (Hugging Face)

Hugging Face exposes a remote MCP server that accepts a bearer token in the `Authorization` header. This is the `bearer` / `header` scenario.

The Hugging Face settings page generates a config like this for other clients:

```json
{
  "mcpServers": {
    "hf-mcp-server": {
      "url": "https://huggingface.co/mcp",
      "headers": { "Authorization": "Bearer hf_***" }
    }
  }
}
```

In Axon terms: transport `mcp_http`, auth scheme `bearer` (always maps to `Authorization: Bearer <token>`), secret resolved from an env var.

**Step 1.** Create a Hugging Face access token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) (a read or fine-grained token). It looks like `hf_xxxxxxxx`.

**Step 2.** Add it to `.env`:

```dotenv
HF_TOKEN=hf_xxxxxxxx
```

The env var name is your choice — you point `--env-var` at it. If you omit `--env-var`, Axon infers `AXON_SECRET_HUGGINGFACE` from the resource name.

**Step 3.** Register the resource:

```bash
axon add mcp huggingface \
  --http https://huggingface.co/mcp \
  --auth bearer --env-var HF_TOKEN \
  --tag models --tag datasets --tag papers --tag search
```

**Step 4.** Confirm registration:

```bash
axon ga resource list
```

```
NAME           TYPE   STATUS   SKILLS
huggingface    mcp    online   model_search, dataset_search, papers_semantic_search, ...
```

> **Note:** The Hugging Face settings page can also generate an OAuth-based config. If you prefer that flow, register with `--auth oauth` instead of `--auth bearer --env-var HF_TOKEN`. The browser authorization runs during the live-connect step, the same as Notion above.

---

### Scenario 5: Using an admission token

If your Gateway requires operator authorization before accepting a new resource, attach an `axon_token` at registration time. The token is verified (`verify_local`) and consumed (`mark_used`) during registration, and the resource record keeps a reference to it (`token_ref`).

**Step 1.** Generate an admission token:

```bash
TOKEN=$(axon token generate --name tavily | grep -o 'axon_tk_[A-Za-z0-9_-]*')
```

**Step 2.** Pass it to `add mcp`:

```bash
axon add mcp tavily \
  --http https://mcp.tavily.com/mcp/ \
  --auth api_key --location query --param tavilyApiKey \
  --env-var TAVILY_API_KEY \
  --token "$TOKEN"
```

After registration, the token moves to the `used` state and is bound to the resource ID. Verify with:

```bash
axon token list --all
```

---

## How it works: the registration pipeline

When you run `axon add mcp`, the following steps execute in sequence:

```
axon add mcp ...
    │
    ▼
Build ResourceManifest          transport + auth assembled from CLI flags
    │
    ▼
validate_mcp()                  live connect via MCPClient → list_tools()
    │                           ← this is the proof of validity
    ▼
Compute fingerprint             sha256(binding + endpoint/command + tools)
    │
    ▼
Verify admission token          only if --token was given
    │
    ▼
Persist Resource                .axon/ga/{context}/registry.json
    │
    ▼
Mark token used                 only if --token was given
```

> **Warning:** If the live connection fails at the `validate_mcp()` step, registration aborts immediately and nothing is written to the registry. Check that the server is reachable and that credentials are correct before retrying.

---

## What gets stored

Each registered resource lives in `.axon/ga/{context}/registry.json` as a `Resource` object. The following fields are written:

| Field | Content |
|-------|---------|
| `type` | Always `mcp` |
| `protocol_binding` | Transport type (`mcp_http`, `mcp_sse`, `mcp_stdio`) |
| `endpoint` / `command` | The HTTP URL or stdio command string |
| `auth` | Full `AuthConfig`: scheme, location, header/param name, env var name, scopes |
| `skills` | One entry per discovered tool, with the tool's real name and description fetched live from the server |
| `description` | Synthesized summary (name + tool names + tags) unless `--description` was given |
| `fingerprint` | `sha256` covering tool names and descriptions — detects server drift |
| `token_ref` | The admission token ID, if one was used |

The `skills` field is what powers retrieval: `skill.description` and `skill.tags` are matched against task descriptions when the PA selects which resource to call.

> **Note:** **Secrets are never stored.** The registry holds only the *name* of the env var (e.g. `RESEND_API_KEY`), never its value. The `TokenResolver` reads the actual secret from the environment at call time.

---

## Architecture

### `ResourceManifest` — structure

```
ResourceManifest
├── protocol_binding   how to reach it   (mcp_http | mcp_sse | mcp_stdio | a2a)
└── auth: AuthConfig   how to authenticate
        ├── scheme     none | bearer | api_key | oauth
        ├── location   header | query | env          (for api_key)
        ├── header / param / env_var                 (the credential name/source)
        └── scopes / client_id_env / client_secret_env   (for oauth)
```

### `TokenResolver` — credential routing

The resolver maps each `AuthConfig` to a transport-ready credential:

| Auth location | `ResolvedAuth` method | Effect |
|--------------|----------------------|--------|
| `header` | `as_headers()` | Adds the credential as an HTTP header |
| `query` | `apply_to_url()` | Appends `?param=<token>` to the request URL |
| `env` | `as_env()` | Injects the secret into the stdio child process environment |
| `oauth` | *(none)* | No static secret; browser flow delegated to fastmcp |

### `MCPClient` — transport matrix

The client pairs each `protocol_binding` with the correct transport and applies credentials from `ResolvedAuth`:

```
manifest.protocol_binding          manifest.auth (via ResolvedAuth)
─────────────────────────          ────────────────────────────────
mcp_stdio  → StdioTransport        env    → injected into child env
mcp_http   → StreamableHttp        header → HTTP request header
mcp_sse    → SSETransport          query  → ?param=token appended to URL
                                   oauth  → delegated to fastmcp.OAuth
```

### Secret flow: from `.env` to the wire

```
.env / shell environment
    │
    │  TokenResolver.resolve()
    │  (loads .env without overriding existing exports, reads the named var)
    ▼
ResolvedAuth
    │
    │  MCPClient builds the transport
    ▼
header:  Authorization: Bearer <token>  /  X-Api-Key: <token>
query:   https://server/mcp/?tavilyApiKey=<token>
env:     child process env["RESEND_API_KEY"] = <token>
oauth:   no static secret — browser authorization + token lifecycle in fastmcp
```

---

## Known limitations

The following constraints are intentional for the current stage and are tracked for future releases:

| Limitation | Detail |
|------------|--------|
| **OAuth tokens not persisted** | The OAuth token lives in memory only. An OAuth resource will re-authorize via the browser on every fresh process. Persistent storage is planned. |
| **stdio `env_var` source and target share a name** | The env var Axon reads from and the one injected into the child process share the same name. If they need to differ, the model does not yet support that separation. |
| **`ga_proxy` not wired** | Only `pa_direct` resources are exercised. Proxy-routed MCP calls are not yet supported. |
| **HTTP `POST /ga/resources` is A2A-only** | The REST endpoint validates A2A resources only. `axon add mcp` (CLI) is the supported path for MCP registration today. |
| **Auth failures may surface as tool results** | Some servers (e.g. Tavily) return a `401` error as a normal tool result rather than a transport-level error, making auth failures harder to detect programmatically. |

---

## See also

- [Architecture](architecture.md) — the PA/GA model and execution flow
- [CLI reference](cli.md) — all commands and flags
- [Configuration](configuration.md) — contexts, gateways, and data directories
- [Local tools](local-tools.md) — MCP tools the PA calls without a Gateway
