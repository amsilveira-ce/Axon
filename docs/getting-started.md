# Getting Started

This guide helps you get Axon running locally, register your first agent, and send a query through the full PA → GA → agent flow.

By the end, you will have:

- Installed the Axon CLI
- Initialized a local Axon workspace
- Registered an A2A-compatible agent
- Run a one-shot query and an interactive chat session

## How Axon fits together

Axon sits between your application and your agents:

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

- **Principal Agent (PA)**: receives user queries, extracts intent, builds a plan, and coordinates execution
- **Gateway Agent (GA)**: keeps a registry of available resources and returns the best match for each task

## Prerequisites

Before you begin, make sure you have:

- Python 3.11+
- [Ollama](https://ollama.com) running locally
- An A2A-compatible agent available over HTTP

Pull a model for the PA before starting:

```bash
ollama pull deepseek-r1:14b
# or
ollama pull llama3.2
```

## 1. Install Axon

Install the CLI from PyPI:

```bash
pip install axon-framework
```

## 2. Initialize a workspace

Run Axon once in your project directory:

```bash
axon init
```

For a non-interactive setup:

```bash
axon init --defaults
```

After initialization, you should see:

- `axon.config.json`: your local configuration
- `.axon/`: runtime data such as registry entries, sessions, and traces

## 3. Prepare an agent for registration

Axon uses the [A2A protocol](https://a2a-protocol.org) to communicate with agents. To register an agent, you need:

1. An agent card at `/.well-known/agent.json`
2. An Axon token embedded in that card

Example agent card:

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

Generate a token:

```bash
axon token generate --name my-agent
```

Add it to `capabilities.extensions` in the agent card:

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

## 4. Register the agent

Once the agent is reachable, register it with the GA:

```bash
axon add agent http://localhost:8000
```

Axon will fetch the agent card, validate the token, and store the resource in the registry.

Expected output:

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

To confirm what is currently registered:

```bash
axon ga resource list
```

## 5. Run your first query

You can send a one-shot query:

```bash
axon pa run --query "summarize the Q3 sales report"
```

The PA will extract intent, ask the GA for matching resources, and coordinate execution.

You can also start an interactive session:

```bash
axon pa chat
```

If a query is ambiguous, Axon asks clarifying questions before taking action:

```
  you: analyze the patient data

  ◇ extracting intent...
  │
  I understand that you want to analyze patient data.

  1. Which patient should be analyzed?
  2. What type of analysis is needed?
     • clinical summary  /  lab results  /  full report

  you: John Silva, full report
  ...
  ◆ identified goal
     goal    generate a full clinical report for patient John Silva
```

## Next steps

- [Architecture](architecture.md): understand how the PA and GA work internally
- [Configuration](configuration.md): tune the model, ports, and context window
- [Deployment](deployment.md): run Axon in a container or production environment
- [CLI reference](cli.md): explore the full command surface
