"""
Mock MCP HTTP server — real MCP protocol via FastMCP (streamable HTTP).

Enforces Bearer auth on every /mcp request: if the TokenResolver did NOT
inject the credential, the handshake fails with 401 and the experiment
path fails. A successful tool call therefore proves the full chain:
manifest.auth → TokenResolver(env var) → MCPClient header injection.
"""
from __future__ import annotations

import threading

import uvicorn
from fastmcp import FastMCP

EXPECTED_TOKEN = "test_token_exp2"

mcp = FastMCP("mock-medical-mcp")


@mcp.tool
def check_interactions(drug_a: str, drug_b: str) -> str:
    """Check for known interactions between two drugs."""
    return (
        f"Interaction check: {drug_a} + {drug_b}. "
        "No significant pharmacokinetic interactions identified. "
        "Monitor for additive effects."
    )


@mcp.tool
def search_drugs(query: str) -> str:
    """Search drug database by name or condition."""
    return (
        f"Search results for '{query}': found 3 matching entries. "
        "Primary result: standard prescription medication, no special warnings."
    )


class _BearerAuthASGI:
    """ASGI wrapper: 401 on /mcp unless the expected Bearer token is present."""

    def __init__(self, app) -> None:
        self._app = app
        self.rejected = 0   # requests refused — visible to the experiment

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope["path"].startswith("/mcp"):
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            if headers.get("authorization") != f"Bearer {EXPECTED_TOKEN}":
                self.rejected += 1
                await send({
                    "type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                })
                await send({
                    "type": "http.response.body",
                    "body": b'{"detail": "missing or invalid bearer token"}',
                })
                return
        await self._app(scope, receive, send)


def start(port: int = 18082) -> tuple[uvicorn.Server, _BearerAuthASGI]:
    """Start the mock MCP HTTP server in a daemon thread."""
    app    = _BearerAuthASGI(mcp.http_app())
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    return server, app
