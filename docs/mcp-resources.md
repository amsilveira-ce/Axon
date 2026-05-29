# Third-party MCP resources

Axon can register and call **MCP servers it does not own** — Tavily, Notion,
Resend, and any other server that speaks the Model Context Protocol. This page
explains how a third-party MCP server is proven valid, which scenarios are
supported, how to register one, and the architecture that makes a single client
talk to all of them.

If you are registering an **A2A agent** instead, see
[Architecture → Protocol](architecture.md#protocol). The two flows differ in one
important way, explained next.

## Why MCP resources differ from A2A agents

Registration always needs a way to **prove the resource is valid**. For A2A
agents Axon uses an `axon_token`:

- You run `axon token generate`, then embed that token in the agent's own card
  (`capabilities.extensions[axon].params.token`).
- At registration the GA fetches the card and verifies the token.
- This works because **you control the agent** — you can put the token inside it.
  The token proves *"this resource opted into my registry and presents the proof
  back to me"* (resource → GA).

Third-party MCP servers break that assumption. You do **not** control Tavily's
server, so there is nowhere to embed your token. The self-attestation model has
no place to live.

So for MCP the proof of validity is different:

| | A2A agent | Third-party MCP |
|---|---|---|
| Who presents the token | the **resource** (in its card) | the **operator** (you, at `add mcp`) |
| What the token proves | "the resource opted into my registry" | "I, an authorized operator, sanctioned adding this resource" |
| Proof the resource is real | fetch the agent card | **live connection** + `list_tools()` |
| Fingerprint | hash of the card | hash of `(binding + endpoint/command + tools)` |
| Token requirement | required | **optional** admission token |

The key idea: **the proof of validity for MCP is a live connection.** Axon
actually connects to the server, lists its tools (which proves it exists, is
reachable, and what it can do), and fingerprints the result. An `axon_token` can
still be attached — but as an *admission* token you present, not something the
resource carries.

## Supported scenarios

A resource is described by two orthogonal axes, both stored on the
`ResourceManifest`:

- **Transport** (`ProtocolBinding`) — *how to reach it*
- **Auth** (`AuthConfig`: `scheme` + `location`) — *how to authenticate*

Every combination below is driven by the same client. Real examples:

| Server | Transport | Auth scheme | Auth location | Notes |
|--------|-----------|-------------|---------------|-------|
| Tavily | `mcp_http` | `api_key` | `query` | key sent as `?tavilyApiKey=...` |
| Resend | `mcp_stdio` | `api_key` | `env` | key injected into the child process env |
| Notion | `mcp_http` | `oauth` | — | browser-based OAuth, delegated to fastmcp |
| Hugging Face | `mcp_http` | `bearer` | `header` | `Authorization: Bearer hf_...` |
| (generic) | any | `none` | — | no authentication |

`AuthScheme` values: `none`, `bearer`, `api_key`, `oauth`.
`AuthLocation` values (where an `api_key` goes): `header`, `query`, `env`.

## Adding a resource: `axon add mcp`

`add mcp` registers a resource into the **active Gateway context** (check it with
`axon ga list`, switch with `axon ga use <name>`).

```
axon add mcp NAME  (one transport)  [auth flags]  [--token ...]  [--tag ...]
```

Transport — choose exactly one:

| Flag | Transport | Example value |
|------|-----------|---------------|
| `--http URL` | Streamable HTTP | `https://mcp.tavily.com/mcp/` |
| `--sse URL` | SSE (legacy) | `https://example.com/sse` |
| `--stdio "CMD"` | local process | `"npx -y resend-mcp"` |

Auth flags:

| Flag | Meaning |
|------|---------|
| `--auth none\|bearer\|api_key\|oauth` | credential type (default `none`) |
| `--location header\|query\|env` | where the `api_key` goes (default `header`) |
| `--header NAME` | header name when `location=header` (e.g. `X-Api-Key`) |
| `--param NAME` | query param name when `location=query` (e.g. `tavilyApiKey`) |
| `--env-var NAME` | env var that holds the secret (e.g. `RESEND_API_KEY`) |
| `--scope SCOPE` | OAuth scope (repeatable) |

Other:

| Flag | Meaning |
|------|---------|
| `--token axon_tk_...` | optional admission token — verified and consumed at registration |
| `--tag TAG` | capability tag for retrieval (repeatable) |
| `--description TEXT` | human description |

### Examples

```bash
# Tavily — API key in the query string
axon add mcp tavily --http https://mcp.tavily.com/mcp/ \
  --auth api_key --location query --param tavilyApiKey --env-var TAVILY_API_KEY \
  --tag web_search

# Resend — stdio, secret injected into the child process env
axon add mcp resend --stdio "npx -y resend-mcp" \
  --auth api_key --location env --env-var RESEND_API_KEY \
  --tag email

# Notion — OAuth (the validation step opens your browser to authorize)
axon add mcp notion --http https://mcp.notion.com/mcp \
  --auth oauth --tag docs
```

### With an admission token

If your Gateway requires operator authorization, attach a framework token. It is
verified (`verify_local`) and consumed (`mark_used`) during registration, and the
resource keeps a reference to it (`token_ref`):

```bash
TOKEN=$(axon token generate --name tavily | grep -o 'axon_tk_[A-Za-z0-9_-]*')

axon add mcp tavily --http https://mcp.tavily.com/mcp/ \
  --auth api_key --location query --param tavilyApiKey --env-var TAVILY_API_KEY \
  --token "$TOKEN"
```

The token moves to `used` and is bound to the resource id — check with
`axon token list --all`.

### Worked example: Hugging Face (bearer token in a header)

Hugging Face exposes a remote MCP server. Its config (generated at
[huggingface.co/settings/mcp](https://huggingface.co/settings/mcp)) sends a
Hugging Face access token in the `Authorization` header:

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

In Axon terms this is the **`bearer` / `header`** scenario: transport `mcp_http`,
auth scheme `bearer` (which always means `Authorization: Bearer <token>`), with
the secret resolved from an env var. Step by step:

1. **Get a Hugging Face token.** Create one at
   [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
   (a read or fine-grained token). It looks like `hf_xxxxxxxx`.

2. **Put it where the resolver can find it.** Add it to the project `.env`
   (auto-loaded — no manual `export` needed):

   ```dotenv
   HF_TOKEN=hf_xxxxxxxx
   ```

   The env var name is your choice; you point `--env-var` at it. (If you omit
   `--env-var`, the resolver infers `AXON_SECRET_HUGGINGFACE` from the resource
   name instead.)

3. **(Optional) Mint an admission token** if your Gateway gates registration:

   ```bash
   TOKEN=$(axon token generate --name huggingface | grep -o 'axon_tk_[A-Za-z0-9_-]*')
   ```

4. **Register it.** One transport (`--http`), scheme `bearer`, and the env var:

   ```bash
   axon add mcp huggingface \
     --http https://huggingface.co/mcp \
     --auth bearer --env-var HF_TOKEN \
     --tag models --tag datasets --tag papers --tag search \
     # --token "$TOKEN"   # add this line if you minted an admission token
   ```

5. **What Axon does.** It reads `HF_TOKEN` from `.env`, connects live to
   `https://huggingface.co/mcp` sending `Authorization: Bearer hf_…`, lists the
   tools (Model Search, Dataset Search, Papers Semantic Search, Documentation
   Semantic Search, …), fingerprints them, verifies the admission token if given,
   and writes the resource into the active context's `registry.json`.

6. **Confirm.** `axon ga resource list` shows `huggingface` as `online` with its
   tools as skills.

> Note: the Hugging Face settings page can also generate an OAuth-based config for
> some clients. If you prefer that, register with `--auth oauth` instead (no
> `--env-var`), and the browser flow runs during the live-connect step — the same
> path as the Notion example above.

### What happens during registration

```
axon add mcp ...
    ↓
build ResourceManifest        (transport + auth from the flags)
    ↓
validate_mcp()                live connect via MCPClient → list_tools()   ← proof of validity
    ↓
fingerprint                   sha256(binding + endpoint/command + tools)
    ↓
verify admission token        (only if --token was given)
    ↓
persist Resource              .axon/ga/{context}/registry.json
    ↓
mark token used               (only if --token was given)
```

If the live connection fails, registration aborts — nothing is written.

## What gets stored

Each registered resource lives in `.axon/ga/{context}/registry.json` as a
`Resource`:

- `type` = `mcp`, `protocol_binding`, and either `endpoint` (HTTP/SSE) or
  `command` (stdio)
- `auth` — the full `AuthConfig` (scheme, location, header/param, env var name,
  scopes) so the PA can rebuild the manifest later
- `skills` — one per discovered tool (the tool name), used for retrieval
- `fingerprint` — detects drift if the server's tool set changes
- `token_ref` — the admission token, if one was used

**Secrets are never stored.** The registry holds only the *name* of the env var,
never its value. The actual secret is resolved at call time (see below).

## Architecture

### The contract: `ResourceManifest`

Everything the PA needs to call a resource is captured in one object — no
per-resource code. The two axes again:

```
ResourceManifest
├── protocol_binding   how to reach it   (mcp_http | mcp_sse | mcp_stdio | A2A)
└── auth: AuthConfig   how to authenticate
        ├── scheme     none | bearer | api_key | oauth
        ├── location   header | query | env        (for api_key)
        ├── header / param / env_var               (the credential's name/source)
        └── scopes / client_id_env / client_secret_env   (for oauth)
```

### Resolving the secret: `TokenResolver`

The resolver (`axon.pa.token_resolver`) turns an `AuthConfig` into a concrete
credential at runtime:

- It **auto-loads `.env`** from the project root (without overriding real shell
  exports), so `RESEND_API_KEY=...` in `.env` is enough — no manual `export`.
- It reads the secret from the env var (`--env-var`, or the convention
  `AXON_SECRET_<NAME>`), and returns a location-aware `ResolvedAuth`:
  - `header` → `as_headers()` — an HTTP header
  - `query`  → `apply_to_url()` — appended to the URL as `?param=token`
  - `env`    → `as_env()` — injected into the stdio child process environment
- For `oauth` it returns nothing: there is no static secret. The browser flow is
  delegated to the MCP client.

### Driving the connection: `MCPClient`

`axon.pa.clients.mcp_client.MCPClient` consumes a `ResourceManifest`, asks the
`TokenResolver` for the credential, and builds the right transport:

```
manifest.protocol_binding        manifest.auth (via ResolvedAuth)
─────────────────────────        ──────────────────────────────
mcp_stdio  → StdioTransport       env    → injected into child env
mcp_http   → StreamableHttp       header → HTTP header
mcp_sse    → SSETransport         query  → ?param=token in the URL
                                  oauth  → delegated to fastmcp.OAuth
```

The same `MCPClient` is used by `add mcp` to validate a resource and (in the
roadmap) by the Executor to actually call its tools.

### Where the secret travels

```
.env / shell env
    │  TokenResolver.resolve()        (loads .env, reads the env var)
    ▼
ResolvedAuth
    │  MCPClient builds the transport
    ▼
header:  Authorization / X-Api-Key:  <token>
query:   https://server/mcp/?param=<token>
env:     child process environment[<NAME>] = <token>
oauth:   no static secret — browser authorization + token managed by fastmcp
```

## Current limitations

These are known and intentional for the current stage:

- **OAuth token is not persisted** — it lives in memory, so an OAuth resource
  re-authorizes (browser) on every fresh process. Persistent storage is planned.
- **stdio `env_var` is both source and target** — the env var Axon reads from and
  the one injected into the child share a name. If they must differ, the model
  does not yet separate them.
- **`ga_proxy` is not wired** — only `pa_direct` resources are exercised.
- **The HTTP endpoint `POST /ga/resources` validates A2A only** — `axon add mcp`
  (CLI) is the supported path for MCP registration today.
- **Auth failures can surface as tool results** — some servers (e.g. Tavily)
  return a `401` payload as a normal tool result rather than a transport error.

## See also

- [Architecture](architecture.md) — the PA/GA model and execution flow
- [CLI reference](cli.md) — all commands
- [Configuration](configuration.md) — contexts, gateways, and data dirs
- [Local tools](local-tools.md) — MCP tools the PA calls without a Gateway
