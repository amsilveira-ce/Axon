"""
pa/policy.py — Avaliador de elegibilidade de recursos.

Fonte única de verdade para "este recurso pode ser usado?", combinando:

  Step 3 — política do operador (ResourcePolicyConfig): pago / custo
  Step 4 — resolução de token (TokenResolver): auth != none precisa do segredo

Dois consumidores:
  Resolver       → roda Step 3 e Step 4 como etapas distintas e descarta os inelegíveis
  CLI (resources)→ chama evaluate() (Step 3 + Step 4 juntos) para mostrar o status

Manter os dois alinhados é o ponto: o que o operador vê como "pronto" é
exatamente o que o Resolver aceita. O token nunca é persistido — o Step 4 apenas
verifica que resolve; o Executor re-resolve em runtime via TokenResolver.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from axon.types import AuthScheme, ResourceManifest

if TYPE_CHECKING:
    from axon.config import ResourcePolicyConfig


class ResourceEligibility(BaseModel):
    """Resultado da avaliação de um recurso contra política + auth."""
    resource_name: str
    eligible:      bool
    reasons:       list[str] = Field(default_factory=list)  # motivos de descarte (vazio se elegível)

    # dados para exibição
    is_paid:       bool         = False
    cost_per_call: float | None = None
    auth_scheme:   str          = "none"
    auth_ready:    bool         = True          # token presente OU não exige token estático
    auth_env_var:  str | None   = None          # var a configurar quando auth_ready=False


def policy_violations(
    manifest: ResourceManifest,
    policy:   "ResourcePolicyConfig | None",  # noqa: F821
) -> list[str]:
    """
    Step 3 — política econômica do operador (pago / custo).

    Retorna a lista de violações (vazia = passa). Não toca em auth — isso é o
    Step 4. A política pode ser None (nada a impor).
    """
    reasons: list[str] = []
    if policy is None:
        return reasons

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

    return reasons


def token_status(manifest: ResourceManifest) -> tuple[bool, str | None, str | None]:
    """
    Step 4 — resolução de token.

    Para auth.scheme != none/oauth, resolve o segredo via TokenResolver.
    Retorna (ready, env_var, reason_if_missing):
      none/oauth  → (True, None, None)   — sem token estático a resolver
      token ok    → (True, env_var, None)
      token falta → (False, env_var, "set <ENV> para habilitar")

    O segredo NÃO é retornado nem persistido — só verificamos que resolve.
    """
    from axon import token_resolver

    auth = manifest.auth
    if auth.scheme in (AuthScheme.none, AuthScheme.oauth):
        return True, None, None

    env_var = auth.env_var or token_resolver._infer_env_var(manifest.name)
    ready   = token_resolver.resolve(manifest) is not None
    return ready, env_var, (None if ready else f"set {env_var} para habilitar")


def evaluate(
    manifest: ResourceManifest,
    policy:   "ResourcePolicyConfig | None",  # noqa: F821
) -> ResourceEligibility:
    """
    Elegibilidade completa = Step 3 (política) + Step 4 (token), na ordem.
    Usado pela CLI para mostrar o status; o Resolver roda os dois como etapas
    separadas mas chega ao mesmo veredito.
    """
    reasons = policy_violations(manifest, policy)
    ready, env_var, tok_reason = token_status(manifest)
    if tok_reason:
        reasons.append(tok_reason)

    return ResourceEligibility(
        resource_name=manifest.name,
        eligible=not reasons,
        reasons=reasons,
        is_paid=manifest.policy.is_paid,
        cost_per_call=manifest.policy.cost_per_call,
        auth_scheme=manifest.auth.scheme.value,
        auth_ready=ready,
        auth_env_var=env_var,
    )
