"""Persistent stdio MCP session for the Principal Agent's local tool pool.

``LocalMCPSession`` manages a single long-lived connection to the local MCP
server (``axon.local_pool.server``) for the lifetime of the PA process.

**Why a background thread?**
The ``fastmcp`` ``Client`` is async.  The Executor — and the ``run()`` entry
point exposed to the CLI and API — is synchronous.  The solution, without
breaking the interface, is to run a dedicated event loop on a daemon thread
and dispatch coroutines to it via ``asyncio.run_coroutine_threadsafe``.

Typical usage::

    with LocalMCPSession(manifests) as session:
        schemas = session.tool_schemas()
        result  = session.call_tool_sync("calculate", {"expression": "2**10"})
    # client closed, subprocess exited, background thread stopped
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
from typing import TYPE_CHECKING, Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

if TYPE_CHECKING:
    from axon.types import ResourceManifest

logger = logging.getLogger(__name__)


def _inherit_pythonpath() -> str:
    """Return a PYTHONPATH that includes both the env var and ``sys.path``."""
    current = os.environ.get("PYTHONPATH", "")
    from_sys = ":".join(p for p in sys.path if p)
    return ":".join(filter(None, [current, from_sys]))


class LocalMCPSessionError(Exception):
    """Raised when the session fails to start or a tool call fails."""


class LocalMCPSession:
    """Persistent stdio MCP connection to the PA's local tool server.

    All local tool manifests point to the same server process.  The session
    spawns exactly one subprocess and routes every tool call through the
    shared ``fastmcp`` ``Client``, avoiding per-call process overhead.

    Attributes:
        owns: Check whether a manifest is served by this session.
        tool_schemas: Cached ``{tool_name: inputSchema}`` dict from startup.

    Use as a context manager::

        with LocalMCPSession(manifests) as session:
            result = session.call_tool_sync("calculate", {"expression": "2**10"})
    """

    def __init__(
        self,
        manifests: list["ResourceManifest"],
        timeout: float = 30.0,
    ) -> None:
        if not manifests:
            raise LocalMCPSessionError("LocalMCPSession requires at least one manifest.")

        cmd = manifests[0].command
        if not cmd:
            raise LocalMCPSessionError(
                f"Manifest '{manifests[0].name}' has no command — "
                "LocalMCPSession requires MCP_STDIO manifests with a command defined."
            )

        self._cmd = cmd
        self._owned = {m.resource_id for m in manifests}
        self._timeout = timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: Client | None = None
        self._schemas: dict[str, dict] = {}

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def __enter__(self) -> "LocalMCPSession":
        self._loop = asyncio.new_event_loop()
        
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="LocalMCPSession"
        )
        self._thread.start()

        future = asyncio.run_coroutine_threadsafe(self._start(), self._loop)
        try:
            future.result(timeout=self._timeout)
        except Exception as exc:
            self._shutdown_loop()
            raise LocalMCPSessionError(
                f"Failed to connect to local MCP server ({self._cmd}): {exc}"
            ) from exc

        logger.info(
            "[LocalMCPSession] connected — %d tool(s): %s",
            len(self._schemas), ", ".join(sorted(self._schemas)),
        )
        return self

    def __exit__(self, *args: Any) -> None:
        if self._client is not None and self._loop is not None:
            future = asyncio.run_coroutine_threadsafe(
                self._client.__aexit__(None, None, None), self._loop
            )
            try:
                future.result(timeout=10)
            except Exception as exc:
                logger.warning("[LocalMCPSession] error closing client: %s", exc)
            self._client = None

        self._shutdown_loop()
        logger.info("[LocalMCPSession] disconnected")

    # ── public API ────────────────────────────────────────────────────────────

    def owns(self, manifest: "ResourceManifest") -> bool:
        """Return ``True`` if *manifest* is served by this session.

        The Executor calls this before deciding whether to use the shared
        client or fall back to spawning a new subprocess via ``MCPClient``.
        """
        return manifest.resource_id in self._owned

    def tool_schemas(self) -> dict[str, dict]:
        """Return ``{tool_name: inputSchema}`` — populated once at startup."""
        return dict(self._schemas)

    def call_tool_sync(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on the shared server synchronously.

        Dispatches the coroutine to the session's background event loop via
        ``run_coroutine_threadsafe`` — no new subprocess is spawned.

        Raises:
            LocalMCPSessionError: When the session is not connected or the
                tool returns ``is_error=True``.
        """
        if self._client is None or self._loop is None:
            raise LocalMCPSessionError(
                "LocalMCPSession is not connected — use 'with LocalMCPSession(...) as s:'"
            )
        logger.debug("[LocalMCPSession] call → %s(%s)", tool_name, arguments)
        future = asyncio.run_coroutine_threadsafe(
            self._async_call_tool(tool_name, arguments), self._loop
        )
        result = future.result(timeout=self._timeout)
        logger.debug(
            "[LocalMCPSession] %s → result_type=%s", tool_name, type(result).__name__
        )
        return result

    # ── async internals (run on the background loop) ──────────────────────────

    async def _start(self) -> None:
        """Start the subprocess, connect the client, and cache tool schemas."""
        resolved_cmd = (
            [sys.executable, *self._cmd[1:]]
            if self._cmd[0] in ("python", "python3")
            else list(self._cmd)
        )
        env = {**os.environ, "PYTHONPATH": _inherit_pythonpath()}

        logger.debug("[LocalMCPSession] spawning → %s", " ".join(resolved_cmd))
        transport = StdioTransport(
            command=resolved_cmd[0],
            args=resolved_cmd[1:],
            env=env,
        )
        self._client = Client(transport, timeout=self._timeout)
        await self._client.__aenter__()

        tools = await self._client.list_tools()
        self._schemas = {
            t.name: (getattr(t, "inputSchema", None) or {}) for t in tools
        }

    async def _async_call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Async tool call dispatched from ``call_tool_sync``."""
        result = await self._client.call_tool(tool_name, arguments)  # type: ignore[union-attr]
        if result.is_error:
            raise LocalMCPSessionError(
                f"Tool '{tool_name}' returned is_error=True: {_extract_content(result)}"
            )
        return _extract_content(result)

    # ── private helpers ───────────────────────────────────────────────────────

    def _shutdown_loop(self) -> None:
        if self._loop is None:
            return

        # fastmcp keeps a _session_runner task alive until the loop stops.
        # asyncio logs this as ERROR ("Task was destroyed but it is pending!")
        # when the loop is stopped before the task exits naturally.
        # This is expected on intentional shutdown — silence it for the duration.
        asyncio_logger = logging.getLogger("asyncio")
        prev_level = asyncio_logger.level
        asyncio_logger.setLevel(logging.CRITICAL)
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread is not None:
                self._thread.join(timeout=5)
        finally:
            asyncio_logger.setLevel(prev_level)

        self._loop = None
        self._thread = None


def _extract_content(result: Any) -> Any:
    """Extract the usable value from a fastmcp tool result."""
    if hasattr(result, "data") and result.data is not None:
        return result.data
    if hasattr(result, "content") and result.content:
        first = result.content[0]
        if hasattr(first, "text"):
            return first.text
    return None
