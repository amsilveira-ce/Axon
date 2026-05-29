"""
run_notion.py — demo standalone do MCP do Notion (OAuth de usuário).

Cenário: OAuth. Agora também expresso 100% no manifest (scheme=oauth) e
dirigido pelo MESMO MCPClient que o Tavily — o MCPClient detecta scheme=oauth
e delega ao helper OAuth do fastmcp (Dynamic Client Registration + navegador
+ callback local + token storage).

Endpoints (https://developers.notion.com/guides/mcp/get-started-with-mcp):
  https://mcp.notion.com/mcp   → Streamable HTTP (recomendado)
  https://mcp.notion.com/sse   → SSE (legado)

Uso:
    python pocs/poc_mcp_client/run_notion.py
    (na primeira execução o navegador abre para login/consentimento no Notion)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from axon.types import (
    AuthConfig, AuthScheme,
    ProtocolBinding, ResourceManifest, ResourceType,
)
from axon.pa.clients.mcp_client import MCPClient

NOTION_MCP_URL = "https://mcp.notion.com/mcp"


def notion_manifest() -> ResourceManifest:
    return ResourceManifest(
        resource_id="notion-mcp",
        name="notion",
        type=ResourceType.mcp,
        protocol_binding=ProtocolBinding.MCP_HTTP,
        description="Notion — pages, databases, search",
        capability_tags=["notes", "search", "docs"],
        callable_by="pa_direct",
        endpoint=NOTION_MCP_URL,
        auth=AuthConfig(scheme=AuthScheme.oauth),
    )


async def main() -> int:
    manifest = notion_manifest()

    print("\n── conectar ao Notion MCP (scheme=oauth) ──────────────")
    print("  ⓘ na primeira execução o navegador abre para login/consentimento")

    async with MCPClient(manifest, timeout=120.0) as client:
        tools = await client.list_tools()
        print(f"\n  ✓ conectado — {len(tools)} tools:")
        for t in tools:
            print(f"      - {t}")

    print("\n✓ Notion MCP acessível via OAuth, dirigido pelo manifest.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
