# Axon

**Interoperability infrastructure for AI agents.**

Axon lets agents built on different frameworks — AutoGen, LangChain, Google ADK, CrewAI, or your own code — discover each other and collaborate on complex tasks through a single shared protocol, with no direct integration between them.

![Python](https://img.shields.io/badge/python-3.12+-blue) ![License](https://img.shields.io/badge/license-MIT-green) ![Protocol](https://img.shields.io/badge/protocol-A2A-8957e5)

> Built based on the [DAWN architecture](https://arxiv.org/abs/2410.22339) — *Distributed Agents in a Worldwide Network*.

---

## The problem

Multi-agent systems today are locked inside the framework they were built with. A LangChain agent and an AutoGen agent can't collaborate unless you hand-write an adapter between them — and the number of adapters you maintain grows with every pair of agents you add.

Axon removes the point-to-point glue. Every agent speaks one protocol; Axon handles discovery, planning, and orchestration. **Register an agent once, and any workflow can use it.**

## How it works

Axon sits between your application and your agents as an orchestration layer.

```
                       user query
                           │
                           ▼
                  ┌──────────────────┐
                  │  Principal Agent │   intent · planning · context
                  └────────┬─────────┘
                           │  requests resources
                           ▼
                  ┌──────────────────┐
                  │  Gateway Agent   │   registry · discovery · validation
                  └────────┬─────────┘
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ LangChain│ │  AutoGen │ │   MCP    │
        │  agent   │ │  agent   │ │  tools   │
        └──────────┘ └──────────┘ └──────────┘
            speak A2A    speak A2A   wrapped by the GA
```

Two core components, from the DAWN architecture:

- **Principal Agent (PA)** — the single entry point. It takes a natural-language query, extracts the user's intent, decomposes the objective into subtasks, builds an execution plan (a DAG), and coordinates execution. It owns the global state and keeps conversation context across turns.
- **Gateway Agent (GA)** — the resource directory. It keeps a registry of available agents and MCP tools, validates them at registration, and returns the best match for each subtask. Resources are discovered at runtime — nothing is hardcoded at deploy time.

Agents connect through the [A2A protocol](https://a2a-protocol.org): each one exposes an agent card at `/.well-known/agent.json` describing its skills, and the GA uses that card to register, validate, and match it.

### Execution flow

```
user query
   │
   ▼  IntentExtractor   query        → Objective | ClarificationNeeded
   ▼  Decomposer        Objective    → list[Subtask]
   ▼  Planner           list[Subtask]→ Plan (DAG)
   ▼  Resolver          Plan + GAs   → resource pool
   ▼  Executor          Plan + pool  → result
   ▼
response
```

## Why Axon

- **Framework-independent** — coordinate any agent that speaks A2A, regardless of how it was built. No SDK lock-in.
- **Dynamic discovery** — agents and tools register with a Gateway Agent and are matched to tasks by capability at runtime, not wired in at deploy time.
- **Coherent orchestration** — one Principal Agent owns intent, planning, and global state; external agents stay stateless executors, so every run is traceable end to end.
- **Context across turns** — conversation history is persisted per session with a sliding window; older turns are summarized so long sessions stay cheap.
- **Local and remote resources** — mix remote A2A agents discovered through the GA with local MCP tools called directly by the PA.
- **Local-first** — the orchestrator runs on [Ollama](https://ollama.com) by default, so your queries and planning stay on your machine.

## Install

```bash
pip install axon-framework
```

Requires Python 3.12+ and a running [Ollama](https://ollama.com) instance for the Principal Agent.

## Quick start

```bash
# 1. initialize a workspace (creates axon.config.json and .axon/)
axon init

# 2. start the Gateway Agent
axon ga serve

# 3. register an A2A-compatible agent
axon add agent http://localhost:8000

# 4. send a query through the full PA → GA → agent flow
axon pa run --query "summarize the Q3 sales report"

# or start an interactive session
axon pa chat
```

See [Getting started](docs/getting-started.md) for the full walkthrough, including how to prepare and register your first agent.

## Documentation

- [Getting started](docs/getting-started.md) — install, register an agent, run a query
- [Architecture](docs/architecture.md) — how the PA and GA work internally
- [Configuration](docs/configuration.md) — `axon.config.json` and environment variables
- [Skills](docs/skills.md) — steer how the Principal Agent understands requests
- [Local tools](docs/local-tools.md) — give the Principal Agent tools it can call directly
- [CLI reference](docs/cli.md) — every available command

## License

[MIT](LICENSE)
