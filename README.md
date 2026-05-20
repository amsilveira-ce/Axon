# Axon

Axon is a distributed multi-agent orchestration framework. It connects agents built on different frameworks like AutoGen, LangChain, ADK, or custom, through a common protocol, enabling them to collaborate on complex tasks without requiring direct integration.

Axon is built on the [DAWN architecture](https://arxiv.org/abs/2410.22339) (Distributed Agents in a Worldwide Network).

## Install

```bash
pip install axon-framework
```

## Quick start

```bash
axon init
axon ga serve        # start the Gateway Agent
axon pa run --query "your query here"
```

## Documentation

- [Architecture](docs/architecture.md) — how Axon works
- [Getting started](docs/getting-started.md) — init, register an agent, run a query
- [Configuration](docs/configuration.md) — axon.config.json and environment variables
- [CLI reference](docs/cli.md) — all available commands
- [Deployment](docs/deployment.md) — containers and production setup

## License

MIT