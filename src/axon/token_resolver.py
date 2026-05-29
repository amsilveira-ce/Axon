"""
token_resolver.py — TokenResolver

Módulo neutro (axon.*): usado tanto pelo PA (autenticar-se ao recurso na
execução) quanto pelo GA (conectar-se ao recurso na validação/registro).

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

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from axon.types import AuthLocation, AuthScheme, ResourceManifest

logger = logging.getLogger(__name__)

_ENV_PREFIX = "AXON_SECRET_"

_dotenv_loaded = False


def _ensure_dotenv() -> None:
    """
    Carrega o .env uma única vez para dentro de os.environ.

    override=False → exports reais do shell têm prioridade sobre o .env.
    No-op se python-dotenv não estiver instalado ou não houver .env.
    """
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        logger.debug("[TokenResolver] python-dotenv ausente — pulando .env")
        return
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path, override=False)
        logger.debug("[TokenResolver] .env carregado de %s", path)


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
    """
    Credencial resolvida — pronta para ser injetada na chamada.

    location=header → vai como header {name}: {value}
    location=query  → vai como query param ?{name}={value} na URL
    """

    def __init__(
        self,
        value: str,
        *,
        location: AuthLocation = AuthLocation.header,
        name: str = "Authorization",
    ) -> None:
        self.value    = value      # ex: "Bearer eyJ..." (bearer) ou o token cru (api_key)
        self.location = location
        self.name     = name       # nome do header ou do query param

    def as_headers(self) -> dict[str, str]:
        """Headers a injetar (vazio se a credencial não for de header)."""
        return {self.name: self.value} if self.location == AuthLocation.header else {}

    def as_env(self) -> dict[str, str]:
        """Env vars a injetar no processo filho (vazio se não for location=env)."""
        return {self.name: self.value} if self.location == AuthLocation.env else {}

    def apply_to_url(self, url: str) -> str:
        """Aplica a credencial à URL quando location=query; senão devolve a URL intacta."""
        if self.location != AuthLocation.query:
            return url
        parts = urlparse(url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query[self.name] = self.value
        return urlunparse(parts._replace(query=urlencode(query)))

    def __repr__(self) -> str:
        masked = self.value[:12] + "..." if len(self.value) > 12 else "***"
        return f"ResolvedAuth({self.location.value}:{self.name}={masked})"


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
    _ensure_dotenv()
    auth = manifest.auth

    # none → sem auth.
    # oauth → não há credencial estática para resolver; o fluxo é interativo e
    #         delegado ao cliente MCP (fastmcp.OAuth). Nada para o resolver fazer.
    if auth.scheme in (AuthScheme.none, AuthScheme.oauth):
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

    if auth.scheme == AuthScheme.bearer:
        # bearer é sempre header
        resolved = ResolvedAuth(
            f"Bearer {token}",
            location=AuthLocation.header,
            name=auth.header or "Authorization",
        )

    elif auth.scheme == AuthScheme.api_key:
        if auth.location == AuthLocation.query:
            name = auth.param
            if not name:
                logger.warning(
                    "[TokenResolver] api_key/query para '%s' sem 'param' definido",
                    manifest.name,
                )
                return None
            resolved = ResolvedAuth(token, location=AuthLocation.query, name=name)
        elif auth.location == AuthLocation.env:
            # stdio: o segredo é injetado no env do processo filho sob env_var
            # (o mesmo nome que o servidor MCP lê — ex.: RESEND_API_KEY).
            resolved = ResolvedAuth(token, location=AuthLocation.env, name=env_var)
        else:
            resolved = ResolvedAuth(
                token,
                location=AuthLocation.header,
                name=auth.header or "X-Api-Key",
            )

    else:
        logger.warning(
            "[TokenResolver] unsupported auth scheme '%s' for '%s'",
            auth.scheme, manifest.name,
        )
        return None

    logger.debug("[TokenResolver] resolved auth for '%s': %s", manifest.name, resolved)
    return resolved


def resolve_or_raise(manifest: ResourceManifest) -> ResolvedAuth | None:
    """
    Igual a resolve(), mas levanta TokenResolverError se o token é necessário
    e não está configurado.

    Usado quando require_auth_setup=True na ResourcePolicyConfig.
    """
    auth    = manifest.auth
    # none/oauth não têm token estático — nada a exigir do ambiente.
    if auth.scheme in (AuthScheme.none, AuthScheme.oauth):
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
    if manifest.auth.env_var is None and manifest.auth.scheme not in (
        AuthScheme.none, AuthScheme.oauth,
    ):
        inferred = _infer_env_var(manifest.name)
        return manifest.model_copy(
            update={"auth": manifest.auth.model_copy(update={"env_var": inferred})}
        )
    return manifest