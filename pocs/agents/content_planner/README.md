# Content Planner Agent

Agente A2A que recebe uma descrição de alto nível e retorna um outline detalhado para um conteúdo. Utiliza o Google ADK com LiteLLM (Ollama/Gemma) e expõe uma interface JSON-RPC.

## Requisitos

- Python 3.13+
- [Ollama](https://ollama.com/) rodando localmente com o modelo `gemma3:12b`

```bash
ollama pull gemma3:12b
```

## Instalação

```bash
pip install -r requirements.txt
```

Ou com `uv`:

```bash
uv sync
```

## Subindo o agente

```bash
uv run python __main__.py
```

O servidor sobe em `http://localhost:4115`.

Para confirmar que está no ar:

```bash
curl http://localhost:4115/.well-known/agent-card.json | python3 -m json.tool
```

## Testando com input

### curl

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

### Script Python

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

## Estrutura

```
content_planner_agent/
├── __main__.py              # Ponto de entrada — sobe o servidor A2A
├── agent_executor.py        # Integração entre ADK e o protocolo A2A
├── content_planner_agent.py # Definição do agente (modelo, instrução, ferramentas)
├── requirements.txt
└── pyproject.toml
```
