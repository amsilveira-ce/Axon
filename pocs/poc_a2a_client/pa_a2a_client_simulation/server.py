"""
pa_agent/server.py

Webhook server do PA — recebe push notifications de agentes remotos.

Sobe junto com o PA e roda em paralelo via asyncio.
O endpoint /webhook/task-complete é registrado no ResourceManifest
quando push_notifications=True, e o agente remoto faz POST aqui
quando a task conclui.

Uso:
    server = WebhookServer()
    await server.start()

    # ... PA executa tasks ...

    await server.stop()

    # ou como context manager:
    async with WebhookServer() as server:
        result = await execute(manifest, prompt)
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

logger = logging.getLogger("pa_webhook")

PA_PORT = int(os.getenv("PA_PORT", "8001"))
WEBHOOK_PATH = "/webhook/task-complete"

# Resultados recebidos via push — chaveados por task_id
# Compartilhado com executor.py via import
push_results: dict[str, dict] = {}


# ──────────────────────────────────────────────────────────────
# Handler
# ──────────────────────────────────────────────────────────────

async def webhook_handler(request: Request) -> JSONResponse:
    data = await request.json()
    task_id = data.get("id")

    if not task_id:
        logger.warning("[webhook] payload sem task_id — ignorado")
        return JSONResponse({"status": "ignored"}, status_code=400)

    push_results[task_id] = data
    logger.info(f"[webhook] push recebido → task_id={task_id}")
    return JSONResponse({"status": "ok"})


# ──────────────────────────────────────────────────────────────
# WebhookServer
# ──────────────────────────────────────────────────────────────

class WebhookServer:
    """
    Wrapper em torno do uvicorn que permite subir e parar
    o servidor webhook de forma programática.

    Roda em background via asyncio — não bloqueia o PA.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = PA_PORT) -> None:
        self.host = host
        self.port = port
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task | None = None

        self._app = Starlette(routes=[
            Route(WEBHOOK_PATH, webhook_handler, methods=["POST"]),
        ])

    async def start(self) -> None:
        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="warning",  # silencia uvicorn — usamos nosso logger
        )
        self._server = uvicorn.Server(config)
        self._task = asyncio.create_task(self._server.serve())

        # aguarda o servidor estar pronto antes de retornar
        while not self._server.started:
            await asyncio.sleep(0.05)

        logger.info(f"[webhook] servidor pronto → http://{self.host}:{self.port}{WEBHOOK_PATH}")

    async def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._task:
            await self._task
        logger.info("[webhook] servidor encerrado")

    async def __aenter__(self) -> "WebhookServer":
        await self.start()
        return self

    async def __aexit__(self, *_) -> None:
        await self.stop()