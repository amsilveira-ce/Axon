"""
pa/clients/a2a_webhook.py — WebhookServer do PA

Recebe push notifications de agentes A2A remotos.
Sobe como processo background junto com o PA.

Uso:
    async with WebhookServer() as webhook:
        client = A2AClient(pa_webhook_url=webhook.url)
        result = await client.call_with_push(manifest, task="...")
"""

from __future__ import annotations

import asyncio
import logging
import os

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/webhook/task-complete"

# dict compartilhado com A2AClient.call_with_push — chaveado por task_id
push_results: dict[str, dict] = {}


async def _webhook_handler(request: Request) -> JSONResponse:
    data    = await request.json()
    task_id = data.get("id")

    if not task_id:
        logger.warning("[webhook] payload without task_id — ignored")
        return JSONResponse({"status": "ignored"}, status_code=400)

    push_results[task_id] = data
    logger.info("[webhook] push received → task_id=%s", task_id)
    return JSONResponse({"status": "ok"})


class WebhookServer:
    """
    Servidor webhook do PA para push notifications A2A.

    Roda em background via asyncio — não bloqueia o PA.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int | None = None,
    ) -> None:
        self.host    = host
        self.port    = port or int(os.getenv("PA_PORT", "8001"))
        self._server: uvicorn.Server | None = None
        self._task:   asyncio.Task | None   = None

        self._app = Starlette(routes=[
            Route(WEBHOOK_PATH, _webhook_handler, methods=["POST"]),
        ])

    @property
    def url(self) -> str:
        return f"http://localhost:{self.port}{WEBHOOK_PATH}"

    async def start(self) -> None:
        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)
        self._task   = asyncio.create_task(self._server.serve())

        while not self._server.started:
            await asyncio.sleep(0.05)

        logger.info("[webhook] ready → %s", self.url)

    async def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._task:
            await self._task
        logger.info("[webhook] stopped")

    async def __aenter__(self) -> "WebhookServer":
        await self.start()
        return self

    async def __aexit__(self, *_) -> None:
        await self.stop()