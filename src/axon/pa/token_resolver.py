"""
pa/token_resolver.py — TokenResolver

Responsabilidade:
  Resolver o token de autenticação do PA perante um recurso externo.
  Chamado pelo Resolver antes de entregar o ResourceManifest ao Executor.

Dois problemas de autenticação distintos no Axon:
  AxonToken   → recurso se autentica perante o GA no registro
  TokenResolver → PA se autentica perante o recurso na execução  ← aqui

Convenção de nomenclatura das env vars:
  resource name: "healthcare-agent-1"  → AXON_SECRET_HEALTHCARE_AGENT_1
  resource name: "resend"              → AXON_SECRET_RESEND
  resource name: "notion"              → AXON_SECRET_NOTION

O operador configura antes de iniciar o PA:
  export AXON_SECRET_HEALTHCARE_AGENT_1="eyJhbGci..."
  export AXON_SECRET_RESEND="re_AbCdEfGh..."

O token nunca é armazenado em disco — apenas em memória durante a execução.
"""

from __future__ import annotations

import logging
import os
import re

from axon.types import AuthScheme, ResourceManifest

logger = logging.getLogger(__name__)

_ENV_PREFIX = "AXON_SECRET_"


def _infer_env_var(name: str) -> str:
    """
    Infere o nome da variável de ambiente pela convenção Axon.

    Converte o nome do recurso para UPPER_SNAKE_CASE e prefixa com AXON_SECRET_.

    Examples:
        "healthcare-agent-1" → "AXON_SECRET_HEALTHCARE_AGENT_1"
        "resend"             → "AXON_SECRET_RESEND"
        "my.service.v2"      → "AXON_SECRET_MY_SERVICE_V2"
    """
    normalized = re.sub(r"[^a-zA-Z0-9]", "_", name).upper()
    return f"{_ENV_PREFIX}{normalized}"


class ResolvedAuth:
    """Token resolvido — pronto para ser injetado na chamada."""

    def __init__(self, header: str, value: str) -> None:
        self.header = header   # ex: "Authorization"
        self.value  = value    # ex: "Bearer eyJhbGci..."

    def as_dict(self) -> dict[str, str]:
        return {self.header: self.value}

    def __repr__(self) -> str:
        masked = self.value[:12] + "..." if len(self.value) > 12 else "***"
        return f"ResolvedAuth({self.header}: {masked})"


class TokenResolverError(Exception):
    """Raised quando o token é necessário mas não está configurado."""


def resolve(manifest: ResourceManifest) -> ResolvedAuth | None:
    """
    Resolve o token de autenticação para um ResourceManifest.

    Se auth.scheme == none → retorna None (sem autenticação necessária)
    Se token encontrado    → retorna ResolvedAuth com header montado
    Se token ausente       → loga mensagem clara e retorna None
                             (Resolver descarta o recurso)

    Args:
        manifest: ResourceManifest com auth.scheme e opcionalmente auth.env_var

    Returns:
        ResolvedAuth | None
    """
    auth = manifest.auth

    if auth.scheme == AuthScheme.none:
        return None

    # determina a env var — usa auth.env_var se configurada, infere pela convenção
    env_var = auth.env_var or _infer_env_var(manifest.name)
    token   = os.environ.get(env_var)

    if not token:
        logger.warning(
            "[TokenResolver] token not configured for '%s' — "
            "set %s to enable this resource",
            manifest.name,
            env_var,
        )
        return None

    # monta o header pelo scheme
    if auth.scheme == AuthScheme.bearer:
        header = auth.header or "Authorization"
        value  = f"Bearer {token}"

    elif auth.scheme == AuthScheme.api_key:
        header = auth.header or "X-Api-Key"
        value  = token

    else:
        logger.warning(
            "[TokenResolver] unsupported auth scheme '%s' for '%s'",
            auth.scheme, manifest.name,
        )
        return None

    resolved = ResolvedAuth(header=header, value=value)
    logger.debug("[TokenResolver] resolved auth for '%s': %s", manifest.name, resolved)
    return resolved


def resolve_or_raise(manifest: ResourceManifest) -> ResolvedAuth | None:
    """
    Igual a resolve(), mas levanta TokenResolverError se o token é necessário
    e não está configurado.

    Usado quando require_auth_setup=True na ResourcePolicyConfig.
    """
    auth    = manifest.auth
    if auth.scheme == AuthScheme.none:
        return None

    resolved = resolve(manifest)
    if resolved is None:
        env_var = auth.env_var or _infer_env_var(manifest.name)
        raise TokenResolverError(
            f"token not configured for '{manifest.name}'\n"
            f"  set {env_var} to enable this resource\n"
            f"  example: export {env_var}='your-token-here'"
        )
    return resolved


def inject(manifest: ResourceManifest) -> ResourceManifest:
    """
    Retorna uma cópia do manifest com auth.env_var preenchida pela convenção,
    sem resolver o token ainda.

    Usado pelo GA ao montar o ResourceManifest — garante que o Resolver
    sabe qual env var buscar mesmo quando o operador não declarou explicitamente.
    """
    if manifest.auth.env_var is None and manifest.auth.scheme != AuthScheme.none:
        inferred = _infer_env_var(manifest.name)
        return manifest.model_copy(
            update={"auth": manifest.auth.model_copy(update={"env_var": inferred})}
        )
    return manifest