"""
The three ResourceManifests of the experiment.

The manifest is the ONLY input each client consumes — built here by hand,
without fetching an Agent Card and without querying the GA. If the clients
work from these objects alone, the manifest is a sufficient execution
contract.
"""
from __future__ import annotations

from axon.types import (
    AuthConfig,
    AuthLocation,
    AuthScheme,
    ProtocolBinding,
    ResourceManifest,
    ResourcePolicy,
    ResourceType,
)

A2A_PORT = 18081
MCP_PORT = 18082
GA_PORT  = 18083

MCP_ENV_VAR    = "AXON_SECRET_MOCK_MEDICAL_MCP"
STDIO_RES_ID   = "res-exp2pa-stdio"


def a2a_manifest() -> ResourceManifest:
    """Path 1: A2A agent via pa_direct (JSON-RPC binding, no auth)."""
    return ResourceManifest(
        resource_id="mock-code-review-001",
        name="mock-code-review",
        type=ResourceType.agent,
        protocol_binding=ProtocolBinding.JSONRPC,
        description="Mock code review agent",
        capability_tags=["code", "review", "bugs"],
        callable_by="pa_direct",
        endpoint=f"http://127.0.0.1:{A2A_PORT}/",
        match_score=0.95,
        auth=AuthConfig(scheme=AuthScheme.none),
        policy=ResourcePolicy(is_paid=False, requires_auth=False),
    )


def mcp_http_manifest() -> ResourceManifest:
    """Path 2: MCP HTTP via pa_direct — bearer auth resolved by TokenResolver."""
    return ResourceManifest(
        resource_id="mock-medical-mcp-001",
        name="mock-medical-mcp",
        type=ResourceType.mcp,
        protocol_binding=ProtocolBinding.MCP_HTTP,
        description="Mock medical MCP tool",
        capability_tags=["drugs", "interactions", "medical"],
        callable_by="pa_direct",
        endpoint=f"http://127.0.0.1:{MCP_PORT}/mcp",
        match_score=0.92,
        auth=AuthConfig(
            scheme=AuthScheme.bearer,
            location=AuthLocation.header,
            env_var=MCP_ENV_VAR,      # TokenResolver reads this — never the token itself
        ),
        policy=ResourcePolicy(is_paid=False, requires_auth=True),
    )


def ga_proxy_manifest(ga_url: str = f"http://127.0.0.1:{GA_PORT}") -> ResourceManifest:
    """Path 3: MCP stdio via ga_proxy — the GA spawns the process, not the PA."""
    return ResourceManifest(
        resource_id=STDIO_RES_ID,
        name="mock-health-search",
        type=ResourceType.mcp,
        protocol_binding=ProtocolBinding.MCP_STDIO,
        description="Mock health search stdio tool",
        capability_tags=["health", "patient", "records"],
        callable_by="ga_proxy",
        command=["python", "experiments/pa/exp2_resource_manifest/servers/mock_stdio_server.py"],
        ga_url=ga_url,
        match_score=0.90,
        auth=AuthConfig(scheme=AuthScheme.none),
        policy=ResourcePolicy(is_paid=False, requires_auth=False),
    )
