"""
ga/server.py — FastAPI Gateway Agent server.

Endpoints:
  GET  /ga/card                  → GatewayCard dinâmico via ga/card.py
  POST /ga/resources             → registra recurso (valida token + persiste)
  GET  /ga/resources             → lista recursos com status
  POST /ga/resources/search      → busca semântica via ga/retrieval.py
  POST /ga/resources/{id}/invoke → ga_proxy stub

Cada request instancia GAConfig.resolve() — lê o contexto ativo
via AXON_GA_CONTEXT env var injetado pelo axon ga serve.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
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
async def register_resource(req: RegisterRequest) -> dict:
    """Register an A2A agent. Validates Axon token before persisting."""
    import secrets
    from axon.validator import validate_agent
    from axon.ga.registry import add_resource
    from axon.ga.tokens import mark_used, TokenVerificationError
    from axon.types import Resource, ResourceType, ResourceStatus

    ga = _ga()
    result = validate_agent(req.url)

    if not result.ok:
        raise HTTPException(
            status_code=422,
            detail={"step": result.step, "error": result.error},
        )

    card     = result.agent_card
    resource = Resource(
        id=f"res-{secrets.token_hex(3)}",
        type=ResourceType.agent,
        name=req.name or card.name,
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
                "id":          r.id,
                "name":        r.name,
                "type":        r.type.value,
                "endpoint":    r.endpoint,
                "description": r.description,
                "status":      r.status.value,
                "skills": [
                    {"id": s.id, "description": s.description, "tags": s.tags}
                    for s in r.skills
                ],
            }
            for r in resources
        ],
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
                "id":          r.id,
                "name":        r.name,
                "type":        r.type.value,
                "endpoint":    r.endpoint,
                "description": r.description,
                "score":       round(score, 3),
                "skills": [
                    {"id": s.id, "description": s.description, "tags": s.tags}
                    for s in r.skills
                ],
            }
            for score, r in results
        ],
    }


# ── POST /ga/resources/{id}/invoke 

class InvokeRequest(BaseModel):
    task:    str
    payload: dict = {}


@app.post("/ga/resources/{resource_id}/invoke")
async def invoke_resource(resource_id: str, req: InvokeRequest) -> dict:
    """GA proxy — invoke a registered resource on behalf of the PA. MVP stub."""
    from axon.ga.registry import get_resource

    ga       = _ga()
    resource = get_resource(resource_id, ga.paths)

    if resource is None:
        raise HTTPException(
            status_code=404,
            detail=f"resource '{resource_id}' not found in context '{ga.context}'",
        )

    logger.info(
        "[GA:%s] invoke %s (%s) task=%r",
        ga.context, resource.name, resource.type.value, req.task[:80],
    )

    return {
        "resource_id": resource_id,
        "name":        resource.name,
        "type":        resource.type.value,
        "task":        req.task,
        "status":      "accepted",
        "result":      None,
        "note":        "execution not yet implemented — Resolver/Executor pending",
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