"""
pa/policy.py — Avaliador de elegibilidade de recursos.

Fonte única de verdade para "este recurso pode ser usado?", combinando a
política do operador (ResourcePolicyConfig) com a política declarada pelo
recurso (ResourceManifest.policy) e o estado de auth (token configurado?).

Dois consumidores:
  Resolver._passes_policy  → filtra recursos vindos do GA (descarta os inelegíveis)
  CLI (gateway resources)  → mostra ao operador o status de cada recurso

Manter os dois alinhados é o ponto: o que o operador vê como "pronto" é
exatamente o que o Resolver aceita.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from axon.types import AuthScheme, ResourceManifest


class ResourceEligibility(BaseModel):
    """Resultado da avaliação de um recurso contra a política do operador."""
    resource_name: str
    eligible:      bool
    reasons:       list[str] = Field(default_factory=list)  # motivos de descarte (vazio se elegível)

    # dados para exibição
    is_paid:       bool         = False
    cost_per_call: float | None = None
    auth_scheme:   str          = "none"
    auth_ready:    bool         = True          # token presente OU não exige token estático
    auth_env_var:  str | None   = None          # var a configurar quando auth_ready=False


def evaluate(
    manifest: ResourceManifest,
    policy:   "ResourcePolicyConfig | None",  # noqa: F821
) -> ResourceEligibility:
    """
    Avalia um recurso. Coleta TODOS os motivos de descarte (um recurso pode ser
    pago E sem token, como no caso 'resend').

    A política do operador (`policy`) pode ser None — então nada é descartado,
    mas o estado de auth/pago ainda é computado para exibição.
    """
    from axon import token_resolver

    auth        = manifest.auth
    needs_token = auth.scheme in (AuthScheme.bearer, AuthScheme.api_key)

    env_var:    str | None = None
    auth_ready: bool       = True
    if needs_token:
        env_var    = auth.env_var or token_resolver._infer_env_var(manifest.name)
        auth_ready = token_resolver.resolve(manifest) is not None

    reasons: list[str] = []
    if policy is not None:
        if manifest.policy.is_paid and not policy.allow_paid:
            reasons.append("recurso pago desabilitado (allow_paid=false)")

        cost = manifest.policy.cost_per_call
        if (
            policy.max_cost_per_call is not None
            and cost is not None
            and cost > policy.max_cost_per_call
        ):
            reasons.append(
                f"custo ${cost:.4f}/call acima do limite ${policy.max_cost_per_call:.4f}"
            )

        if policy.require_auth_setup and needs_token and not auth_ready:
            reasons.append(f"set {env_var} para habilitar")

    return ResourceEligibility(
        resource_name=manifest.name,
        eligible=not reasons,
        reasons=reasons,
        is_paid=manifest.policy.is_paid,
        cost_per_call=manifest.policy.cost_per_call,
        auth_scheme=auth.scheme.value,
        auth_ready=auth_ready,
        auth_env_var=env_var,
    )
