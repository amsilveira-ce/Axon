# Architecture

Axon is built on the DAWN architecture (Distributed Agents in a Worldwide Network), which defines two core components: the **Principal Agent** and the **Gateway Agent**.

## Components

### Principal Agent (PA)

The PA is the central orchestrator. It is the only component that interacts directly with the user. Its responsibilities are:

1. Extract the user's intent from a natural language query
2. Decompose the objective into subtasks
3. Build an execution plan (DAG)
4. Request resources from Gateway Agents
5. Execute the plan using the returned resources
6. Return a final response

The PA maintains the global execution state via `AgentState`, ensuring coherence between the initial intent and the final response.

### Gateway Agent (GA)

The GA connects distributed resources (agents and MCP tools) to the PA. Its responsibilities are:

- Maintain a registry of available resources
- Search and return the most suitable resources for a given task
- Validate resources at registration time and monitor them over time

Resources registered in the GA are discovered dynamically at runtime — the set of available capabilities is not fixed at deploy time.

## Execution flow

```
user query
    ↓
IntentExtractor        query → Objective | ClarificationNeeded
    ↓
Decomposer             Objective → list[Subtask]
    ↓
Planner                list[Subtask] → Plan (DAG)
    ↓
Resolver               Plan + GatewayAgents → resource_pool
    ↓
Executor               Plan + resource_pool → result
    ↓
response
```

## Context layer

A language model holds no state between calls, so the PA re-supplies what it
needs to know on every request. The **context layer** maintains two kinds of
memory and assembles them into the prompt:

- **Conversation history** (`ConversationHistory`) — the running dialogue of the
  current session, kept in a sliding window with older turns summarized by LLM.
  Persisted per `session_id` in `{data_dir}/pa/sessions/`.
- **Memory bank** (`MemoryBank`) — durable facts and preferences that hold
  across every session. Persisted in `{data_dir}/pa/memory_bank.json`.

A `PromptAssembler` combines both — plus available resources and the new query
— into the context window, trimming to a token budget when needed.

See [The context layer](context-layer.md) for a full explanation.

## Skills layer

The first pipeline stage, the `IntentExtractor`, is driven by editable Markdown **skill** files rather than hard-coded prompts:

- A **base skill** (`intent_extraction.md`) defines general behavior — how the PA reasons about a request and when it should ask for clarification.
- An optional **domain skill** (`domains/<name>.md`) is layered on top to add field-specific rules (clinical, finance, and so on).
- A fixed **output contract** is appended last. It defines the JSON structure the parser reads back and is not meant to be edited.

This keeps behavior changes in version-controlled text, separate from the extraction logic. See [Skills](skills.md).

## Local resources

Alongside resources discovered through Gateway Agents, the PA holds a `LocalResourcePool` of **local tools** — MCP tools it invokes directly, without GA discovery. They are declared in `{data_dir}/pa/local_tools.json` and matched to subtasks by capability tag, the same way remote resources are.

Local tools cover always-available, machine-local capabilities (calculation, file reading, web search, date handling); Gateway Agents cover independently deployed remote agents. See [Local tools](local-tools.md).

## Protocol

Agents communicate with the PA via the A2A protocol. Each agent exposes an agent card at `/.well-known/agent.json` describing its capabilities and skills. The GA uses this card to register and validate the agent.

MCP tools are also supported and wrapped as callable resources by the GA.

## Design decisions

**Single entry point**: only the PA interacts with the user. GA, remote agents, and MCP servers are internal resources, not independent entry points. This keeps execution coherent and traceable.

**Framework independence**: the PA can coordinate any agent capable of communicating via A2A, regardless of the framework it was built with.

**Dynamic discovery**: resources are discovered at runtime via Gateway Agents, not hardcoded at deploy time.

**Separated execution state**: global state is maintained by the PA via `AgentState`. External agents are stateless executors responsible only for their assigned subtask.