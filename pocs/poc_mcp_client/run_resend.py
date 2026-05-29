"""
run_resend.py — demo standalone do MCP do Resend (stdio) — ENVIA UM EMAIL REAL.

Cenário: MCP_STDIO com segredo via ENV do processo filho. Agora 100% dirigido
pelo manifest:
  auth = api_key, location=env, env_var="RESEND_API_KEY"

O TokenResolver:
  - carrega o .env automaticamente (sem sobrescrever exports do shell)
  - lê RESEND_API_KEY e devolve um ResolvedAuth(location=env)
  - o MCPClient injeta esse segredo no env do processo `npx -y resend-mcp`

tool: send-email
  * to:      array   (obrigatório)
  * subject: string  (obrigatório)
  * text:    string  (obrigatório)
o remetente NÃO é param — vem de SENDER_EMAIL_ADDRESS (também lido do .env).

Uso (via .env na raiz do projeto OU export no shell):
    RESEND_API_KEY=re_...
    SENDER_EMAIL_ADDRESS=voce@dominio-verificado.com   # ou onboarding@resend.dev
    python pocs/poc_mcp_client/run_resend.py destinatario@exemplo.com
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from axon.types import (
    AuthConfig, AuthLocation, AuthScheme,
    ProtocolBinding, ResourceManifest, ResourceType,
)
from axon.token_resolver import resolve
from axon.pa.clients.mcp_client import MCPClient, MCPClientError

SEND_TOOL = "send-email"


def resend_manifest() -> ResourceManifest:
    return ResourceManifest(
        resource_id="resend-mcp",
        name="resend",
        type=ResourceType.mcp,
        protocol_binding=ProtocolBinding.MCP_STDIO,
        description="Resend — transactional email",
        capability_tags=["email", "send_email"],
        callable_by="pa_direct",
        command=["npx", "-y", "resend-mcp"],
        auth=AuthConfig(
            scheme=AuthScheme.api_key,
            location=AuthLocation.env,
            env_var="RESEND_API_KEY",
        ),
    )


async def main() -> int:
    manifest = resend_manifest()

    # ── 0. resolver o segredo via TokenResolver (carrega o .env) ───────
    print("\n── 0. resolver RESEND_API_KEY via TokenResolver ───────")
    resolved = resolve(manifest)
    if resolved is None:
        print("  ✗ RESEND_API_KEY não encontrada (.env ou export)")
        return 1
    print(f"  ✓ {resolved}")

    to = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("RESEND_TO")
    if not to:
        print("  ✗ informe o destinatário: python run_resend.py destinatario@exemplo.com")
        return 1

    sender = os.environ.get("SENDER_EMAIL_ADDRESS", "(definido no env do server)")
    print(f"\n  de:   {sender}")
    print(f"  para: {to}")

    # ── 1. conectar (MCPClient injeta o segredo no env do server) ──────
    print("\n── 1. conectar ao Resend MCP (stdio) ──────────────────")
    async with MCPClient(manifest, timeout=60.0) as client:
        tools = await client.list_tools()
        print(f"  ✓ conectado — {len(tools)} tools ({SEND_TOOL!r} presente: {SEND_TOOL in tools})")

        # ── 2. enviar email ────────────────────────────────────────────
        print("\n── 2. enviar email (send-email) ───────────────────────")
        try:
            result = await client.call_tool(SEND_TOOL, {
                "to":      [to],
                "subject": "Axon POC — Resend MCP via stdio",
                "text":    "Email enviado pelo MCPClient do Axon através do "
                           "Resend MCP server (stdio), com auth resolvida pelo "
                           "TokenResolver (location=env). Funciona!",
            })
        except MCPClientError as e:
            print(f"  ✗ falha no envio: {e}")
            return 1

    print(f"  ✓ enviado → {result}")
    print("\n✓ email enviado de verdade.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
