"""
ga/card.py — GatewayCard gerado dinamicamente.

Lê ga.json da instância ativa para nome, descrição e metadados.
Consulta o registry ao vivo para resources_count.
Nunca tem valores hardcoded.
"""
from __future__ import annotations

import json

from axon.ga.config import GAConfig, GAPaths
from axon.ga.registry import list_resources
from axon.types import AXON_GATEWAY_EXTENSION_URI


# Defaults quando ga.json não existe ou campo está ausente
_DEFAULTS = {
    "name":         "Axon Gateway Agent",
    "description":  "Gateway Agent — manages and exposes registered resources.",
    "organization": None,
    "trust_level":  "local",
    "accepted_types": ["a2a_agent", "mcp_http", "mcp_stdio"],
    "requires_token": True,
}


def _read_ga_json(paths: GAPaths) -> dict:
    """Lê ga.json da instância. Retorna dict vazio se não existe."""
    if not paths.ga_config.exists():
        return {}
    try:
        return json.loads(paths.ga_config.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_card(ga_config: GAConfig) -> dict:
    """
    Monta o GatewayCard como dict para o endpoint GET /ga/card.

    Fontes (em ordem de prioridade):
      1. ga.json da instância  (operador edita)
      2. GAInstanceConfig      (nome e porta do axon.config.json)
      3. defaults hardcoded    (fallback seguro)
    """
    paths       = ga_config.paths
    ga_json     = _read_ga_json(paths)
    resources   = list_resources(paths)

    name        = ga_json.get("name")        or ga_config.name        or _DEFAULTS["name"]
    description = ga_json.get("description") or _DEFAULTS["description"]
    organization= ga_json.get("organization") or _DEFAULTS["organization"]
    trust_level = ga_json.get("trust_level") or _DEFAULTS["trust_level"]
    accepted    = ga_json.get("accepted_types") or _DEFAULTS["accepted_types"]
    req_token   = ga_json.get("requires_token",  _DEFAULTS["requires_token"])
    version     = ga_json.get("version", "0.1.0")

    return {
        "name":        name,
        "description": description,
        "url":         f"http://localhost:{ga_config.port}",
        "version":     version,
        "capabilities": {
            "extensions": [
                {
                    "uri":    AXON_GATEWAY_EXTENSION_URI,
                    "params": {
                        "axon_version":    "0.1.0",
                        "organization":    organization,
                        "trust_level":     trust_level,
                        "resources_count": len(resources),
                        "accepted_types":  accepted,
                        "requires_token":  req_token,
                    },
                }
            ]
        },
    }