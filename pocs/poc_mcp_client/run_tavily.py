"""
run_tavily.py — demo standalone (sem pytest) do MCPClient contra o Tavily MCP.

Cenário: api_key em QUERY STRING. Agora isso é expresso 100% no manifest
(scheme=api_key, location=query, param="tavilyApiKey") — o MCPClient + TokenResolver
leem a env var e montam a URL sozinhos. Nenhuma gambiarra de URL no script.

  1. monta o ResourceManifest declarando api_key/query via env var
  2. MCPClient conecta (TokenResolver embute a key na query string)
  3. lista tools + roda uma busca real
  4. mostra o comportamento com key inválida

Uso:
    export TAVILY_API_KEY="tvly-..."
    python pocs/poc_mcp_client/run_tavily.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from axon.types import (
    AuthConfig, AuthLocation, AuthScheme,
    ProtocolBinding, ResourceManifest, ResourceType,
)
from axon.pa.token_resolver import resolve
from mcp_client import MCPClient, MCPClientError


def tavily_manifest(env_var: str = "TAVILY_API_KEY") -> ResourceManifest:
    return ResourceManifest(
        resource_id="tavily-mcp",
        name="tavily",
        type=ResourceType.mcp,
        protocol_binding=ProtocolBinding.MCP_HTTP,
        description="Tavily — real-time web search",
        capability_tags=["web_search"],
        callable_by="pa_direct",
        endpoint="https://mcp.tavily.com/mcp/",
        auth=AuthConfig(
            scheme=AuthScheme.api_key,
            location=AuthLocation.query,
            param="tavilyApiKey",
            env_var=env_var,
        ),
    )


async def main() -> int:
    manifest = tavily_manifest()

    # ── 0. checar resolução da key (só p/ visibilidade — o MCPClient já faz isso) ──
    print("\n── 0. resolver key via TokenResolver ──────────────────")
    resolved = resolve(manifest)
    if resolved is None:
        print("  ✗ TAVILY_API_KEY não configurada — export TAVILY_API_KEY=tvly-...")
        return 1
    print(f"  ✓ {resolved}")

    # ── 1. conectar + listar tools ─────────────────────────────────────
    print("\n── 1. conectar + listar tools ─────────────────────────")
    async with MCPClient(manifest, timeout=30.0) as client:
        tools = await client.list_tools()
        print(f"  ✓ conectado — {len(tools)} tools: {tools}")

        search_tool = next((t for t in tools if "search" in t.lower()), None)
        if search_tool is None:
            print(f"  ✗ nenhuma tool de search em {tools}")
            return 1

        # ── 2. rodar search ────────────────────────────────────────────
        print("\n── 2. rodar search ────────────────────────────────────")
        result = await client.call_tool(
            search_tool,
            {"query": "Model Context Protocol MCP specification 2025"},
        )
        print(f"  ✓ {search_tool}() →\n  {str(result)[:400]}...")

    # ── 3. comportamento com key inválida ──────────────────────────────
    print("\n── 3. comportamento com key inválida ──────────────────")
    import os
    os.environ["TAVILY_BAD_KEY"] = "tvly-INVALID-000"
    bad = tavily_manifest(env_var="TAVILY_BAD_KEY")
    try:
        async with MCPClient(bad, timeout=10.0) as client:
            res = await client.call_tool("tavily_search", {"query": "ping"})
        print(f"  ⚠ Tavily respondeu (key inválida) → {str(res)[:200]}")
    except MCPClientError as e:
        print(f"  ✓ key inválida rejeitada: {str(e)[:160]}")

    print("\n✓ tudo funcionando.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
