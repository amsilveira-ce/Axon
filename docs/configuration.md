# Configuration

Axon is configured through a single file, `axon.config.json`, created in your
project directory by [`axon init`](cli.md#axon-init). Every field has a
sensible default, so a fresh workspace works without any editing.

You can change settings in two ways:

- **`axon pa config`** — the recommended way. It validates your input, saves
  the file for you, and tells you when a restart is needed. See the
  [CLI reference](cli.md#axon-pa-config).
- **Editing `axon.config.json` directly** — fine for quick changes, but you
  are responsible for keeping the JSON valid.

This page explains every field.

## axon.config.json

A freshly initialized file looks like this:

```json
{
  "version": "0.1.0",
  "data_dir": ".axon",
  "pa": {
    "port": 4100,
    "default_reasoning": "rewoo",
    "max_iterations": 10,
    "gateways": [],
    "llm": {
      "host": "http://localhost:11434",
      "model": "deepseek-r1:14b",
      "temperature": 0.0,
      "timeout": 60
    },
    "budget": {
      "tokens_max": 60000,
      "cost_max_usd": 0.5,
      "calls_max": 40,
      "timeout_ms": 120000.0
    },
    "conversation": {
      "max_messages": 10,
      "max_tokens": null,
      "window_mode": "messages"
    },
    "cache": {
      "enabled": true,
      "max_size": 50
    },
    "intent_extractor": {
      "domain": null,
      "intents": {}
    }
  },
  "ga": {
    "port": 5000
  }
}
```

## Top-level fields

### `version`

The configuration schema version. Managed by Axon — do not change it by hand.

### `data_dir`

Directory where Axon stores all runtime data (registry, tokens, sessions,
conversation history, local tools, traces). Defaults to `.axon`, relative to
the current directory. Can be overridden by the `AXON_DATA_DIR` environment
variable — see [Environment variables](#environment-variables).

## Principal Agent (`pa`)

Everything under `pa` configures the [Principal Agent](architecture.md).
The matching `axon pa config` flag is listed for each field.

### `pa.port`

Port for the PA control API. Default: `4100`.
Flag: *(not editable via `axon pa config`)*.

### `pa.default_reasoning`

The reasoning strategy the PA uses to plan and execute work. Options:

- `rewoo` — plan the whole sequence first, then execute (default)
- `react` — reason and act step by step
- `tot` — explore several reasoning branches (tree of thought)

Flag: `--reasoning-mode`. Changing this requires a restart.

### `pa.max_iterations`

The maximum number of planning/execution cycles the PA will run for a single
request. A safety limit that prevents runaway loops. Default: `10`.
Flag: `--max-iterations`.

### `pa.gateways`

A list of Gateway Agent URLs the PA can request resources from. Empty by
default — the PA still works with its [local tools](local-tools.md), it just
has no remote agents to delegate to.
Flags: `--gateway-add`, `--gateway-remove`.

### `pa.llm`

The language model that powers the PA. Axon uses [Ollama](https://ollama.com)
by default, so the model runs locally on your machine.

| Field | Default | Description |
|---|---|---|
| `host` | `http://localhost:11434` | URL of the Ollama server |
| `model` | `deepseek-r1:14b` | Model used for intent extraction and reasoning |
| `temperature` | `0.0` | Sampling temperature, `0.0`–`1.0`. Lower is more deterministic |
| `timeout` | `60` | Timeout in seconds for a single LLM call |

Flags: `--llm` (model), `--temperature`. Reasoning models such as
`deepseek-r1:14b` handle complex queries better than general models.
Make sure the model is pulled in Ollama (`ollama pull <model>`) before using
it. Changing the model requires a restart.

### `pa.budget`

Hard limits applied to a single run. When any limit is reached, the run stops
— this keeps an unexpected loop from draining tokens, money, or time.

| Field | Default | Description |
|---|---|---|
| `tokens_max` | `60000` | Maximum tokens consumed per run |
| `cost_max_usd` | `0.5` | Maximum cost in USD per run |
| `calls_max` | `40` | Maximum number of LLM calls per run |
| `timeout_ms` | `120000.0` | Maximum execution time per run, in milliseconds |

Flags: `--budget-tokens`, `--budget-cost`, `--budget-calls`, `--budget-timeout`.

### `pa.conversation`

Controls the PA's working memory — how much past conversation it keeps in the
active context window. Older turns that fall outside the window are summarized
rather than dropped, so long sessions stay coherent without growing unbounded.
See [The context layer](context-layer.md) for how this memory works.

| Field | Default | Description |
|---|---|---|
| `max_messages` | `10` | Maximum messages kept in the active window |
| `max_tokens` | `null` | Maximum tokens kept in the active window (`null` = no token limit) |
| `window_mode` | `messages` | How the window is measured: `messages`, `tokens`, or `both` |

Flags: `--conversation-max-messages`, `--conversation-max-tokens`,
`--conversation-window-mode`.

### `pa.cache`

The cross-session resource cache. When enabled, resources discovered through a
Gateway Agent are remembered between runs, so the PA does not re-discover the
same agents every time. See [Resource resolution](resolver.md) for how the
Resolver fills and reads it.

| Field | Default | Description |
|---|---|---|
| `enabled` | `true` | Whether the resource cache is active |
| `max_size` | `50` | Maximum number of cached **resources** (LRU) |

Flags: `--cache`, `--cache-max-size`.

**What `max_size` counts.** One slot per **resource**, regardless of type — an
A2A agent is one, an MCP server is one, and the two share the same budget. It is
per *resource*, not per *tool*: an MCP server counts as one even if it exposes
several tools (those are skills inside the resource). Only resources discovered
through a Gateway Agent are counted — local tools live in the
[local pool](local-tools.md) and never take a slot.

**Eviction is LRU.** Recency is the order in which resources are discovered or
refreshed (`put`). When the cache exceeds `max_size`, the least-recently-discovered
resource is dropped. A resource that keeps being rediscovered stays; stale ones
are evicted. Set `max_size` to `0` for no limit.

### `pa.intent_extractor`

Settings for the intent extraction stage — the step that turns a
natural-language request into a structured objective.

| Field | Default | Description |
|---|---|---|
| `domain` | `null` | The active domain skill (e.g. `clinical`). `null` = base skill only |
| `intents` | `{}` | Reserved for pre-declared intent definitions |

Flag: `--domain`. A domain must exist as a skill file before it can be
activated — see [Skills](skills.md). Changing the domain requires a restart.

## Gateway Agent (`ga`)

### `ga.port`

Port for the Gateway Agent API. Default: `5000`.

## Environment variables

### `AXON_DATA_DIR`

Overrides `data_dir` from `axon.config.json`. It takes priority over the config
file and accepts absolute or relative paths. This is the standard way to point
Axon at a writable location in a container or production environment.

```bash
# container / production
AXON_DATA_DIR=/var/lib/axon axon pa run --query "..."

# or in docker-compose
environment:
  - AXON_DATA_DIR=/data/axon
```

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
