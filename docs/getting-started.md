# Getting Started

Let's get Axon running on your machine, register your first agent, and send a query through the full PA → GA → agent pipeline — from install to a working interactive session.

By the end of this tutorial, you will have:

- Installed the Axon CLI
- Initialized a local Axon workspace
- Registered an A2A-compatible agent
- Run a one-shot query and an interactive chat session

## How Axon fits together

Before diving in, it helps to understand what Axon actually does. Axon sits between your application and your agents as a coordination layer:

```
your app / CLI
      ↓
Principal Agent   ← orchestrates, maintains context
      ↓
Gateway Agent     ← finds the right agent for the task
      ↓
your agents       ← do the actual work
```

The two core components are:

- **Principal Agent (PA)**: receives user queries, extracts intent, builds a plan, and coordinates execution across one or more agents
- **Gateway Agent (GA)**: keeps a registry of available resources and returns the best match for each task using semantic search

We'll bring both of these online in the steps below.

## Prerequisites

Make sure your environment meets the following requirements before starting:

- **Python** 3.11 or higher
- **[Ollama](https://ollama.com)** installed and running locally
- An **A2A-compatible agent** reachable over HTTP

Axon uses a local LLM (via Ollama) to power the Principal Agent. Pull a model before you begin — `deepseek-r1:14b` gives the best reasoning quality, but `llama3.2` is a lighter alternative:

```bash
ollama pull deepseek-r1:14b
# or, for a lighter footprint:
ollama pull llama3.2
```

> **Note:** The model you pull here is what the PA will use for intent extraction and planning. You can change it later with `axon pa config --llm <model>` without re-registering anything.

## Step 1: Install Axon

Install the CLI directly from PyPI:

```bash
pip install axon-framework
```

We recommend installing inside a virtual environment to keep dependencies isolated.

## Step 2: Initialize a workspace

Axon needs a workspace to store configuration, registry entries, and session data. Run `axon init` once inside your project directory:

```bash
axon init
```

If you want to skip the interactive prompts and accept sensible defaults, pass `--defaults`:

```bash
axon init --defaults
```

After initialization, two things appear in your project:

- `axon.config.json` — your local configuration (model, budget, domain skill, etc.)
- `.axon/` — runtime data: registry entries, session history, and traces

> **Tip:** `axon init` also registers four ready-to-use **local tools** — `calculator`, `web_search`, `file_reader`, and `datetime_tool` — that the PA can call without routing through any agent. To see them, run `axon pa tools list`. See [Local tools](local-tools.md) for details on adding your own.

## Step 3: Prepare an agent for registration

Axon uses the [A2A protocol](https://a2a-protocol.org) to communicate with agents. The protocol requires each agent to expose an **agent card** — a JSON file at `/.well-known/agent.json` that describes what the agent can do. The GA reads this card to understand the agent's capabilities and uses the skill descriptions for semantic matching.

Here's what a minimal agent card looks like:

```json
{
  "name": "my-agent",
  "description": "Does something useful",
  "version": "1.0.0",
  "url": "http://localhost:8000",
  "skills": [
    {
      "id": "my-skill",
      "name": "My skill",
      "description": "What this agent can do - the GA uses this for semantic search",
      "tags": ["tag1", "tag2"]
    }
  ],
  "capabilities": {
    "extensions": []
  }
}
```

> **Note:** The `description` field inside each skill is what the GA runs semantic search against when routing a query. Write it to describe the task clearly — not just the technology.

To register an agent, Axon also requires a signed token embedded in the card. Generate one now:

```bash
axon token generate --name my-agent
```

Then add it to `capabilities.extensions` in your agent card:

```json
"capabilities": {
  "extensions": [{
    "uri": "https://axon-framework.dev/extensions/registry/v1",
    "params": {
      "token": "axon_tk_...",
      "registry_id": "local",
      "protocol_version": "0.1"
    }
  }]
}
```

> **Warning:** Keep this token private. Axon uses it to verify the agent's identity at registration time — anyone who holds the token can register an agent as if it were yours.

## Step 4: Register the agent

With the agent running and its card in place, register it with the Gateway Agent:

```bash
axon add agent http://localhost:8000
```

Axon fetches the agent card from `http://localhost:8000/.well-known/agent.json`, validates the embedded token, and stores the resource in the registry. You should see output like this:

```
◇ agent card       my-agent v1.0.0
│
◇ axon token       registry=local · v0.1 · verified
│
◆ my-agent registered

  │  id          res-a1b2c3
  │  type        agent (A2A)
  │  endpoint    http://localhost:8000
  │  status      online
```

To confirm the registration took effect, list all registered resources:

```bash
axon ga resource list
```

## Step 5: Run your first query

We're ready to send a query through the full pipeline. The simplest way is a one-shot run:

```bash
axon pa run --query "summarize the Q3 sales report"
```

Behind the scenes, the PA extracts the intent from your query, asks the GA for the best-matching resource, dispatches the task to your agent, and returns the result.

We can also open an interactive session where the PA maintains context across turns:

```bash
axon pa chat
```

When a query is ambiguous, Axon asks clarifying questions before taking any action — rather than making assumptions that could lead to incorrect results:

```
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

## Step 6: Tune the Principal Agent

The PA works out of the box, but you can shape its behavior without touching any code. Let's look at the most useful knobs.

Inspect all current settings first:

```bash
axon pa config
```

Switch the model or set a per-run token budget:

```bash
axon pa config --llm llama3.2 --budget-tokens 30000
```

You can also teach the PA the vocabulary and rules specific to your domain with a **domain skill**. This steers how the PA interprets requests — useful when your users speak in domain-specific terms the base model may not handle well:

```bash
axon pa skills new --domain finance   # scaffolds the skill file
# edit src/axon/pa/skills/domains/finance.md
axon pa config --domain finance       # activate it
```

See [Skills](skills.md) for a full explanation of how skills influence intent extraction.

## Next steps

Now that you have a working end-to-end setup, here are the best places to go deeper:

- [Architecture](architecture.md) — understand how the PA and GA work internally
- [Configuration](configuration.md) — tune the model, budget, and context window
- [The context layer](context-layer.md) — how the PA remembers things across turns
- [Skills](skills.md) — steer how the PA understands requests
- [Local tools](local-tools.md) — give the PA tools it can call directly
- [CLI reference](cli.md) — explore the full command surface
