"""
pa/mcp_client.py — MCPClient: interface do PA para execução de tools MCP.

Consome ResourceManifest e delega ao fastmcp o transporte correto.
Auth é resolvida pelo TokenResolver antes de construir o transport.

ProtocolBinding → transport fastmcp:
    MCP_STDIO → StdioTransport          — spawna processo local
    MCP_HTTP  → StreamableHttpTransport — Streamable HTTP (spec 2024+)
    MCP_SSE   → SSETransport            — Server-Sent Events (legado)

Auth (via ResolvedAuth do TokenResolver):
    header → header HTTP
    query  → ?param=token na URL
    env    → injetado no env do processo stdio
    oauth  → delegado ao fastmcp.OAuth (httpx.Auth)
"""

from __future__ import annotations
import sys
import os
import logging
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import SSETransport, StdioTransport, StreamableHttpTransport

from axon.types import AuthScheme, ProtocolBinding, ResourceManifest
from axon.token_resolver import ResolvedAuth, TokenResolverError, resolve

logger = logging.getLogger(__name__)


def _inherit_pythonpath() -> str:
    current  = os.environ.get("PYTHONPATH", "")
    from_sys = ":".join(p for p in sys.path if p)
    return ":".join(filter(None, [current, from_sys]))
# ---------------------------------------------------------------------------
#   Erros
# ---------------------------------------------------------------------------

class MCPClientError(Exception):
    """Base para todos os erros do MCPClient."""


class MCPTransportError(MCPClientError):
    """Falha ao conectar ou spawnar o processo MCP."""


class MCPToolNotFoundError(MCPClientError):
    """Tool solicitada não existe no servidor MCP."""


class MCPToolExecutionError(MCPClientError):
    """Tool executou mas retornou is_error=True."""


# ---------------------------------------------------------------------------
#   MCPClient
# ---------------------------------------------------------------------------

class MCPClient:
    """
    Interface do PA para execução de tools MCP.

    Uso:
        async with MCPClient(manifest) as client:
            tools  = await client.list_tools()
            result = await client.call_tool("search", {"query": "..."})

        # one-shot
        result = await MCPClient.call_once(manifest, "search", {"query": "..."})
    """

    def __init__(self, manifest: ResourceManifest, timeout: float = 30.0) -> None:
        self._manifest = manifest
        self._timeout  = timeout
        self._client: Client | None = None

    # ------------------------------------------------------------------
    #   Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "MCPClient":
        logger.debug(
            "[MCPClient] connecting → name=%s binding=%s timeout=%.1fs",
            self._manifest.name, self._manifest.protocol_binding, self._timeout,
        )
        auth      = resolve(self._manifest)
        transport = self._build_transport(auth)
        self._client = Client(transport, timeout=self._timeout)
        try:
            await self._client.__aenter__()
        except Exception as exc:
            logger.error(
                "[MCPClient] connection FAILED → name=%s binding=%s: %s",
                self._manifest.name, self._manifest.protocol_binding, exc,
            )
            raise MCPTransportError(
                f"Failed to connect to '{self._manifest.name}' "
                f"({self._manifest.protocol_binding}): {exc}"
            ) from exc
        logger.debug("[MCPClient] connected → name=%s", self._manifest.name)
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client is not None:
            await self._client.__aexit__(*args)
            self._client = None
            logger.debug("[MCPClient] disconnected → name=%s", self._manifest.name)

    # ------------------------------------------------------------------
    #   API pública
    # ------------------------------------------------------------------

    async def list_tools(self) -> list[str]:
        """Retorna lista de nomes de tools disponíveis no servidor."""
        self._assert_connected()
        tools = await self._client.list_tools()  # type: ignore[union-attr]
        names = [t.name for t in tools]
        logger.debug(
            "[MCPClient] list_tools → name=%s tools=%s", self._manifest.name, names,
        )
        return names

    async def list_tool_schemas(self) -> dict[str, dict]:
        """Retorna {nome_da_tool: inputSchema} — usado pelo Parameterizer."""
        self._assert_connected()
        tools = await self._client.list_tools()  # type: ignore[union-attr]
        return {t.name: (getattr(t, "inputSchema", None) or {}) for t in tools}

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """
        Chama uma tool MCP e retorna o resultado deserializado.

        Raises:
            MCPToolNotFoundError:   tool não existe no servidor
            MCPToolExecutionError:  tool retornou is_error=True
            MCPTransportError:      falha de comunicação
        """
        self._assert_connected()

        logger.debug(
            "[MCPClient] call_tool → name=%s tool=%s args=%s",
            self._manifest.name, tool_name, arguments,
        )

        available = await self.list_tools()
        if tool_name not in available:
            logger.error(
                "[MCPClient] tool not found → name=%s tool=%s available=%s",
                self._manifest.name, tool_name, available,
            )
            raise MCPToolNotFoundError(
                f"Tool '{tool_name}' not found in '{self._manifest.name}'. "
                f"Available: {available}"
            )

        try:
            result = await self._client.call_tool(tool_name, arguments)  # type: ignore[union-attr]
        except Exception as exc:
            logger.error(
                "[MCPClient] transport error → name=%s tool=%s: %s",
                self._manifest.name, tool_name, exc,
            )
            raise MCPTransportError(
                f"Transport error calling '{tool_name}': {exc}"
            ) from exc

        if result.is_error:
            logger.warning(
                "[MCPClient] tool returned error → name=%s tool=%s",
                self._manifest.name, tool_name,
            )
            raise MCPToolExecutionError(
                f"Tool '{tool_name}' returned an error: {_extract_content(result)}"
            )

        content = _extract_content(result)
        logger.debug(
            "[MCPClient] call_tool OK → name=%s tool=%s result_type=%s",
            self._manifest.name, tool_name, type(content).__name__,
        )
        return content

    # ------------------------------------------------------------------
    #   One-shot helper
    # ------------------------------------------------------------------

    @classmethod
    async def call_once(
        cls,
        manifest:  ResourceManifest,
        tool_name: str,
        arguments: dict[str, Any],
        timeout:   float = 30.0,
    ) -> Any:
        """Conecta, chama a tool e desconecta em uma operação."""
        async with cls(manifest, timeout=timeout) as client:
            return await client.call_tool(tool_name, arguments)

    # ------------------------------------------------------------------
    #   Internals
    # ------------------------------------------------------------------

    def _build_transport(
        self, auth: ResolvedAuth | None
    ) -> StdioTransport | StreamableHttpTransport | SSETransport:
        """Constrói o transport a partir de manifest.protocol_binding."""
        pb = self._manifest.protocol_binding

        if pb == ProtocolBinding.MCP_STDIO:
            command = self._manifest.command
            if not command:
                raise MCPTransportError(
                    f"'{self._manifest.name}' tem protocol_binding=MCP_STDIO "
                    f"mas nenhum command definido."
                )

            # replace generic "python"/"python3" with the exact interpreter
            # running the PA — critical with uv or when venv isn't activated
            resolved_cmd = (
                [sys.executable, *command[1:]]
                if command[0] in ("python", "python3")
                else list(command)
            )

            env = {**os.environ, "PYTHONPATH": _inherit_pythonpath()}
            if auth:
                env.update(auth.as_env())
            logger.debug(
                "[MCPClient] spawning stdio subprocess → name=%s cmd=%s",
                self._manifest.name, " ".join(resolved_cmd),
            )
            return StdioTransport(
                command=resolved_cmd[0],
                args=resolved_cmd[1:],
                env=env,
            )
        elif pb == ProtocolBinding.MCP_HTTP:
            endpoint = self._manifest.endpoint
            if not endpoint:
                raise MCPTransportError(
                    f"'{self._manifest.name}' tem protocol_binding=MCP_HTTP "
                    f"mas nenhum endpoint definido."
                )
            url, headers, auth_obj = self._http_auth(endpoint, auth)
            logger.debug(
                "[MCPClient] http transport → name=%s url=%s", self._manifest.name, url,
            )
            return StreamableHttpTransport(url=url, headers=headers, auth=auth_obj)

        elif pb == ProtocolBinding.MCP_SSE:
            endpoint = self._manifest.endpoint
            if not endpoint:
                raise MCPTransportError(
                    f"'{self._manifest.name}' tem protocol_binding=MCP_SSE "
                    f"mas nenhum endpoint definido."
                )
            url, headers, auth_obj = self._http_auth(endpoint, auth)
            logger.debug(
                "[MCPClient] sse transport → name=%s url=%s", self._manifest.name, url,
            )
            return SSETransport(url=url, headers=headers, auth=auth_obj)

        else:
            raise MCPTransportError(
                f"ProtocolBinding '{pb}' não é suportado pelo MCPClient. "
                f"Suportados: MCP_STDIO, MCP_HTTP, MCP_SSE."
            )

    def _http_auth(
        self, endpoint: str, auth: ResolvedAuth | None
    ) -> tuple[str, dict[str, str] | None, Any]:
        """
        Resolve (url, headers, auth_obj) para transports HTTP/SSE a partir do scheme.

        oauth          → delega ao fastmcp.OAuth (httpx.Auth); url/headers intactos
        api_key/query  → credencial embutida na URL (?param=token)
        bearer/header  → credencial em header
        """
        ac = self._manifest.auth

        if ac.scheme == AuthScheme.oauth:
            from fastmcp.client.auth import OAuth
            oauth = OAuth(
                endpoint,
                scopes=ac.scopes or None,
                client_id=os.environ.get(ac.client_id_env) if ac.client_id_env else None,
                client_secret=os.environ.get(ac.client_secret_env) if ac.client_secret_env else None,
            )
            return endpoint, None, oauth

        if auth is not None:
            return auth.apply_to_url(endpoint), (auth.as_headers() or None), None

        return endpoint, None, None

    def _assert_connected(self) -> None:
        if self._client is None:
            raise MCPClientError(
                "MCPClient não está conectado. "
                "Use 'async with MCPClient(manifest) as client:'"
            )


# ---------------------------------------------------------------------------
#   Helpers
# ---------------------------------------------------------------------------

def _extract_content(result: Any) -> Any:
    """
    Extrai o valor útil de um CallToolResult.
    Prefere .data (fastmcp 2.x+); fallback para texto do primeiro content block.
    """
    if hasattr(result, "data") and result.data is not None:
        return result.data
    if hasattr(result, "content") and result.content:
        first = result.content[0]
        if hasattr(first, "text"):
            return first.text
    return None
