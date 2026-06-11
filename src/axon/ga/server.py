"""
ga/server.py — FastAPI Gateway Agent server.

Endpoints:
  GET  /ga/card                  → GatewayCard dinâmico via ga/card.py
  POST /ga/resources             → registra recurso (valida token + persiste)
  GET  /ga/resources             → lista recursos com status
  POST /ga/resources/search      → busca semântica via ga/retrieval.py
  POST /ga/resources/{id}/invoke → ga_proxy: GA executa a tool MCP em nome do PA

Cada request instancia GAConfig.resolve() — lê o contexto ativo
via AXON_GA_CONTEXT env var injetado pelo axon ga serve.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Axon Gateway Agent",
    version="0.1.0",
    docs_url="/docs",
)

_FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="14" fill="#4f46e5"/>'
    '<path d="M32 14 18 50h7l3-8h12l3 8h7L32 14zm-3.5 22L32 27l3.5 9h-7z" '
    'fill="#fff"/></svg>'
)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(content=_FAVICON_SVG, media_type="image/svg+xml")


def _ga() -> "GAConfig":  # type: ignore[name-defined]
    from axon.ga.config import GAConfig
    return GAConfig.resolve()


# ── GET /ga/card ──────────────────────────────────────────────────────────────

@app.get("/ga/card")
async def get_card() -> JSONResponse:
    """Returns the GatewayCard for this GA instance."""
    from axon.ga.card import build_card
    try:
        return JSONResponse(build_card(_ga()))
    
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── POST /ga/resources ────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    url:  str
    name: str | None = None


@app.post("/ga/resources", status_code=201)
async def register_resource(
    req: RegisterRequest,
    x_axon_pa_id: str | None = Header(default=None),
) -> dict:
    """Register an A2A agent. Validates Axon token before persisting."""
    if not x_axon_pa_id:
        raise HTTPException(status_code=401, detail="X-Axon-PA-ID header is required")

    import secrets
    from axon.validator import validate_agent
    from axon.ga.registry import add_resource, resource_exists
    from axon.ga.tokens import mark_used
    from axon.types import Resource, ResourceType, ResourceStatus, ProtocolBinding

    ga     = _ga()
    result = validate_agent(req.url, ga.paths)

    if not result.ok:
        raise HTTPException(
            status_code=422,
            detail={"step": result.step, "error": result.error},
        )

    card = result.agent_card
    name = req.name or card.name

    if resource_exists(name, ga.paths):
        raise HTTPException(
            status_code=409,
            detail=f"resource '{name}' is already registered — use 'axon ga resource remove {name}' first",
        )

    resource = Resource(
        id=f"res-{secrets.token_hex(3)}",
        type=ResourceType.agent,
        protocol_binding=ProtocolBinding.HTTP_JSON,
        name=name,
        endpoint=req.url,
        description=card.description,
        skills=card.skills,
        fingerprint=result.fingerprint or "",
        status=ResourceStatus.online,
    )

    try:
        add_resource(resource, ga.paths)
        mark_used(result.verified_token, resource.id, ga.paths)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    logger.info("[GA:%s] registered %s (%s)", ga.context, resource.name, resource.id)

    return {
        "id":          resource.id,
        "name":        resource.name,
        "type":        resource.type.value,
        "endpoint":    resource.endpoint,
        "fingerprint": resource.fingerprint,
        "status":      resource.status.value,
    }


# ── GET /ga/resources 

@app.get("/ga/resources")
async def list_resources_endpoint() -> dict:
    """List all registered resources."""
    from axon.ga.registry import list_resources

    resources = list_resources(_ga().paths)
    return {
        "count":     len(resources),
        "resources": [
            {
                "id":               r.id,
                "name":             r.name,
                "type":             r.type.value,
                "protocol_binding": r.protocol_binding.value,
                "endpoint":         r.endpoint,
                "command":          r.command,
                "auth":             r.auth.model_dump(mode="json"),
                "policy":           r.policy.model_dump(mode="json"),
                "description":      r.description,
                "status":           r.status.value,
                "skills": [
                    {"id": s.id, "description": s.description, "tags": s.tags}
                    for s in (r.skills or [])
                ],
            }
            for r in resources
        ],
    }


# ── POST /pa/connect

class ConnectRequest(BaseModel):
    name:         str
    version:      str        = "0.1.0"
    organization: str | None = None
    url:          str | None = None


@app.post("/pa/connect")
async def pa_connect(req: ConnectRequest) -> dict:
    """Register a Principal Agent connection (PACard). Observability handshake."""
    from axon.ga.connections import add_connection
    from axon.ga.registry import list_resources
    from axon.types import PACard

    ga   = _ga()
    card = PACard(
        name=req.name, version=req.version,
        organization=req.organization, url=req.url,
    )
    conn = add_connection(card, ga.paths)
    logger.info("[GA:%s] PA connected: %s v%s", ga.context, card.name, card.version)

    return {
        "status":          "connected",
        "gateway":         ga.name,
        "context":         ga.context,
        "resources_count": len(list_resources(ga.paths)),
        "connected_at":    conn.connected_at.isoformat(),
    }


# ── POST /ga/resources/search 

class SearchRequest(BaseModel):
    query:        str
    capabilities: list[str] = []
    max_results:  int        = 5


@app.post("/ga/resources/search")
async def search_resources(req: SearchRequest) -> dict:
    """Search resources by capability tags and query text."""
    from axon.ga.retrieval import search

    results = search(
        query=req.query,
        paths=_ga().paths,
        capabilities=req.capabilities or None,
        max_results=req.max_results,
    )

    return {
        "query":   req.query,
        "count":   len(results),
        "results": [
            {
                "id":               r.id,
                "name":             r.name,
                "type":             r.type.value,
                "protocol_binding": r.protocol_binding.value,
                "endpoint":         r.endpoint,
                "command":          r.command,
                "auth":             r.auth.model_dump(mode="json"),
                "policy":           r.policy.model_dump(mode="json"),
                "description":      r.description,
                "score":            round(score, 3),
                "skills": [
                    {"id": s.id, "description": s.description, "tags": s.tags}
                    for s in (r.skills or [])
                ],
            }
            for score, r in results
        ],
    }


# ── POST /ga/resources/{id}/invoke

class InvokeRequest(BaseModel):
    """
    Contrato do ga_proxy. O PA (Executor) pede ao GA para rodar uma tool MCP.

    tool    nome da tool a chamar; None → usa a única tool do servidor
    params  argumentos da tool
    task    intenção legível, só para log/observabilidade (opcional)
    """
    tool:   str | None = None
    params: dict        = {}
    task:   str | None = None


@app.post("/ga/resources/{resource_id}/invoke")
async def invoke_resource(
    resource_id: str,
    req:         InvokeRequest,
    x_axon_pa_id: str | None = Header(default=None),
) -> dict:
    """
    GA proxy — executa uma tool MCP em nome do PA (caminho ga_proxy).

    Usado por recursos MCP (tipicamente stdio) que o PA não roda direto: o GA
    spawna o processo, chama a tool e devolve o resultado. Agentes A2A e MCP
    HTTP/SSE são pa_direct — o PA os chama sem passar por aqui.
    """
    from axon.ga.registry import get_resource
    from axon.pa.clients.mcp_client import (
        MCPClient, MCPClientError, MCPToolNotFoundError,
    )
    from axon.types import ResourceManifest, ResourceType

    ga       = _ga()
    resource = get_resource(resource_id, ga.paths)

    if resource is None:
        raise HTTPException(
            status_code=404,
            detail=f"resource '{resource_id}' not found in context '{ga.context}'",
        )

    if resource.type != ResourceType.mcp:
        raise HTTPException(
            status_code=400,
            detail=(
                f"resource '{resource.name}' is {resource.type.value}; only MCP "
                f"resources are invokable via the GA proxy (A2A agents are called "
                f"directly by the PA)"
            ),
        )

    logger.info(
        "[GA:%s] invoke %s (%s) tool=%s pa=%s task=%r",
        ga.context, resource.name, resource.protocol_binding.value,
        req.tool or "<single>", x_axon_pa_id or "<anon>", (req.task or "")[:80],
    )

    # Reconstrói o manifesto de execução a partir do registry (auth resolvida
    # em runtime pelo MCPClient via TokenResolver, no ambiente do GA).
    manifest = ResourceManifest(
        resource_id=resource.id,
        name=resource.name,
        type=resource.type,
        protocol_binding=resource.protocol_binding,
        description=resource.description,
        callable_by="pa_direct",   # do ponto de vista do GA é uma chamada direta
        endpoint=resource.endpoint,
        command=resource.command,
        auth=resource.auth,
        policy=resource.policy,
    )

    try:
        async with MCPClient(manifest) as client:
            tools = await client.list_tools()
            tool  = req.tool or (tools[0] if len(tools) == 1 else None)
            if tool is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"resource exposes multiple tools {tools}; specify 'tool'",
                )
            if tool not in tools:
                raise HTTPException(
                    status_code=404,
                    detail=f"tool '{tool}' not found in '{resource.name}'; available: {tools}",
                )
            result = await client.call_tool(tool, req.params)
    except MCPToolNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MCPClientError as exc:
        # falha do recurso proxiado (transporte/execução) → 502 Bad Gateway
        logger.warning("[GA:%s] invoke %s failed: %s", ga.context, resource.name, exc)
        raise HTTPException(status_code=502, detail=str(exc))

    return {
        "resource_id": resource.id,
        "name":        resource.name,
        "type":        resource.type.value,
        "tool":        tool,
        "status":      "ok",
        "result":      result,
    }


# ── GET /health 

@app.get("/health")
async def health() -> dict:
    from axon.ga.registry import list_resources
    ga = _ga()
    return {
        "status":          "ok",
        "context":         ga.context,
        "version":         "0.1.0",
        "resources_count": len(list_resources(ga.paths)),
    }