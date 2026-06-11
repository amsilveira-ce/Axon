# Local Tools

Local tools give the Principal Agent (PA) capabilities it can call directly on your machine — no network discovery, no registration token, no external service required. They are the right choice for utilities that are always available, fast to invoke, and inherently local in nature.

> **Note:** This page covers concepts and how-tos for local tools. For the full command reference, see [`axon pa tools`](cli.md#axon-pa-tools).

## Overview

The Principal Agent draws its capabilities from two distinct sources:

- **Remote agents** — independently deployed services that the PA discovers at runtime through a [Gateway Agent](architecture.md).
- **Local tools** — [MCP](https://modelcontextprotocol.io) tools registered directly with the PA and executed on your own machine.

When the PA decides a task needs a local tool's capability, it runs the tool itself. There is no Gateway Agent involved, no discovery round trip, and no admission token required.

### Local tools vs. remote agents

| | Local tools | Remote agents |
|---|---|---|
| Registered with | the Principal Agent | a Gateway Agent |
| Discovered | from `local_tools.json` at startup | dynamically, at runtime |
| Needs a token | no | yes |
| Runs | on your machine | wherever the agent is hosted |
| Managed by | `axon pa tools` | `axon token` + `axon add` |

**When to use a local tool:** the capability is self-contained, always available, and has no reason to live in a separate service — for example, reading a file, evaluating an expression, or checking the current date.

**When to use a remote agent:** the work belongs to an independently deployed service with its own lifecycle, infrastructure, and team.

## Default tools

Running `axon init` registers four local tools automatically. They are all enabled and ready to use without any additional installation or configuration:

| Tool | Capability tag | What it does |
|---|---|---|
| `calculator` | `calculation` | Evaluates mathematical expressions safely |
| `web_search` | `web_search` | Searches the web via DuckDuckGo (no API key required) |
| `file_reader` | `file_reading` | Reads local files — PDF, TXT, CSV, Markdown |
| `datetime_tool` | `datetime` | Returns the current date and time; resolves natural-language date expressions |

All four are served by a single bundled MCP server (`python -m axon.pa.tools.server`) over the `stdio` transport. You do not need to start anything separately.

To confirm they are registered and enabled:

```bash
axon pa tools list
```

Expected output:

```
NAME            CAPABILITY      TRANSPORT   ENABLED
calculator      calculation     stdio       yes
web_search      web_search      stdio       yes
file_reader     file_reading    stdio       yes
datetime_tool   datetime        stdio       yes
```

## How tools are stored

Registered local tools live in `.axon/pa/local_tools.json` inside your workspace directory. Each entry follows this shape:

```json
{
  "name": "calculator",
  "capability": "calculation",
  "description": "Evaluates mathematical expressions safely",
  "transport": "stdio",
  "command": ["python", "-m", "axon.pa.tools.server"],
  "enabled": true
}
```

> **Note:** You rarely need to edit this file by hand. The `axon pa tools` commands keep it consistent. Only tools with `"enabled": true` are loaded when the PA starts.

Each field plays a specific role:

| Field | Meaning |
|---|---|
| `name` | Unique identifier used in CLI commands |
| `capability` | A tag the PA matches against the inferred needs of a task |
| `description` | Plain-language explanation of what the tool does — this is what the PA reads to decide whether a tool fits |
| `transport` | Communication protocol: `stdio` for local processes, `http` for HTTP endpoints |
| `command` | The command that launches the tool (stdio) or its endpoint URL (http) |
| `enabled` | Controls whether the PA may load and use the tool |

## How the PA selects a tool

The PA does not choose tools at random. During intent extraction, it infers which **capabilities** a request requires, then looks for registered tools whose `capability` tag matches.

The `description` field is what makes a tool discoverable. It is the only signal the PA uses when deciding whether a tool is appropriate for a given task.

> **Tip:** Write descriptions that are specific about domain and context. A description like *"Searches patient records in the HStory EHR system"* tells the PA exactly when to reach for the tool. A description like *"Searches records"* is ambiguous and may cause the wrong tool to be selected — or none at all.

This is why `axon pa tools add` requires a `--description` argument: a tool without a precise description is effectively invisible to the PA.

## Tutorials

### Register a new local tool (stdio)

Any MCP-compatible tool that runs as a local process can be registered with `axon pa tools add`. You need four pieces of information: a name, the command that starts the tool, a capability tag, and a description.

```bash
axon pa tools add \
  --name sales_report \
  --command "python -m mycompany.tools.sales" \
  --capability sales_data \
  --description "Fetches quarterly sales figures from the data warehouse and returns a structured report"
```

Before saving, Axon validates that the command is importable (for Python modules) or present on your `PATH` (for executables). If validation fails, the tool is not registered — so you find out immediately, not the first time the PA tries to use it.

Expected output on success:

```
Tool "sales_report" registered successfully.
```

### Register a tool over HTTP

Use `--transport http` when your tool is already running as an HTTP service and exposes an MCP-compatible endpoint.

```bash
# Register a CRM lookup tool served over HTTP
axon pa tools add \
  --name crm_lookup \
  --command "http://localhost:9000/mcp" \
  --capability crm \
  --description "Looks up customer records and account history in the internal CRM" \
  --transport http
```

For HTTP tools, Axon validates reachability of the endpoint before saving the registration.

> **Note:** The `--command` for HTTP tools is the endpoint URL, not a shell command. Axon will `GET` the URL during validation to confirm it responds.

### Choosing a transport

| Transport | Use when | `--command` value |
|---|---|---|
| `stdio` (default) | The tool runs as a local process — a Python module or an executable | The command that launches it, e.g. `python -m mymodule` |
| `http` | The tool is already running as an HTTP service | The MCP endpoint URL, e.g. `http://localhost:9000/mcp` |

### Disable a tool temporarily

You can turn a tool off without deleting its registration. This is useful when you want to restrict what the PA can do for a specific run — for example, keeping it offline:

```bash
axon pa tools disable web_search
```

The tool entry remains in `local_tools.json` with `"enabled": false`. The PA will not load or use it until you re-enable it.

### Re-enable a disabled tool

```bash
axon pa tools enable web_search
```

### Remove a tool permanently

```bash
axon pa tools remove web_search
```

This deletes the entry from `local_tools.json`. The action cannot be undone, but you can re-register the tool at any time using `axon pa tools add`.

## See also

- [`axon pa tools`](cli.md#axon-pa-tools) — full command reference for listing, adding, enabling, disabling, and removing tools
- [Architecture](architecture.md) — how local tools and remote agents fit into the broader PA design
- [Configuration](configuration.md#data-directory-structure) — where `local_tools.json` lives and how the data directory is structured
