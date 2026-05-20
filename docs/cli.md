# CLI reference

## axon init

Initialize Axon in the current directory.

```bash
axon init [--defaults] [--data-dir <path>]
```

| flag | description |
|---|---|
| `--defaults`, `-d` | use all default values without prompting |
| `--data-dir <path>` | directory for runtime data (default: `.axon`) |

Creates `axon.config.json` and the full `.axon/` directory structure.

---

## axon token

Manage registration tokens for agents and MCP tools.

### axon token generate

```bash
axon token generate --name <name>
```

Generates a single-use token. The token must be added to the agent card before running `axon add agent`.

### axon token list

```bash
axon token list [--all]
```

Lists pending tokens. Use `--all` to include used and revoked tokens.

### axon token revoke

```bash
axon token revoke <token>
```

Revokes a token. Revoked tokens are rejected in future registrations.

---

## axon add

Register resources with the Gateway Agent.

### axon add agent

```bash
axon add agent <url> [--name <name>]
```

Registers an A2A agent. The agent must be running and expose an agent card with a valid Axon token.

| flag | description |
|---|---|
| `--name` | override the resource name (default: agent card name) |

---

## axon pa

Principal Agent commands.

### axon pa run

```bash
axon pa run --query "<query>"
```

Sends a one-shot query to the PA and prints the response.

### axon pa chat

```bash
axon pa chat
```

Starts an interactive session. Handles clarification rounds automatically — if the PA cannot extract a clear objective, it asks follow-up questions before proceeding.

---

## axon ga

Gateway Agent commands.

### axon ga serve

```bash
axon ga serve
```

Starts the Gateway Agent API server on the port configured in `axon.config.json` (default: `5000`).

### axon ga resource list

```bash
axon ga resource list
```

Lists all resources registered in the GA.

### axon ga resource ping

```bash
axon ga resource ping [--all] [<name>]
```

Verifies reachability and fingerprint of registered resources.