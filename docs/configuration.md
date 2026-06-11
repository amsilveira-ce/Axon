# Configuration

`axon.config.json` is the single source of truth for how your Axon workspace
behaves. It controls everything from which language model the Principal Agent
uses to how many tokens it may spend in a single run. Every field has a
sensible default, so a fresh workspace works without any editing — but knowing
what each knob does lets you tune Axon for your workload.

## Two ways to configure

You can change settings in two ways, and they are not equivalent:

| Approach | When to use | Trade-offs |
|---|---|---|
| **`axon pa config <flag>`** | Day-to-day adjustments and automation | Validates the value, saves the file, and prints a restart notice when one is needed. Recommended for all normal use. |
| **Editing `axon.config.json` directly** | Bulk changes, templating, or CI pipelines | Faster when touching many fields at once, but you are responsible for keeping the JSON valid and for knowing which changes need a restart. |

> **Tip:** Use `axon pa config` for single-field changes and direct file
> editing for large configuration templates you check into version control.

## Quick reference

| Top-level key | Purpose |
|---|---|
| `version` | Schema version — managed by Axon, do not edit by hand |
| `data_dir` | Where Axon stores all runtime data on disk |
| `pa` | Everything about the Principal Agent (LLM, budget, memory, cache, …) |
| `ga` | Gateway Agent network port |

## axon.config.json

A freshly initialized file looks like this:

```json
{
  "version": "0.1.0",        // Schema version — do not change manually
  "data_dir": ".axon",       // Runtime data directory (overridable via AXON_DATA_DIR)
  "pa": {
    "port": 4100,            // PA control API port
    "default_reasoning": "rewoo",  // Planning strategy: rewoo | react | tot
    "max_iterations": 10,    // Safety cap on planning cycles per request
    "gateways": [],          // Gateway Agent URLs the PA can delegate to
    "llm": {
      "host": "http://localhost:11434",  // Ollama server URL
      "model": "deepseek-r1:14b",        // Model for intent extraction and reasoning
      "temperature": 0.0,                // Determinism dial (0.0 = fully deterministic)
      "timeout": 60                      // Seconds before a single LLM call is aborted
    },
    "budget": {
      "tokens_max": 60000,      // Hard token ceiling per run
      "cost_max_usd": 0.5,      // Hard cost ceiling per run (USD)
      "calls_max": 40,          // Maximum LLM calls per run
      "timeout_ms": 120000.0    // Wall-clock timeout per run (milliseconds)
    },
    "conversation": {
      "max_messages": 10,    // Turns kept in the active context window
      "max_tokens": null,    // Token limit for the window (null = no limit)
      "window_mode": "messages"  // How the window is measured: messages | tokens | both
    },
    "cache": {
      "enabled": true,  // Whether the cross-session resource cache is active
      "max_size": 50    // Maximum cached resources (LRU eviction, not tool count)
    },
    "intent_extractor": {
      "domain": null,   // Active domain skill file (null = base skill only)
      "intents": {}     // Reserved for pre-declared intent definitions
    }
  },
  "ga": {
    "port": 5000  // Gateway Agent API port
  }
}
```

> **Note:** JSON does not allow comments. The annotations above are for
> illustration only — your actual `axon.config.json` will not contain them.

---

## Top-level fields

### `version`

The configuration schema version. Managed by Axon — do not change it by hand.
Axon uses this field to detect when a migration is needed after an upgrade.

### `data_dir`

Directory where Axon stores all runtime data (registry, tokens, sessions,
conversation history, local tools, traces). Defaults to `.axon`, relative to
the current directory. Can be overridden by the `AXON_DATA_DIR` environment
variable — see [Environment variables](#environment-variables).

> **Note:** Changing `data_dir` after a workspace has been running moves
> where Axon *looks* for data, but does not move existing data. Migrate the
> directory contents manually, or start fresh.

---

## Principal Agent (`pa`)

Everything under `pa` configures the [Principal Agent](architecture.md) — the
orchestrator that receives your requests, plans a sequence of tool calls, and
assembles the final answer. The corresponding `axon pa config` flag is listed
for each field.

### Core agent settings

These fields govern the PA's network address, planning strategy, and iteration
budget. They define the agent's fundamental runtime behavior before any model
or memory concerns apply.

| Field | Default | Flag | Description |
|---|---|---|---|
| `port` | `4100` | *(not editable via CLI)* | Port for the PA control API |
| `default_reasoning` | `rewoo` | `--reasoning-mode` | Planning strategy: `rewoo`, `react`, or `tot` |
| `max_iterations` | `10` | `--max-iterations` | Maximum planning/execution cycles per request |
| `gateways` | `[]` | `--gateway-add`, `--gateway-remove` | Gateway Agent URLs the PA can delegate to |

**Reasoning modes explained:**

- `rewoo` — Plans the full sequence of tool calls first, then executes them in
  one pass. Fewer LLM round-trips, lower latency, better for deterministic
  workflows. **Default and recommended for most use cases.**
- `react` — Reasons and acts step by step, inspecting tool output before
  deciding the next action. More adaptive but uses more LLM calls.
- `tot` — Explores multiple reasoning branches (Tree of Thought). Best for
  open-ended problems where the right path is not obvious. Highest token cost.

> **Note:** Changing `default_reasoning` or `port` requires a restart of the
> PA process. Changes to `max_iterations` and `gateways` take effect
> immediately after `axon pa config` saves the file.

---

### `pa.llm` — Language model

The `pa.llm` group controls which language model the PA uses and how it calls
it. Axon uses [Ollama](https://ollama.com) by default, so inference runs
locally on your machine with no external API key required.

| Field | Default | Flag | Description |
|---|---|---|---|
| `host` | `http://localhost:11434` | — | URL of the Ollama server |
| `model` | `deepseek-r1:14b` | `--llm` | Model for intent extraction and reasoning |
| `temperature` | `0.0` | `--temperature` | Sampling temperature, `0.0`–`1.0` |
| `timeout` | `60` | — | Seconds before a single LLM call is aborted |

> **Tip:** Axon defaults to `deepseek-r1:14b` because it is a reasoning model
> — it produces an explicit chain-of-thought before answering, which makes
> multi-step planning significantly more reliable than general-purpose chat
> models. If you need lower latency and your tasks are simpler, `deepseek-r1:7b`
> is a good trade-off. For maximum accuracy on complex agentic tasks, prefer
> the 14b or larger variant.

> **Tip:** `temperature: 0.0` is the default because the PA's job is to
> execute a plan correctly, not to be creative. Deterministic sampling makes
> tool-call sequences reproducible and easier to debug. Raise the temperature
> only if you need the model to generate varied natural-language output (for
> example, in a creative writing workflow).

> **Note:** Make sure the model is pulled in Ollama before starting Axon:
> `ollama pull deepseek-r1:14b`. Changing the model requires a restart.

---

### `pa.budget` — Run limits

The `pa.budget` group sets hard limits applied to a single run. When any limit
is reached the run stops immediately — this protects you from runaway loops
that drain tokens, money, or wall-clock time. Think of these as circuit
breakers, not performance targets.

| Field | Default | Flag | Description |
|---|---|---|---|
| `tokens_max` | `60000` | `--budget-tokens` | Maximum tokens consumed per run |
| `cost_max_usd` | `0.5` | `--budget-cost` | Maximum cost in USD per run |
| `calls_max` | `40` | `--budget-calls` | Maximum number of LLM calls per run |
| `timeout_ms` | `120000.0` | `--budget-timeout` | Maximum execution time per run (milliseconds) |

> **Warning:** When a budget limit is hit mid-run, the PA stops immediately
> and returns a partial result (or an error if no intermediate answer was
> produced). It does **not** attempt to summarize what it completed so far.
> If you are seeing truncated answers, raise the relevant limit — or reduce
> `max_iterations` so the PA does less work per run rather than hitting the
> wall mid-flight.

> **Tip:** Start with the defaults and tighten them once you know your typical
> workload. For cost-sensitive deployments, set `cost_max_usd` to a value you
> are comfortable spending per query; for latency-sensitive deployments, lower
> `timeout_ms` and watch which queries start failing, then optimize those.

> **Note:** Budget limits are evaluated per-run, not per-session. A long
> conversation that completes many short runs can exceed these limits in
> aggregate.

---

### `pa.conversation` — Working memory

The `pa.conversation` group controls the PA's working memory — how much past
conversation it keeps in the active context window. Rather than dropping older
turns entirely, Axon summarizes them, so long sessions stay coherent without
feeding an ever-growing prompt to the model. The sliding window determines how
many recent turns or tokens are kept verbatim before summarization kicks in.
See [The context layer](context-layer.md) for a full explanation of how this
memory pipeline works.

| Field | Default | Flag | Description |
|---|---|---|---|
| `max_messages` | `10` | `--conversation-max-messages` | Maximum messages kept in the active window |
| `max_tokens` | `null` | `--conversation-max-tokens` | Maximum tokens kept in the active window (`null` = no token limit) |
| `window_mode` | `messages` | `--conversation-window-mode` | How the window is measured: `messages`, `tokens`, or `both` |

> **Tip:** `window_mode: "both"` enforces whichever limit is hit first —
> useful when you want to keep at most 10 turns *and* never exceed 4 000
> context tokens at the same time.

> **Note:** Changes to conversation settings take effect on the next turn
> within any session. No restart is required.

---

### `pa.cache` — Resource cache

The `pa.cache` group controls the cross-session resource cache. When enabled,
resources discovered through a Gateway Agent are remembered between runs, so
the PA does not re-discover the same agents every time a new session starts.
See [Resource resolution](resolver.md) for how the Resolver fills and reads it.

| Field | Default | Flag | Description |
|---|---|---|---|
| `enabled` | `true` | `--cache` | Whether the resource cache is active |
| `max_size` | `50` | `--cache-max-size` | Maximum number of cached resources (LRU) |

> **Note:** `max_size` counts **resources**, not tools. One slot is consumed
> per resource — an A2A agent counts as one, and an MCP server counts as one
> even if that server exposes a dozen tools (those tools are skills *inside*
> the resource). An MCP server with 12 tools still occupies a single cache
> slot. Only resources discovered through a Gateway Agent are counted; local
> tools live in the [local pool](local-tools.md) and never take a slot.

> **Note:** Eviction is **LRU by discovery time**. Recency is the order in
> which resources are discovered or refreshed. When the cache exceeds
> `max_size`, the least-recently-discovered resource is dropped. Resources
> that are rediscovered frequently stay in cache; stale ones are evicted. Set
> `max_size` to `0` to disable the size limit entirely (cache grows
> unbounded).

> **Note:** Toggling `enabled` or changing `max_size` takes effect
> immediately — no restart required.

---

### `pa.intent_extractor` — Intent extraction

The `pa.intent_extractor` group configures the intent extraction stage — the
step that translates a natural-language request into a structured objective
before planning begins.

| Field | Default | Flag | Description |
|---|---|---|---|
| `domain` | `null` | `--domain` | Active domain skill (e.g. `clinical`). `null` = base skill only |
| `intents` | `{}` | — | Reserved for pre-declared intent definitions |

> **Note:** The value of `domain` must match an existing skill file before it
> can be activated. If the file does not exist, Axon will reject the
> configuration and fall back to the base skill. See [Skills](skills.md) for
> how to create and register a domain skill file. Changing the domain requires
> a restart.

---

## Gateway Agent (`ga`)

The `ga` group configures the Gateway Agent — the registry that other agents
and MCP servers register with so the PA can discover them.

### `ga.port`

Port for the Gateway Agent API. Default: `5000`. This is the port remote
resources POST their registration to, and the port the PA queries when
resolving resources.

> **Note:** Changing `ga.port` requires a restart of the GA process and an
> update to any remote resources that were registered using the old port.

---

## Environment variables

### `AXON_DATA_DIR`

Overrides `data_dir` from `axon.config.json`. It takes priority over the
config file and accepts absolute or relative paths. This is the standard way
to point Axon at a writable location in a container or production environment
without modifying the config file itself.

```bash
# container / production
AXON_DATA_DIR=/var/lib/axon axon pa run --query "..."

# or in docker-compose
environment:
  - AXON_DATA_DIR=/data/axon
```

> **Tip:** Set `AXON_DATA_DIR` in your container entrypoint rather than
> hardcoding an absolute path in `axon.config.json`. This keeps the config
> file portable across local development and production deployments.

---

## Data directory structure

`axon init` creates the following layout under `data_dir` (`.axon` by default):

```text
{data_dir}/
├── ga/
│   ├── registry.json        # registered resources
│   ├── tokens.json          # registration tokens
│   └── traces/              # GA operation logs
└── pa/
    ├── sessions/            # conversation history, one file per session_id
    ├── resource_cache.json  # cross-session resource cache
    ├── memory_bank.json     # domain defaults and user preferences
    ├── local_tools.json     # local MCP tools (see Local tools)
    └── traces/              # LLM reasoning logs
```

You normally do not edit these files by hand. Use the CLI instead — for
example [`axon pa tools`](cli.md#axon-pa-tools) manages `local_tools.json`.

> **Warning:** Do not share `ga/tokens.json` or commit it to version control.
> It contains the registration tokens that gate write access to the Gateway
> Agent registry.

---

## Common configurations

The following examples show complete `pa` sections for three real-world
scenarios. Copy the relevant block into your `axon.config.json` and adjust as
needed.

### Low-latency setup

Optimized for fast, simple queries where predictability matters more than deep
reasoning. Uses a smaller model, tighter iteration cap, and a short timeout so
failures surface quickly.

```json
"pa": {
  "default_reasoning": "rewoo",
  "max_iterations": 5,
  "llm": {
    "model": "deepseek-r1:7b",
    "temperature": 0.0,
    "timeout": 20
  },
  "budget": {
    "tokens_max": 20000,
    "cost_max_usd": 0.1,
    "calls_max": 15,
    "timeout_ms": 30000.0
  },
  "conversation": {
    "max_messages": 6,
    "max_tokens": null,
    "window_mode": "messages"
  },
  "cache": {
    "enabled": true,
    "max_size": 50
  }
}
```

The smaller 7b model shaves 30–50 % off median latency. The 30-second wall-
clock timeout (`timeout_ms: 30000`) keeps the user experience responsive even
when something goes wrong.

### Cost-controlled setup

Designed for shared or multi-user environments where per-query spend must stay
predictable. Hard token and cost caps are tight; the `react` mode is used
because it uses fewer speculative calls than `rewoo` for short tasks.

```json
"pa": {
  "default_reasoning": "react",
  "max_iterations": 8,
  "llm": {
    "model": "deepseek-r1:14b",
    "temperature": 0.0,
    "timeout": 45
  },
  "budget": {
    "tokens_max": 15000,
    "cost_max_usd": 0.05,
    "calls_max": 10,
    "timeout_ms": 60000.0
  },
  "conversation": {
    "max_messages": 4,
    "max_tokens": null,
    "window_mode": "messages"
  },
  "cache": {
    "enabled": true,
    "max_size": 100
  }
}
```

A larger `cache.max_size` (100) offsets the tighter call budget: resources
stay cached longer, so the PA spends fewer calls on re-discovery and more on
actual task execution. A short conversation window (4 messages) keeps the
prompt token footprint low.

### Long-session setup

Designed for extended, multi-turn conversations where context continuity is
the priority. The token-based window mode ensures older turns are summarized
by token budget rather than message count, which adapts gracefully to messages
of varying length. Tree-of-thought reasoning is used for complex analytical
queries.

```json
"pa": {
  "default_reasoning": "tot",
  "max_iterations": 15,
  "llm": {
    "model": "deepseek-r1:14b",
    "temperature": 0.0,
    "timeout": 120
  },
  "budget": {
    "tokens_max": 120000,
    "cost_max_usd": 2.0,
    "calls_max": 80,
    "timeout_ms": 300000.0
  },
  "conversation": {
    "max_messages": 30,
    "max_tokens": 8000,
    "window_mode": "both"
  },
  "cache": {
    "enabled": true,
    "max_size": 200
  }
}
```

`window_mode: "both"` means a turn is evicted when *either* the message count
hits 30 *or* the token count hits 8 000 — whichever comes first. This prevents
a single long assistant response from unexpectedly blowing out the context.

---

## Restart vs. immediate effect

| Setting | Restart required? |
|---|---|
| `pa.port` | Yes — PA process restart |
| `pa.default_reasoning` | Yes — PA process restart |
| `pa.llm.model` | Yes — PA process restart |
| `pa.llm.host` | Yes — PA process restart |
| `pa.intent_extractor.domain` | Yes — PA process restart |
| `ga.port` | Yes — GA process restart |
| `pa.max_iterations` | No — takes effect on next run |
| `pa.llm.temperature` | No — takes effect on next run |
| `pa.llm.timeout` | No — takes effect on next run |
| `pa.budget.*` | No — takes effect on next run |
| `pa.conversation.*` | No — takes effect on next turn |
| `pa.cache.enabled` | No — takes effect immediately |
| `pa.cache.max_size` | No — takes effect immediately |
| `pa.gateways` | No — takes effect on next resource resolution |
| `data_dir` | Yes — both PA and GA process restart |

---

## See also

- [CLI reference](cli.md) — full documentation for `axon pa config` and all
  flags mentioned on this page
- [Architecture overview](architecture.md) — how the Principal Agent and
  Gateway Agent relate to each other
- [The context layer](context-layer.md) — detailed explanation of the
  conversation window and summarization pipeline
- [Resource resolution](resolver.md) — how the Resolver uses the cache to
  discover and route to remote resources
- [Local tools](local-tools.md) — how to register tools that live in the PA's
  local pool rather than behind a Gateway Agent
- [Skills](skills.md) — how to create and activate domain skill files for
  `pa.intent_extractor.domain`
