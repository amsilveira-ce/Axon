# Architecture

## What is Axon?

Axon is a multi-agent orchestration framework built on the **DAWN architecture** (Distributed Agents in a Worldwide Network). It lets you describe a goal in plain language and have it automatically broken down, planned, and executed across a network of specialized agents and tools — without you needing to know which agents exist or how to call them.

The framework has two moving parts: a **Principal Agent** that orchestrates everything, and one or more **Gateway Agents** that connect it to the wider world of distributed resources.

```
┌─────────────────────────────────────────────────────────────────┐
│                        User / Client                            │
└──────────────────────────────┬──────────────────────────────────┘
                               │  natural language query
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Principal Agent (PA)                        │
│                                                                 │
│   IntentExtractor → Decomposer → Planner → Resolver → Executor │
│                                                                 │
│   ┌─────────────────┐   ┌──────────────┐   ┌───────────────┐  │
│   │  Context Layer  │   │ Skills Layer │   │ Local Tools   │  │
│   └─────────────────┘   └──────────────┘   └───────────────┘  │
└────────────────────────────────┬────────────────────────────────┘
                                 │  A2A protocol
              ┌──────────────────┴──────────────────┐
              ▼                                      ▼
┌─────────────────────────┐          ┌──────────────────────────┐
│    Gateway Agent (GA)   │          │    Gateway Agent (GA)    │
│  ┌─────────────────┐    │          │  ┌──────────────────┐    │
│  │ Resource        │    │          │  │ Resource         │    │
│  │ Registry        │    │          │  │ Registry         │    │
│  └────────┬────────┘    │          │  └────────┬─────────┘    │
└───────────┼─────────────┘          └───────────┼──────────────┘
            │                                     │
     ┌──────┴──────┐                      ┌───────┴──────┐
     ▼             ▼                      ▼              ▼
  Agent A       MCP Tool              Agent B         Agent C
```

> **Note:** The Principal Agent is the **only** entry point exposed to the user. Gateway Agents, remote agents, and MCP servers are internal resources — not independent entry points. This keeps execution coherent and traceable.

---

## Key concepts

Before diving into each component, it helps to have these terms grounded:

| Term | What it means |
|------|---------------|
| **Principal Agent (PA)** | The single orchestrator that talks to the user, plans work, and drives execution |
| **Gateway Agent (GA)** | A registry-and-proxy that exposes a collection of remote resources to the PA |
| **Resource** | Anything the PA can invoke to do work — an A2A agent, an MCP tool, or a local tool |
| **Subtask** | One unit of work produced by decomposing the user's objective |
| **Plan (DAG)** | An ordered, dependency-aware graph of subtasks |
| **AgentState** | The PA's in-memory execution state for a single request, shared across pipeline stages |
| **Skill** | An editable Markdown file that shapes how the PA reasons, without touching code |

---

## Core components

### Principal Agent

The PA exists because multi-step goals cannot be solved in a single LLM call. It acts as the central coordinator: it understands what the user wants, figures out how to achieve it, finds the right tools, and drives execution to completion.

When a query arrives, the PA passes it through a five-stage pipeline:

| Stage | Input | Output | Why it exists |
|-------|-------|--------|---------------|
| `IntentExtractor` | raw query | `Objective` or `ClarificationNeeded` | Separates ambiguous requests from actionable goals before doing any work |
| `Decomposer` | `Objective` | `list[Subtask]` | Breaks a single goal into independently executable units |
| `Planner` | `list[Subtask]` | `Plan` (DAG) | Orders subtasks by dependency so they run in the right sequence |
| `Resolver` | `Plan` + GAs | `resource_pool` | Binds each subtask to a concrete resource before execution starts |
| `Executor` | `Plan` + `resource_pool` | result | Runs the plan, routing each subtask to its assigned resource |

The PA maintains all cross-stage state in an `AgentState` object, ensuring that what the Executor does is always traceable back to the original intent.

> **Tip:** Because `AgentState` is the single source of truth for a request, you can inspect it at any pipeline stage to understand exactly what the PA is doing and why.

### Gateway Agent

The GA exists to decouple the PA from the specifics of what resources are available. Rather than the PA knowing about every agent and tool in your network, it asks Gateway Agents — which maintain live registries — and works with whatever they return.

A GA's responsibilities are:

- **Register** resources at admission time, validating their capabilities and liveness
- **Search** its registry to find the best match for a given capability request
- **Monitor** registered resources over time and remove unhealthy ones

Because resources are registered at runtime, the set of capabilities available to the PA is never fixed. You can add, remove, or update resources without redeploying the PA.

> **Note:** Framework independence is a first-class design goal. The PA can coordinate any agent capable of speaking the A2A protocol, regardless of the framework it was built with.

---

## Execution flow

Here is what happens from the moment a query arrives to the moment a response is returned:

```
user query
    │
    ▼
IntentExtractor ──── query → Objective | ClarificationNeeded
    │
    ▼
Decomposer ────────── Objective → list[Subtask]
    │
    ▼
Planner ────────────── list[Subtask] → Plan (DAG)
    │
    ▼
Resolver ───────────── Plan + GatewayAgents → resource_pool
    │
    ▼
Executor ───────────── Plan + resource_pool → result
    │
    ▼
response
```

Each stage is isolated: it reads from `AgentState`, does its work, and writes its output back. This makes the pipeline easy to test, extend, and debug one stage at a time.

---

## Resource resolution

The Resolver's job is to bind each subtask to a concrete resource before execution begins, so the Executor never has to make discovery decisions mid-flight.

The Resolver works through a prioritized lookup chain:

1. **Local pool first** — checks `LocalResourcePool` for tools available on the machine, and for resources cached from previous runs
2. **Gateway Agents next** — queries connected GAs, ranking which one to ask first using a **UCB1 bandit** that learns the highest-yield gateway per capability over time
3. **Policy filter last** — filters every candidate against the operator's resource policy (allowed resource types, cost limits, required authentication)

The chosen resource — plus ranked fallbacks — is recorded per subtask in the `resource_pool` handed to the Executor.

> **Tip:** Use `axon pa gateway resources` to inspect what is currently available across your connected GAs, and `axon pa policy` to tune which resources the Resolver is allowed to select.

See [Resource resolution](resolver.md) for the full lookup algorithm and policy schema.

---

## Context layer

A language model holds no state between calls. The context layer exists to solve this: it maintains memory across turns and sessions, and assembles it into the prompt on every request.

The context layer manages two kinds of memory:

| Memory type | Class | Scope | Storage |
|-------------|-------|-------|---------|
| Conversation history | `ConversationHistory` | Current session only | `{data_dir}/pa/sessions/<session_id>` |
| Memory bank | `MemoryBank` | Persists across all sessions | `{data_dir}/pa/memory_bank.json` |

Conversation history uses a sliding window — older turns are summarized by the LLM rather than dropped — so the PA retains the thread of long conversations without exceeding the context budget.

The `PromptAssembler` combines both memory types with the list of available resources and the new query, trimming the result to a token budget when needed.

> **Note:** The memory bank is the right place to store durable facts that should influence every future session — user preferences, domain constraints, standing instructions. Conversation history is ephemeral by design.

See [The context layer](context-layer.md) for the full memory model and `PromptAssembler` configuration.

---

## Skills layer

Prompts that live inside code are hard to iterate on: changing behavior means a code change, review, and redeploy. The skills layer exists to move that behavior into version-controlled Markdown files that anyone can read and edit.

The `IntentExtractor` — the first stage of the pipeline — is driven entirely by skill files:

| File | Purpose | Editable? |
|------|---------|-----------|
| `intent_extraction.md` | Base skill — general reasoning rules and clarification logic | Yes |
| `domains/<name>.md` | Domain skill — field-specific rules layered on top of the base | Yes |
| *(output contract)* | Fixed JSON schema the parser reads back | No |

The domain skill is optional. When present, it is appended after the base skill and before the output contract, so domain rules always take precedence over general rules without conflicting with the parser.

> **Tip:** To customize the PA for a specific domain — clinical, legal, financial — create a domain skill file. You get specialized behavior without touching any application code.

See [Skills](skills.md) for the file format, layering rules, and domain skill examples.

---

## Local resources

Not every resource needs to travel through a Gateway Agent. The `LocalResourcePool` holds **local tools** — MCP tools the PA invokes directly on the local machine, bypassing GA discovery entirely.

Local tools are declared in `{data_dir}/pa/local_tools.json` and matched to subtasks by capability tag, the same way remote resources are. From the Resolver's perspective, a local tool and a remote resource are interchangeable candidates.

Typical uses for local tools:

- Always-available utilities: calculation, date handling, file reading
- Web search and retrieval
- Machine-local integrations that should not be exposed over the network

> **Note:** Local tools are checked first in the Resolver's lookup chain, so they take precedence over remote resources when a matching capability tag is found.

See [Local tools](local-tools.md) for the tool declaration format and capability tag reference.

---

## Protocol

Agents communicate with the PA over the **A2A protocol**. Each agent exposes an agent card at `/.well-known/agent.json` that describes its capabilities and skills. The GA reads this card at registration time to validate the agent and build its registry entry.

MCP tools are also first-class resources. The GA wraps them so they look identical to A2A agents from the Resolver's perspective.

> **Note:** Third-party MCP servers cannot embed an Axon token, so they are validated differently from A2A agents. At registration, the GA opens a **live connection** to prove the server is reachable. An optional operator-supplied admission token can be required for additional access control.

See [Third-party MCP resources](mcp-resources.md) for the registration flow and admission token design.

---

## Design decisions

Understanding why the architecture is shaped this way makes it easier to extend correctly.

**Single entry point.** Only the PA interacts with the user. This keeps execution coherent — every response is traceable through a single pipeline — and makes it straightforward to add cross-cutting concerns like logging, rate limiting, and policy enforcement in one place.

**Framework independence.** The PA coordinates over A2A, a wire protocol. Any agent that speaks A2A can participate, regardless of what framework it was built with. This prevents lock-in and lets teams use the best tool for each job.

**Dynamic discovery.** Resources are registered and discovered at runtime via Gateway Agents. The PA does not need to know in advance what capabilities exist. New agents and tools join the network without any PA configuration change.

**Separated execution state.** The PA owns global state via `AgentState`. Remote agents and MCP tools are stateless executors: they receive a subtask, do the work, and return a result. This containment makes failures easy to isolate and retry.

---

## See also

- [Resource resolution](resolver.md) — lookup algorithm, UCB1 bandit, and policy schema
- [The context layer](context-layer.md) — memory model, sliding window, and `PromptAssembler`
- [Skills](skills.md) — skill file format, layering rules, and domain skill examples
- [Local tools](local-tools.md) — tool declaration format and capability tag reference
- [Third-party MCP resources](mcp-resources.md) — MCP registration flow and admission token design
