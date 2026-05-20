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

The PA maintains conversation context across turns via `ConversationHistory`. Each session is identified by a `session_id` and persisted in `{data_dir}/pa/sessions/`. A sliding window keeps the last N turns in memory; older turns are summarized via LLM and stored in `summary`.

## Protocol

Agents communicate with the PA via the A2A protocol. Each agent exposes an agent card at `/.well-known/agent.json` describing its capabilities and skills. The GA uses this card to register and validate the agent.

MCP tools are also supported and wrapped as callable resources by the GA.

## Design decisions

**Single entry point**: only the PA interacts with the user. GA, remote agents, and MCP servers are internal resources, not independent entry points. This keeps execution coherent and traceable.

**Framework independence**: the PA can coordinate any agent capable of communicating via A2A, regardless of the framework it was built with.

**Dynamic discovery**: resources are discovered at runtime via Gateway Agents, not hardcoded at deploy time.

**Separated execution state**: global state is maintained by the PA via `AgentState`. External agents are stateless executors responsible only for their assigned subtask.