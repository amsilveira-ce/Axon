# CLI reference

The `axon` CLI is your single entry point into the Axon system. Every operation — initializing a workspace, registering agents and tools, querying the Principal Agent, managing gateways — flows through it. You do not need to edit configuration files manually; the CLI keeps `axon.config.json` and `.axon/` consistent for you.

This page is a complete reference organized by command group. If you are seeing Axon for the first time, start with [Getting started](getting-started.md), which walks through the most common commands in order. Come back here when you need exact flag names or want to understand edge cases.

## Command overview

| Command | What it does |
|---|---|
| `axon init` | Create a workspace (`axon.config.json` + `.axon/`) in the current directory |
| `axon token` | Create, list, and revoke registration tokens for agents and tools |
| `axon add` | Register a resource with the Gateway — an A2A agent or an MCP server |
| `axon pa run` | Send a one-shot query to the Principal Agent |
| `axon pa chat` | Start an interactive session with the Principal Agent |
| `axon pa config` | Show or edit the Principal Agent configuration |
| `axon pa skills` | Manage the skill files that steer intent extraction |
| `axon pa tools` | Manage the local MCP tools the Principal Agent can call directly |
| `axon pa gateway` | Connect to Gateway Agents and inspect their resources |
| `axon pa policy` | Show or edit the resource policy the Resolver enforces |
| `axon ga` | Gateway Agent commands (serve, list and ping resources) |

Every command supports `--help`. Running a command group with no subcommand (for example `axon pa`) prints its help text.

---

## axon init

Use `axon init` once per project, before anything else. It creates the workspace that every other command depends on: a configuration file and a runtime data directory that holds the registry, tokens, sessions, conversation history, and default local tools.

```bash
axon init [--defaults] [--data-dir <path>]
```

| Flag | Description |
|---|---|
| `--defaults`, `-d` | Use all default values without prompting |
| `--data-dir <path>` | Directory for runtime data (default: `.axon`) |

`axon init` creates two things:

- **`axon.config.json`** — your configuration file (see [Configuration](configuration.md))
- **`.axon/`** — the runtime data directory: registry, tokens, sessions, conversation history, and the default local tools

It also registers four ready-to-use local tools (`calculator`, `web_search`, `file_reader`, `datetime_tool`). See [Local tools](local-tools.md).

**Expected output**

```text
✓ Created axon.config.json
✓ Created .axon/
✓ Registered local tool: calculator
✓ Registered local tool: web_search
✓ Registered local tool: file_reader
✓ Registered local tool: datetime_tool

Workspace ready. Next steps:
  1. axon token generate --name <agent-name>   # create an admission token
  2. axon add agent <url>                       # register your first agent
  3. axon pa run -q "hello"                     # send a query
```

> **Note:** If a workspace already exists, `axon init` refuses to overwrite it. To start over, run `bash scripts/reset.sh`.

---

## axon token

Before an agent or MCP server can register with your Gateway, it must prove it is authorized to do so. Tokens are how that proof works: you generate a single-use secret here, embed it in the resource, and the Gateway consumes it during registration.

This section covers generating new tokens, auditing their state, and revoking ones that should no longer be accepted.

> **Warning:** Treat tokens like passwords. Anyone holding a token can register a resource with your Gateway. Do not commit tokens to version control, log them, or share them over unencrypted channels. Use `axon token revoke` immediately if a token is exposed.

### axon token generate

```bash
axon token generate --name <name>
```

| Flag | Description |
|---|---|
| `--name`, `-n` | Name of the agent or tool this token authorizes (required) |

Generates one single-use token and prints a snippet you can paste into the agent card (under `capabilities.extensions`) or an MCP manifest. The token must be embedded in the resource before you run `axon add agent`.

A token can only be used once: the Gateway consumes and invalidates it on the first successful `axon add`. If registration fails after token validation, generate a new token before retrying.

**Expected output**

```text
✓ Token generated for "my-analysis-agent"

  Token: axon_tk_7f3a9b2c1d4e8f6a...

  Paste this into your agent card under capabilities.extensions:

    "axon": {
      "token": "axon_tk_7f3a9b2c1d4e8f6a..."
    }

  This token is single-use and expires after the first successful registration.
```

### axon token list

```bash
axon token list [--all]
```

| Flag | Description |
|---|---|
| `--all` | Include used and revoked tokens (default shows only pending) |

By default, only pending (not yet consumed) tokens are shown. Pass `--all` to audit the full history, including tokens that have been used or manually revoked.

### axon token revoke

```bash
axon token revoke <token>
```

Revokes a token so it can no longer be used. Resources already registered with it are not removed immediately — their status updates on the next health check.

---

## axon add

Use `axon add` to register a resource — an A2A agent or a third-party MCP server — with the Gateway. Once registered, the resource appears in the registry and the Principal Agent can discover and route tasks to it.

Registration is not just bookkeeping: Axon validates the resource is reachable, checks its identity, and stores the fingerprint it will use for ongoing health checks.

### axon add agent

```bash
axon add agent <url> [--name <name>]
```

| Argument / Flag | Description |
|---|---|
| `<url>` | The agent's A2A endpoint, e.g. `http://localhost:8000` |
| `--name` | Override the resource name (default: the name in the agent card) |

The agent must be running and expose an agent card at `/.well-known/agent.json` containing a valid Axon token. Axon fetches the card, validates the token, runs a health check, and stores the resource in the registry.

**Expected output**

```text
Registering agent at http://localhost:8000 ...

  ✓ Fetched agent card: my-analysis-agent v1.2.0
  ✓ Token validated and consumed
  ✓ Health check passed (42 ms)
  ✓ Fingerprint stored

  Resource registered:
    name:        my-analysis-agent
    url:         http://localhost:8000
    capabilities: analyze, summarize, report
    status:      healthy
```

### axon add mcp

Registers a third-party **MCP server** (Tavily, Resend, Notion, …). Unlike an A2A agent, the server carries no Axon token, so it is proven valid by a **live connection**: Axon connects, calls `list_tools()`, and fingerprints the result. See [Third-party MCP resources](mcp-resources.md) for the full model.

```bash
axon add mcp <name> ( --http <url> | --sse <url> | --stdio "<cmd>" ) [options]
```

Exactly one transport is required.

| Argument / Flag | Description |
|---|---|
| `<name>` | Resource name, e.g. `tavily` (also drives the `AXON_SECRET_<NAME>` convention) |
| `--http <url>` | MCP Streamable HTTP endpoint |
| `--sse <url>` | MCP SSE endpoint |
| `--stdio "<cmd>"` | MCP stdio command, e.g. `"npx -y resend-mcp"` |
| `--auth` | Auth scheme: `none` (default), `bearer`, `api_key`, `oauth` |
| `--location` | For `api_key`: `header` (default), `query`, or `env` |
| `--header` | Header name when `--location header`, e.g. `X-Api-Key` |
| `--param` | Query param name when `--location query`, e.g. `tavilyApiKey` |
| `--env-var` | Env var holding the secret (default: inferred `AXON_SECRET_<NAME>`) |
| `--scope` | OAuth scope (repeatable) |
| `--tag` | Capability tag the PA matches against (repeatable) |
| `--paid` / `--free` | Whether the resource charges per call (default: `--free`) |
| `--cost-per-call` | Estimated USD cost per call |
| `--token` | Optional Axon admission token (`axon_tk_…`), verified and consumed at registration |
| `--description` | Description used for matching (synthesized from the tools if omitted) |

`--paid` and `--cost-per-call` are stored on the resource's policy and later enforced by the Resolver against the operator's policy — see [Resource resolution → Step 3](resolver.md#step-3--the-operator-policy-filter).

```bash
# Tavily — API key in the query string
axon add mcp tavily --http https://mcp.tavily.com/mcp/ \
  --auth api_key --location query --param tavilyApiKey \
  --tag web_search

# a paid resource, priced per call
axon add mcp some-llm --http https://api.example.com/mcp/ \
  --auth bearer --paid --cost-per-call 0.002 --tag summarize
```

---

## axon pa

The **Principal Agent (PA)** is the part of Axon you talk to. It takes a natural-language request, works out what you actually want (intent extraction), and coordinates the work needed to answer it.

`axon pa` groups every PA-related command:

- [`axon pa run`](#axon-pa-run) — ask the PA a single question
- [`axon pa chat`](#axon-pa-chat) — have a back-and-forth conversation
- [`axon pa config`](#axon-pa-config) — view and change PA settings
- [`axon pa skills`](#axon-pa-skills) — tune how the PA understands requests
- [`axon pa tools`](#axon-pa-tools) — manage the tools the PA can use directly
- [`axon pa gateway`](#axon-pa-gateway) — connect Gateway Agents and inspect their resources
- [`axon pa policy`](#axon-pa-policy) — control which resources the PA may use

### axon pa run

Use `axon pa run` when you want a single answer and do not need a back-and-forth conversation. It is well suited to scripts, cron jobs, and any situation where you know exactly what you want upfront.

```bash
axon pa run --query "<query>" [--lang <language>] [--verbose]
```

| Flag | Description |
|---|---|
| `--query`, `-q` | The request to send to the PA (required) |
| `--lang`, `-l` | Reply in this language, e.g. `Portuguese`, `Spanish`. Default: English |
| `--verbose`, `-v` | Show the context injected into the model and the extraction details |

When `--lang` is set, Axon translates your query to English before processing and translates the response back — the PA always reasons in English internally.

Use `--verbose` when a result is not what you expected: it prints the exact context (conversation history, memory, available resources) that was sent to the model, which is the fastest way to understand the PA's decision.

```bash
# a plain English query
axon pa run -q "Create a report about Q3 results"

# ask and answer in Portuguese
axon pa run -q "Resumir as vendas do Q3" -l Portuguese

# inspect what the PA saw before answering
axon pa run -q "Analyze patient data" -v
```

**Example verbose output**

When you pass `-v`, Axon prints the full context sent to the model before the answer:

```text
[verbose] session: ses_4f2a1b
[verbose] history: 0 messages
[verbose] memory: 2 entries
[verbose] resources available: 3
  - tavily          (web_search)   ✓ eligible
  - my-analysis-agent (analyze)   ✓ eligible
  - some-llm        (summarize)   ✗ auth-missing

[verbose] intent extracted:
  objective: create a Q3 sales report
  resources_needed: [my-analysis-agent]
  confidence: 0.91

─────────────────────────────────────────────
Here is the Q3 results report ...
```

Each run is saved as a session under `.axon/pa/sessions/`. The session ID is printed with the response so you can resume it later with `axon pa chat`.

### axon pa chat

Use `axon pa chat` for exploratory work, multi-step tasks, or any request that may need clarification before the PA can act. Unlike `axon pa run`, the session stays open and the PA can ask follow-up questions.

```bash
axon pa chat [--session <id>] [--lang <language>] [--verbose]
```

| Flag | Description |
|---|---|
| `--session`, `-s` | Resume an existing session by its ID |
| `--lang`, `-l` | Conduct the conversation in this language |
| `--verbose`, `-v` | Show the context injected into the model and the extraction details |

If a request is ambiguous, the PA does not guess — it asks follow-up questions and waits for your answer before proceeding. `axon pa chat` handles up to three of these clarification rounds automatically:

```text
  you: analyze the patient data

  ◇ extracting intent...
  │
  I understand that you want to analyze patient data.

  1. Which patient should be analyzed?
  2. What type of analysis is needed?
     clinical summary  /  lab results  /  full report

  you: John Silva, full report

  ◆ objective identified
  │  generate a full clinical report for patient John Silva
```

Press `Ctrl+C` to exit. Conversation history is persisted per session, so a later `axon pa chat --session <id>` picks up where you left off.

> **Tip:** You can find session IDs by looking in `.axon/pa/sessions/` or from the session ID printed at the end of any `axon pa run`. Use `axon pa chat --session <id>` to continue a run that you want to refine interactively.

### axon pa config

Use `axon pa config` to inspect or adjust the Principal Agent's behavior: the model it uses, how it reasons, what budget limits apply, and which gateways it talks to. All changes are written to `axon.config.json`.

```bash
# show the current configuration
axon pa config

# edit one or more fields
axon pa config --llm llama3.2 --temperature 0.2
```

Run with **no flags** to print the full configuration. Run with **one or more flags** to change those fields and save the file. Every flag below maps to a field documented in [Configuration](configuration.md).

**Model**

| Flag | Description |
|---|---|
| `--llm` | LLM model name, e.g. `deepseek-r1:14b`, `llama3.2` |
| `--temperature` | Sampling temperature, `0.0`–`1.0` (lower = more deterministic) |

**Reasoning**

| Flag | Description |
|---|---|
| `--reasoning-mode` | Reasoning strategy: `react`, `rewoo`, or `tot` |
| `--max-iterations` | Maximum planning/execution cycles per request |

**Domain**

| Flag | Description |
|---|---|
| `--domain` | Activate a domain skill (e.g. `clinical`). Use `none` to deactivate |

The domain must already exist as a skill file. Create one with `axon pa skills new` — see [Skills](skills.md).

**Budget** — hard limits that stop a single run from overspending:

| Flag | Description |
|---|---|
| `--budget-tokens` | Maximum tokens per run |
| `--budget-cost` | Maximum cost in USD per run |
| `--budget-calls` | Maximum LLM calls per run |
| `--budget-timeout` | Maximum execution time in milliseconds |

**Conversation** — how much history the PA keeps in its working context:

| Flag | Description |
|---|---|
| `--conversation-max-messages` | Maximum messages kept in the active window |
| `--conversation-max-tokens` | Maximum tokens kept in the active window |
| `--conversation-window-mode` | How the window is measured: `messages`, `tokens`, or `both` |

**Cache** — the cross-session resource cache:

| Flag | Description |
|---|---|
| `--cache` | Enable or disable the resource cache: `true` or `false` |
| `--cache-max-size` | Maximum number of cached resources |

**Gateways** — the Gateway Agents this PA can request resources from:

| Flag | Description |
|---|---|
| `--gateway-add` | Add a Gateway URL |
| `--gateway-remove` | Remove a Gateway URL |

> **Note:** Prefer [`axon pa gateway add`](#axon-pa-gateway) to connect a gateway: it fetches the gateway card, registers the connection, and shows the resources and their eligibility. These config flags are the low-level equivalent.

> **Warning:** Changes to the model, domain, or reasoning mode only take effect on the next `axon pa run` or `axon pa chat`. The command reminds you when a restart is needed — do not assume the change is live until you start a new session.

```bash
# point the PA at a different model and warm it up
axon pa config --llm deepseek-r1:14b --temperature 0.0

# activate the clinical domain
axon pa config --domain clinical

# tighten the per-run budget
axon pa config --budget-tokens 30000 --budget-cost 0.25

# connect a Gateway Agent
axon pa config --gateway-add http://localhost:5000
```

### axon pa skills

Skill files are Markdown files that tell the PA *how* to read a request during intent extraction. Editing a skill changes the PA's behavior without touching any code — they are the primary tuning surface for domain-specific deployments.

There are two kinds of skill file:

- **Base skill** (`intent_extraction.md`) — always active. Defines the general behavior of the intent extractor.
- **Domain skills** (`domains/<name>.md`) — optional. Layered on top of the base skill when a domain is activated, to add field-specific rules (for example, clinical or finance).

For the concepts behind skills and domains, see [Skills](skills.md). The commands:

```bash
axon pa skills list
axon pa skills show [--domain <name>]
axon pa skills new --domain <name>
axon pa skills validate
axon pa skills reset [--contract-only]
```

| Subcommand | Description |
|---|---|
| `list` | List the base skill and all domains; shows which domain is active and whether the output contract is intact |
| `show` | Print a skill file. Omit `--domain` to show the base skill |
| `new --domain <name>` | Create a new domain skill file from a template |
| `validate` | Check that the base skill's output contract is unmodified |
| `reset` | Restore the base skill to its default content |

| Flag | Applies to | Description |
|---|---|---|
| `--domain`, `-d` | `show`, `new` | Domain name (e.g. `clinical`, `finance`) |
| `--contract-only` | `reset` | Restore only the output contract, keeping your behavior edits |

> **Note:** The bottom of the base skill defines the exact JSON the PA's parser expects. If you edit a skill, do not change that section. Run `axon pa skills validate` to confirm it is intact; `axon pa skills reset --contract-only` repairs it without discarding your other edits.

```bash
# see what skills exist and which domain is active
axon pa skills list

# create and then activate a finance domain
axon pa skills new --domain finance
# (edit src/axon/pa/skills/domains/finance.md in your editor)
axon pa config --domain finance
```

### axon pa tools

Local tools are MCP tools the Principal Agent can call directly, without going through a Gateway Agent. `axon init` registers four by default; these commands let you list, add, and toggle them.

Use local tools for capabilities that are always available on the host machine — calculators, file readers, internal APIs — and use Gateway Agents for capabilities that may be distributed, scaled, or shared across PA instances.

For the concepts and the built-in tools, see [Local tools](local-tools.md).

```bash
axon pa tools list
axon pa tools add --name <name> --command "<cmd>" --capability <tag> --description "<text>"
axon pa tools remove <name>
axon pa tools enable <name>
axon pa tools disable <name>
```

| Subcommand | Description |
|---|---|
| `list` | List every registered tool, its capability, command, and enabled state |
| `add` | Register a new local tool |
| `remove <name>` | Permanently remove a tool |
| `enable <name>` | Re-enable a disabled tool |
| `disable <name>` | Disable a tool without removing it |

Options for `axon pa tools add`:

| Flag | Description |
|---|---|
| `--name` | A unique name for the tool (required) |
| `--command` | The command that runs the tool, e.g. `python -m my.tool` (required) |
| `--capability` | A capability tag the PA matches against, e.g. `web_search` (required) |
| `--description`, `-d` | What the tool does — the PA uses this to decide *when* to call it (required) |
| `--transport` | How Axon talks to the tool: `stdio` (default) or `http` |

The `--description` is required on purpose: without it, the PA has no way to decide which tool fits a task. Be specific — *"searches patient records in the HStory EHR"* is far more useful than *"searches records"*.

Before a tool is saved, `axon pa tools add` validates the command. For `stdio` it confirms the module or executable exists; for `http` it checks the endpoint is reachable. A tool that fails validation is not registered.

```bash
# list the four default tools
axon pa tools list

# register a custom local tool
axon pa tools add \
  --name sales_report \
  --command "python -m mycompany.tools.sales" \
  --capability sales_data \
  --description "Fetches quarterly sales figures and returns a structured report"

# temporarily turn off web access
axon pa tools disable web_search
```

### axon pa gateway

Gateway Agents are remote registries that expose resources — A2A agents and MCP servers — to the PA. Use `axon pa gateway` to connect to them, inspect what they offer, and check which resources are currently eligible under your policy.

A connected gateway is recorded in `axon.config.json` under `pa.gateways`.

```bash
axon pa gateway add <url>
axon pa gateway list
axon pa gateway remove <url>
axon pa gateway ping [<url>]
axon pa gateway resources [--filter <f>] [--context <ga>]
```

| Subcommand | Description |
|---|---|
| `add <url>` | Connect to a gateway (see the three steps below) |
| `list` | List connected gateways with live online/offline status |
| `remove <url>` | Disconnect a gateway |
| `ping [<url>]` | Check reachability and refresh `last_seen` (all gateways if `<url>` omitted) |
| `resources` | List resources across connected gateways with policy eligibility |

**`add` runs three steps:**

1. `GET /ga/card` — fetch the gateway card and check its `trust_level` (you are warned before connecting to an `unknown` gateway).
2. `POST /pa/connect` — announce this PA to the gateway, which records the connection.
3. `GET /ga/resources` — list the gateway's resources and print an eligibility table evaluated against your current [policy](#axon-pa-policy).

**Expected output from `axon pa gateway add`**

```text
Connecting to http://ga-corp.example.com/ ...

  ✓ Gateway card fetched: ga-corp (trust_level: verified)
  ✓ PA registered with gateway

  Resources available (4):

  NAME                 CAPABILITY     AUTH        COST      STATUS
  ──────────────────   ────────────   ─────────   ───────   ──────────────────
  tavily               web_search     api_key     free      ✓ eligible
  my-analysis-agent    analyze        none        free      ✓ eligible
  resend-mcp           email_send     api_key     free      ✗ auth-missing (set AXON_SECRET_RESEND)
  some-llm             summarize      bearer      paid      ✗ policy (allow-paid: false)
```

**`resources` filters:**

| Flag | Value | Shows |
|---|---|---|
| `--filter` | `eligible` | only resources ready to use right now |
| `--filter` | `auth-missing` | only resources needing a token — and which `AXON_SECRET_*` to set |
| `--filter` | `paid` | only paid resources — to decide whether to allow them |
| `--context` | `<name\|url>` | restrict to a single gateway |

The `status` column (`✓ pronto` / `✗ <reason>`) is produced by the **same evaluation the Resolver uses** to pick resources — what shows as ready is what the PA would actually use. See [Resource resolution](resolver.md).

```bash
# connect and immediately see what's available
axon pa gateway add http://ga-corp.example.com/

# what still needs a token?
axon pa gateway resources --filter auth-missing

# only one gateway, only the ready resources
axon pa gateway resources --context ga-corp --filter eligible
```

### axon pa policy

The resource policy is the operator's rule set for which resources the PA is allowed to use. The Resolver applies this policy to every resource a gateway returns, discarding the ones that fail. Use `axon pa policy` to inspect and tighten these rules — especially before enabling paid resources or connecting to external gateways.

Policy is stored in `axon.config.json` under `pa.resource_policy`.

```bash
# show the current policy
axon pa policy

# edit one or more fields
axon pa policy set --allow-paid true --match-threshold 0.75
```

| Flag | Description |
|---|---|
| `--allow-paid` | `true` / `false` — may the PA use paid resources? |
| `--max-cost-per-call` | Maximum USD per call (`0` = no limit) |
| `--match-threshold` | Minimum GA match score (`0.0`–`1.0`) to accept a resource |
| `--fallback-strategy` | What to do when nothing is eligible: `skip`, `fail`, or `ask_user` |

The policy covers economics (paid / cost) and acceptance threshold. Auth is not a policy choice: a resource with `auth != none` whose token is not configured is always discarded by the Resolver (Step 4, fail-fast). How the Resolver applies all of this is in [Resource resolution](resolver.md#step-3--operator-policy-paid--cost).

```bash
# a strict policy: no paid resources, cheap calls only
axon pa policy set --allow-paid false --max-cost-per-call 0.01

# later, allow paid resources after reviewing them
axon pa policy set --allow-paid true
```

> **Warning:** Policy changes take effect on the next `axon pa run` or `axon pa chat`. If you tighten the policy while a session is in progress, the current session continues under the old policy.

---

## axon ga

Gateway Agent commands manage the GA process itself and let you inspect the resources it holds. You will typically run `axon ga serve` once per environment (or wire it into a process supervisor) and use the resource commands for debugging and health checks.

### axon ga serve

```bash
axon ga serve
```

Starts the Gateway Agent API server on the port configured in `axon.config.json` (default: `5000`).

Run this command when you want the GA to accept incoming connections from Principal Agents. In a local development setup, run it in a separate terminal before calling `axon pa gateway add`. In production, wire it into your process supervisor (systemd, Docker, etc.) so it starts automatically.

> **Note:** You do not need to run `axon ga serve` if you are only using the PA to talk to a remote Gateway Agent that someone else operates. You only need it when *you* are hosting the Gateway.

### axon ga resource list

```bash
axon ga resource list
```

Lists all resources registered in the GA.

### axon ga resource ping

```bash
axon ga resource ping [--all] [<name>]
```

Verifies reachability and fingerprint of registered resources.

---

## See also

- [Getting started](getting-started.md) — end-to-end walkthrough using the commands above
- [Configuration](configuration.md) — full reference for every field in `axon.config.json`
- [Local tools](local-tools.md) — the four built-in tools and how to add your own
- [Skills](skills.md) — how the intent extractor works and how to write domain skills
- [Third-party MCP resources](mcp-resources.md) — auth patterns, fingerprinting, and the `AXON_SECRET_*` convention
- [Resource resolution](resolver.md) — the four-step pipeline the Resolver uses to pick resources for each request
