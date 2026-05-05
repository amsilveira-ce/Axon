"""
Summarizer Agent — agente A2A de teste para o Axon.

Duas skills: summarize_text e extract_key_points.
Extensão Axon declarada em metadata["axon"].

Uso:
  python tests/agents/summarizer_agent/agent.py
  # necessário: axon token generate --name summarizer-agent
"""
from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="Summarizer Agent")

_AXON_TOKEN = "REPLACE_WITH_TOKEN"

AGENT_CARD = {
    "name": "summarizer-agent",
    "description": (
        "Summarizes documents, articles and research papers into concise paragraphs. "
        "Also extracts key points as a structured list."
    ),
    "url": "http://localhost:8002",
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
            "id": "summarize_text",
            "name": "Summarize Text",
            "description": (
                "Takes a long text and returns a concise summary. "
                "Optionally accepts a target length in sentences."
            ),
            "tags": ["summarization", "nlp", "text", "research"],
            "examples": [
                "Summarize this research paper in 3 sentences",
                "Give me a TL;DR of the following article",
            ],
            "inputModes": ["text/plain"],
            "outputModes": ["text/plain"],
        },
        {
            "id": "extract_key_points",
            "name": "Extract Key Points",
            "description": "Extracts the main bullet points from a document.",
            "tags": ["extraction", "nlp", "text", "key-points"],
            "examples": ["What are the key points of this document?"],
            "inputModes": ["text/plain"],
            "outputModes": ["text/plain"],
        },
    ],
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
    return JSONResponse({"status": "ok", "agent": "summarizer-agent"})


@app.post("/")
async def handle_task(body: dict) -> JSONResponse:
    return JSONResponse({
        "jsonrpc": "2.0",
        "id": body.get("id"),
        "result": {
            "id": "task-stub",
            "status": {"state": "completed"},
            "artifacts": [{
                "parts": [{"kind": "text", "text": "Summarizer: stub response"}]
            }],
        },
    })


if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=8002, log_level="warning")