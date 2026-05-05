"""
Currency Agent — agente A2A de teste para o Axon.

Expõe o agent card com a extensão Axon em metadata["axon"],
seguindo a especificação A2A que reserva metadata para extensões de terceiros.

Uso:
  python tests/agents/currency_agent/agent.py
  # necessário: axon token generate --name currency-agent
  # e substituir TOKEN_PLACEHOLDER pelo token gerado
"""
from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="Currency Agent")

# Substitua por um token gerado via: axon token generate --name currency-agent
_AXON_TOKEN = "REPLACE_WITH_TOKEN"

AGENT_CARD = {
    "name": "currency-agent",
    "description": (
        "Converts currency values between different denominations. "
        "Supports USD, EUR, BRL, GBP, JPY and other major currencies."
    ),
    "url": "http://localhost:8001",
    "version": "1.0.0",
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
        "stateTransitionHistory": False,
    },
    "skills": [
        {
            "id": "convert_currency",
            "name": "Convert Currency",
            "description": (
                "Converts an amount from one currency to another using live rates. "
                "Input: amount, source currency code, target currency code."
            ),
            "tags": ["currency", "finance", "conversion", "exchange-rate"],
            "examples": [
                "Convert 100 USD to BRL",
                "How much is 50 EUR in JPY?",
                "What is 1000 BRL in USD?",
            ],
            "inputModes": ["text/plain"],
            "outputModes": ["text/plain"],
        }
    ],
    # Extensão Axon em metadata — conforme especificação A2A para extensões
    # de terceiros. Clientes A2A que não conhecem o Axon ignoram este campo.
    "metadata": {
        "axon": {
            "token": _AXON_TOKEN,
            "registry_id": "local",
            "protocol_version": "0.1",
        }
    },
}


@app.get("/.well-known/agent.json")
async def agent_card() -> JSONResponse:
    return JSONResponse(AGENT_CARD)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "agent": "currency-agent"})


@app.post("/")
async def handle_task(body: dict) -> JSONResponse:
    """Endpoint de tarefas A2A (stub para testes)."""
    return JSONResponse({
        "jsonrpc": "2.0",
        "id": body.get("id"),
        "result": {
            "id": "task-stub",
            "status": {"state": "completed"},
            "artifacts": [{
                "parts": [{"kind": "text", "text": "Currency conversion: stub response"}]
            }],
        },
    })


if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=8001, log_level="warning")