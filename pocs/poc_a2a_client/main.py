"""
main.py

Ponto de entrada da POC — demonstra os cenários de comunicação A2A
entre o PA executor e o content_planner_stub.

O ResourceManifest é montado manualmente aqui simulando o que o GA
entregaria ao PA após descoberta e filtragem de política.

Uso:
    # Terminal 1 — agente remoto
    python content_planner_stub/server.py

    # Terminal 2 — POC
    python main.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

BASE_DIR = os.path.dirname(__file__)
SRC_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "..", "src"))

sys.path.insert(0, BASE_DIR)
sys.path.insert(0, SRC_DIR)

from axon.types import (
    A2ACapabilities,
    AuthConfig,
    AuthScheme,
    ProtocolBinding,
    ResourceManifest,
    ResourceType,
)
from pa_a2a_client_simulation.executor import execute, execute_with_push
from pa_a2a_client_simulation.server import WebhookServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
)
logger = logging.getLogger("poc")

PROMPT = "Create an outline for a blog post about Python async programming"


def make_manifest(
    streaming: bool = False,
    push: bool = False,
    token: str | None = None,
) -> ResourceManifest:
    """
    Monta manualmente o ResourceManifest que o GA entregaria ao PA.

    Para manter a POC simples, quando um token é informado nós o espelhamos
    em CONTENT_PLANNER_TOKEN e apontamos o manifesto para essa env var.
    """

    auth = AuthConfig()
    if token:
        os.environ["CONTENT_PLANNER_TOKEN"] = token
        auth = AuthConfig(
            scheme=AuthScheme.bearer,
            header="Authorization",
            env_var="CONTENT_PLANNER_TOKEN",
        )

    return ResourceManifest(
        resource_id="content-planner-agent",
        name="Content Planner Agent",
        type=ResourceType.agent,
        protocol_binding=ProtocolBinding.JSONRPC,
        description="Creates structured outlines for content pieces.",
        capability_tags=["content_planning", "outline_generation", "blog_writing"],
        callable_by="pa_direct",
        endpoint="http://localhost:4115",
        a2a_capabilities=A2ACapabilities(
            streaming=streaming,
            pushNotifications=push,
        ),
        auth=auth,
    )


async def main():
    token = os.getenv("CONTENT_PLANNER_TOKEN", "poc-secret-token")

    print("\n" + "═" * 60)
    print("POC A2A — PA Executor ↔ Content Planner Stub")
    print("═" * 60)

    # ── Cenário 1: HTTP síncrono 
    print("\n▶ Cenário 1 — HTTP síncrono direto")
    print("─" * 40)
    try:
        manifest = make_manifest(streaming=False, token=token)
        result = await execute(manifest, PROMPT)
        print(result)
    except Exception as e:
        print(f"✗ {type(e).__name__}: {e}")

    # ── Cenário 2: Streaming SSE ──────────────────────────────
    print("\n▶ Cenário 2 — Streaming SSE")
    print("─" * 40)
    try:
        manifest = make_manifest(streaming=True, token=token)
        result = await execute(manifest, PROMPT)
        print(result)
    except Exception as e:
        print(f"✗ {type(e).__name__}: {e}")

    # ── Cenário 3: Bearer inválido ────────────────────────────
    print("\n▶ Cenário 3 — Bearer token inválido (esperado: erro 401)")
    print("─" * 40)
    try:
        manifest = make_manifest(token="wrong-token")
        await execute(manifest, PROMPT)
        print("✗ Deveria ter falhado")
    except Exception as e:
        print(f"✓ Falhou como esperado: {type(e).__name__}")

    # ── Cenário 5: Push notification ──────────────────────────
    print("\n▶ Cenário 5 — Push notification")
    print("─" * 40)
    async with WebhookServer() as webhook:
        try:
            manifest = make_manifest(push=True, token=token)
            result = await execute_with_push(manifest, PROMPT)
            print(result)
        except TimeoutError as e:
            print(f"⚠ Timeout: {e}")
        except Exception as e:
            print(f"✗ {type(e).__name__}: {e}")

    print("\n" + "═" * 60)
    print("POC concluída.")


if __name__ == "__main__":
    asyncio.run(main())
