"""
test_http_tavily.py — POC PA-01: MCP_HTTP real — Tavily

Valida:
  ✓ ResourceManifest(protocol_binding=MCP_HTTP, endpoint="https://mcp.tavily.com/...")
  ✓ MCPClient conecta via StreamableHttpTransport
  ✓ list_tools() e tavily-search executam corretamente
  ✓ Key inválida levanta MCPTransportError

Pré-requisito: export TAVILY_API_KEY="tvly-..."
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from axon.types import AuthConfig, AuthScheme, ProtocolBinding, ResourceManifest, ResourceType
from mcp_client import MCPClient, MCPToolNotFoundError, MCPTransportError


def _require_tavily_key() -> str:
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        pytest.skip("TAVILY_API_KEY não setada — export TAVILY_API_KEY=tvly-...")
    return key


@pytest.fixture
def tavily_manifest() -> ResourceManifest:
    """
    Tavily usa a API key na query string da URL — convenção própria do servidor.
    AuthScheme.none porque a auth vai embutida no endpoint, não no header.
    """
    key      = os.environ.get("TAVILY_API_KEY", "")
    endpoint = f"https://mcp.tavily.com/mcp/?tavilyApiKey={key}" if key else "https://mcp.tavily.com/mcp/"

    return ResourceManifest(
        resource_id="tavily-mcp",
        name="tavily",
        type=ResourceType.mcp,
        protocol_binding=ProtocolBinding.MCP_HTTP,
        description="Tavily — real-time web search, extract, map and crawl",
        capability_tags=["web_search", "web_extract", "web_crawl"],
        callable_by="pa_direct",
        endpoint=endpoint,
        auth=AuthConfig(scheme=AuthScheme.none),
    )


@pytest.mark.asyncio
async def test_tavily_connect_and_list_tools(tavily_manifest):
    _require_tavily_key()

    async with MCPClient(tavily_manifest, timeout=30.0) as client:
        tools = await client.list_tools()

    print(f"\n  tools Tavily: {tools}")
    assert len(tools) > 0
    assert any("search" in t.lower() or "tavily" in t.lower() for t in tools)


@pytest.mark.asyncio
async def test_tavily_search(tavily_manifest):
    _require_tavily_key()

    async with MCPClient(tavily_manifest, timeout=30.0) as client:
        tools = await client.list_tools()
        search_tool = next((t for t in tools if "search" in t.lower()), None)
        if search_tool is None:
            pytest.skip(f"Tool de search não encontrada em: {tools}")

        result = await client.call_tool(search_tool, {
            "query": "Model Context Protocol MCP specification 2025",
        })

    print(f"\n  {search_tool}() = {str(result)[:300]}...")
    assert result is not None


@pytest.mark.asyncio
async def test_tavily_invalid_key_raises_transport_error():
    bad = ResourceManifest(
        resource_id="tavily-bad",
        name="tavily_bad",
        type=ResourceType.mcp,
        protocol_binding=ProtocolBinding.MCP_HTTP,
        callable_by="pa_direct",
        endpoint="https://mcp.tavily.com/mcp/?tavilyApiKey=tvly-INVALID-000",
        auth=AuthConfig(scheme=AuthScheme.none),
    )

    with pytest.raises(MCPTransportError):
        async with MCPClient(bad, timeout=10.0) as client:
            await client.list_tools()


@pytest.mark.asyncio
async def test_tavily_tool_not_found(tavily_manifest):
    _require_tavily_key()

    async with MCPClient(tavily_manifest, timeout=30.0) as client:
        with pytest.raises(MCPToolNotFoundError) as exc_info:
            await client.call_tool("enviar_email", {})

    assert "enviar_email" in str(exc_info.value)


def test_manifest_transport_separation():
    """
    Todos os servidores usam o mesmo MCPClient — o ProtocolBinding abstrai o transport.
    """
    manifests = [
        ResourceManifest(
            resource_id="local", name="axon_pa_tools",
            type=ResourceType.mcp, protocol_binding=ProtocolBinding.MCP_STDIO,
            callable_by="pa_direct",
            command=[sys.executable, "-m", "axon.pa.tools.server"],
            auth=AuthConfig(scheme=AuthScheme.bearer),
        ),
        ResourceManifest(
            resource_id="resend", name="resend",
            type=ResourceType.mcp, protocol_binding=ProtocolBinding.MCP_STDIO,
            callable_by="pa_direct",
            command=["npx", "-y", "resend-mcp"],
            auth=AuthConfig(scheme=AuthScheme.none),
        ),
        ResourceManifest(
            resource_id="tavily", name="tavily",
            type=ResourceType.mcp, protocol_binding=ProtocolBinding.MCP_HTTP,
            callable_by="pa_direct",
            endpoint="https://mcp.tavily.com/mcp/?tavilyApiKey=tvly-xxx",
            auth=AuthConfig(scheme=AuthScheme.none),
        ),
        ResourceManifest(
            resource_id="sse-local", name="test_sse_server",
            type=ResourceType.mcp, protocol_binding=ProtocolBinding.MCP_SSE,
            callable_by="pa_direct",
            endpoint="http://127.0.0.1:18766/sse",
            auth=AuthConfig(scheme=AuthScheme.bearer),
        ),
    ]

    print("\n")
    print("  name                 protocol_binding   auth scheme")
    print("  " + "─" * 55)
    for m in manifests:
        print(f"  {m.name:<20} {m.protocol_binding.value:<18} {m.auth.scheme.value}")

    assert all(isinstance(m, ResourceManifest) for m in manifests)