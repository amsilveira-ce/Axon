"""
health.py — monitor de integridade dos recursos registrados.

Estratégia por tipo de recurso:

  agent (A2A):
    GET /.well-known/agent-card.json (ou agent.json, rota legada)
      → não responde          → offline  ("conserte a conexão")
      → responde + fp bate    → online
      → responde + fp diverge → drift    ("re-valide o contrato antes de confiar")

    offline e drift são estados DISTINTOS: drift significa que o agente está
    vivo e respondendo, mas o que ele oferece não corresponde mais ao que foi
    registrado. O fingerprint é HMAC-SHA256 keyed pelo token de admissão —
    o mesmo cálculo do registro (registry.fingerprint_of_agent_card). O token
    é recuperado de tokens.json (used_by == resource.id) ou de token_ref.

  mcp (qualquer transport):
    Monitoramento NÃO aplicável — by design, não por omissão (tese §4.4.2).
    stdio não tem servidor: o processo só existe durante a execução.
    HTTP exigiria apresentar credenciais do operador, que o GA não guarda
    (credential boundary). Nenhuma request é feita; o status é preservado.
"""
import logging
from dataclasses import dataclass

import httpx

from axon.types import AgentCard, Resource, ResourceStatus, ResourceType
from axon.validator import AGENT_CARD_PATHS, TIMEOUT

logger = logging.getLogger(__name__)


@dataclass
class HealthResult:
    status:            ResourceStatus
    reachable:         bool
    fingerprint_match: bool | None     # None = não verificável/aplicável
    error:             str | None = None
    new_fingerprint:   str | None = None  # fingerprint atual se houve drift


def check_agent(resource: Resource, token: str | None = None) -> HealthResult:
    """
    Verifica um agente A2A via GET no agent card.

    Retorna:
      status=offline → não responde (connection refused, timeout, HTTP error)
      status=online  → responde e fingerprint bate (ou sem token p/ verificar)
      status=drift   → responde mas fingerprint diverge do registrado
    """
    base = resource.endpoint.rstrip("/")

    try:
        raw: dict | None = None
        for card_path in AGENT_CARD_PATHS:
            resp = httpx.get(f"{base}{card_path}", timeout=TIMEOUT, follow_redirects=True)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            raw = resp.json()
            break
        if raw is None:
            return HealthResult(
                status=ResourceStatus.offline,
                reachable=False,
                fingerprint_match=None,
                error="agent card not found (404)",
            )
    except httpx.ConnectError:
        return HealthResult(
            status=ResourceStatus.offline,
            reachable=False,
            fingerprint_match=None,
            error="connection refused",
        )
    except httpx.TimeoutException:
        return HealthResult(
            status=ResourceStatus.offline,
            reachable=False,
            fingerprint_match=None,
            error=f"timeout after {TIMEOUT}s",
        )
    except httpx.HTTPStatusError as e:
        return HealthResult(
            status=ResourceStatus.offline,
            reachable=False,
            fingerprint_match=None,
            error=f"HTTP {e.response.status_code}",
        )
    except Exception as e:
        return HealthResult(
            status=ResourceStatus.offline,
            reachable=False,
            fingerprint_match=None,
            error=str(e),
        )

    # Servidor respondeu — liveness OK. Sem token não há como recomputar o
    # fingerprint HMAC; reportamos online com drift indeterminado.
    if token is None:
        return HealthResult(
            status=ResourceStatus.online,
            reachable=True,
            fingerprint_match=None,
            error="admission token not found — drift check skipped",
        )

    try:
        card = AgentCard.model_validate(raw)
    except Exception:
        # vivo, mas o card nem parseia mais como A2A — contrato quebrado
        return HealthResult(
            status=ResourceStatus.drift,
            reachable=True,
            fingerprint_match=False,
            error="agent card no longer parses as A2A schema",
        )

    from axon.ga.registry import fingerprint_of_agent_card
    current_fp = fingerprint_of_agent_card(card, token)

    if current_fp == resource.fingerprint:
        return HealthResult(
            status=ResourceStatus.online,
            reachable=True,
            fingerprint_match=True,
        )

    return HealthResult(
        status=ResourceStatus.drift,
        reachable=True,
        fingerprint_match=False,
        new_fingerprint=current_fp,
        error=(
            f"agent card changed since registration — re-run 'axon add agent' to update.\n"
            f"  saved:   {resource.fingerprint}\n"
            f"  current: {current_fp}"
        ),
    )


def check_mcp(resource: Resource) -> HealthResult:
    """
    MCP não é monitorado — by design (credential boundary).

    stdio: o processo só existe durante a execução de uma tool call.
    HTTP:  uma sonda real exigiria as credenciais do operador (API keys),
           que o GA não armazena. Nenhuma request é feita.
    """
    logger.info(
        "monitoring not applicable: mcp (%s, %s)",
        resource.name, resource.protocol_binding.value,
    )
    return HealthResult(
        status=resource.status,    # preserva o status atual
        reachable=True,            # não sondado — assumido disponível
        fingerprint_match=None,
    )


def _admission_token(resource: Resource, paths) -> str | None:
    """Recupera o token de admissão que registrou o recurso (chave do HMAC)."""
    if resource.token_ref:
        return resource.token_ref
    if paths is None:
        return None
    from axon.ga.tokens import list_tokens
    return next(
        (t.token for t in list_tokens(paths) if t.used_by == resource.id),
        None,
    )


def check(resource: Resource, paths=None) -> HealthResult:
    """
    Despacha para o verificador correto baseado no tipo do resource.

    paths (GAPaths) habilita a verificação de drift: é de tokens.json que
    sai o token de admissão usado como chave do fingerprint HMAC.
    """
    if resource.type == ResourceType.agent:
        return check_agent(resource, token=_admission_token(resource, paths))
    return check_mcp(resource)


def run_cycle(paths) -> list[tuple[Resource, HealthResult]]:
    """
    Um ciclo completo do monitor: verifica cada recurso do registry e
    persiste transições de status (online ↔ offline, online → drift).

    Retorna [(resource_no_estado_anterior, HealthResult)] na ordem do registry.
    """
    from axon.ga.registry import list_resources, update_status

    results: list[tuple[Resource, HealthResult]] = []
    for resource in list_resources(paths):
        result = check(resource, paths)
        if result.status != resource.status:
            logger.info(
                "[Health] %s: %s → %s",
                resource.name, resource.status.value, result.status.value,
            )
            update_status(resource.id, result.status, paths)
        results.append((resource, result))
    return results
