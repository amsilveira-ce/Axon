# Content Planner Agent

An A2A agent that takes a high-level description and returns a detailed outline for a piece of content. 
Built with Google ADK + LiteLLM (Ollama/Gemma) and exposed over a JSON-RPC interface.

---

## 1. Requirements

- Python 3.13+
- [Ollama](https://ollama.com/) running locally with the `gemma3:12b` model

Pull the model once:

```bash
ollama pull gemma3:12b
```

Make sure Ollama is running before you start the agent:

```bash
ollama serve
```

---

## 2. Create a virtual environment

Always work inside a virtual environment so the agent's dependencies stay isolated from your system Python.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Windows (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### Windows (cmd)

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

When the venv is active, your prompt will be prefixed with `(.venv)`. To leave the environment later, just run:

```bash
deactivate
```

> Using `uv`? You can skip this step — `uv sync` creates and manages the `.venv` for you.

---

## 3. Install dependencies

With the virtual environment activated:

```bash
pip install -r requirements.txt
```

Or, with `uv` (creates the `.venv` automatically):

```bash
uv sync
```

---

## 4. Start the agent

```bash
uv run python __main__.py
```

Or, if you're using plain `pip` / `venv`:

```bash
python __main__.py
```

The server will start at `http://localhost:4115`.

To confirm it's up and running:

```bash
curl http://localhost:4115/.well-known/agent-card.json | python3 -m json.tool
```

---

## 5. Send a request

### Option A — curl

```bash
curl -X POST http://localhost:4115 \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [{ "text": "Create an outline for a blog post about Python async programming" }],
        "messageId": "msg-001",
        "contextId": "ctx-001"
      }
    }
  }'
```

### Option B — Python client

```python
import asyncio
from a2a.client import A2AClient
from a2a.types import Message, Part, Role

async def main():
    async with A2AClient(url="http://localhost:4115") as client:
        message = Message(
            role=Role.user,
            parts=[Part(text="Create an outline for a blog post about Python async programming")],
            messageId="msg-001",
            contextId="ctx-001",
        )
        response = await client.send_message(message)
        print(response)

asyncio.run(main())
```

---

## Project structure

```
content_planner/
├── __main__.py              # Entry point — boots the A2A server
├── agent_executor.py        # Bridges Google ADK with the A2A protocol
├── content_planner_agent.py # Agent definition (model, instructions, tools)
├── client.py                # Example A2A client
├── test_agent.py            # Tests
├── requirements.txt
└── pyproject.toml
```
