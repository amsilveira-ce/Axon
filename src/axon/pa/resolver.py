"""
pa/resolver.py — Resolver (Step 1 local + Step 2 Gateway Agent)

Quarta etapa do pipeline do PA.

Responsabilidade:
  Para cada subtask do plano, encontrar o ResourceManifest que vai executá-la
  e registrar a atribuição em state.resource_assignments.

  Depois que o Resolver termina, o Executor pode começar sem descobrir nada —
  state.resource_assignments[subtask_id] → ResolverResult de quem executa.

Lê:    state.plan.subtasks
       state.resource_pool  (pré-populado: local + cache)
Escreve: state.resource_assignments  { subtask_id → ResolverResult }
         state.resource_pool          (recursos novos descobertos via GA)

Step 1 — verifica resource_pool local
  Procura em state.resource_pool um manifest que cubra capability_required.
  Critério de seleção: success_count desc, failure_count asc.
  Local tools têm prioridade implícita por virem primeiro no pool.
  Assignment local → ResolverResult com ga_url="" (Executor não toca no UCB).

Step 2 — consulta Gateway Agent
  Subtasks não cobertas vão ao GA via GAClient (POST /ga/resources/search).
  A ordem dos GAs vem do bandit UCB1 (GAAffinityStore): GAs nunca testados
  primeiro (score infinito), depois por reward médio + termo de exploração.
  Cada GA consultado recebe um reward parcial (match + speed) via update_partial;
  o componente de execução é fechado pelo Executor via update_final.

Step 3 — filtra por ResourcePolicy (pendente)
Step 4 — TokenResolver (pendente)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from axon.pa.clients.ga_client import GAClient, GAClientError
from axon.pa.ga_affinity import GAAffinityStore
from axon.pa.models import ResolverResult
from axon.types import ResourceManifest

if TYPE_CHECKING:
    from axon.pa.models import AgentState, Subtask
    from axon.pa.resource_cache import ResourceCache

logger = logging.getLogger(__name__)


@dataclass
class PendingCapability:
    """
    Estrutura de trabalho do Resolver (Step 2): uma capability ainda não coberta
    localmente, a ser buscada via Gateway Agent. Não persiste — só existe durante a run.
    """
    capability:  str   # ex: "content_creator"
    subtask_id:  str   # ex: "s3"
    description: str    # ex: "gerar relatório clínico em PDF"


class ResolverError(Exception):
    """Raised quando uma subtask obrigatória não pode ser resolvida."""


class Resolver:
    """
    Resolve recursos para cada subtask do plano.

    Step 1 (local) funciona sempre. Step 2 (GA) só acontece se o Resolver foi
    construído com uma lista de gateways e um GAAffinityStore.

    Uso:
        resolver = Resolver(
            gateways=[g.url for g in config.gateways],
            affinity=GAAffinityStore.load(paths.pa_ga_affinity),
            affinity_path=paths.pa_ga_affinity,
        )
        resolver.resolve(state)
        # state.resource_assignments preenchido
        # subtasks opcionais não resolvidas marcadas como SKIPPED
    """

    def __init__(
        self,
        gateways:        list[str] | None                  = None,
        affinity:        GAAffinityStore | None            = None,
        affinity_path:   Path | None                       = None,
        cache:           "ResourceCache | None"            = None,
        client_factory:  Callable[[str], GAClient] | None  = None,
        max_results:     int                               = 5,
        min_match_score: float                             = 0.0,
    ) -> None:
        self._gateways        = list(gateways or [])
        self._affinity        = affinity
        self._affinity_path   = affinity_path
        self._cache           = cache
        self._client_factory  = client_factory or GAClient
        self._max_results     = max_results
        self._min_match_score = min_match_score

    def resolve(self, state: "AgentState") -> None:
        """
        Itera sobre as subtasks e preenche state.resource_assignments.

        Raises:
            ResolverError: se subtask obrigatória não puder ser resolvida
                           (nem local, nem via GA).
        """
        from axon.pa.models import SubtaskStatus

        unresolved: list["Subtask"] = []

        # ── Step 1 — resource_pool local ────────────────────────────────────────
        for subtask in state.plan.subtasks:
            manifest = _find_in_pool(subtask.capability_required, state.resource_pool)

            if manifest:
                state.resource_assignments[subtask.id] = ResolverResult(
                    capability=subtask.capability_required,
                    subtask_id=subtask.id,
                    manifest=manifest,
                    ga_url="",           # local — Executor não atualiza UCB
                    match_score=0.0,
                    latency_ms=0.0,
                )
                logger.info(
                    "[Resolver] step1 ✓ subtask=%s capability=%s → resource=%s (%s)",
                    subtask.id, subtask.capability_required, manifest.resource_id, manifest.name,
                )
                state.append_step(
                    subtask_id=subtask.id,
                    action=f"resolve capability: {subtask.capability_required}",
                    observation=f"assigned: {manifest.name} ({manifest.resource_id}) via local pool",
                )
                continue

            unresolved.append(subtask)
            logger.debug(
                "[Resolver] step1 miss subtask=%s capability=%s — queuing for GA",
                subtask.id, subtask.capability_required,
            )

        # ── Step 2 — Gateway Agent ───────────────────────────────────────────────
        if unresolved and self._gateways:
            for subtask in list(unresolved):
                pending = PendingCapability(
                    capability=subtask.capability_required,
                    subtask_id=subtask.id,
                    description=subtask.description,
                )
                result = self._resolve_pending(pending, state)
                if result is not None:
                    unresolved.remove(subtask)
                    state.append_step(
                        subtask_id=subtask.id,
                        action=f"resolve capability: {subtask.capability_required}",
                        observation=(
                            f"assigned: {result.manifest.name} via GA {result.ga_url} "
                            f"(match={result.match_score:.2f}, {result.latency_ms:.0f}ms)"
                        ),
                    )

        # ── subtasks ainda não cobertas ──────────────────────────────────────────
        for subtask in unresolved:
            if subtask.is_optional:
                state.progress[subtask.id] = SubtaskStatus.SKIPPED
                logger.info(
                    "[Resolver] skipping optional subtask=%s (capability=%s not available)",
                    subtask.id, subtask.capability_required,
                )
                state.append_step(
                    subtask_id=subtask.id,
                    action=f"resolve capability: {subtask.capability_required}",
                    observation="skipped — capability not available (optional subtask)",
                )
            else:
                raise ResolverError(
                    f"no resource found for subtask '{subtask.id}' "
                    f"(capability: '{subtask.capability_required}')\n"
                    f"  available capabilities: "
                    f"{sorted({t for m in state.resource_pool for t in m.capability_tags})}\n"
                    f"  connect a Gateway Agent with this capability: "
                    f"axon pa gateway add <url>"
                )

        logger.info(
            "[Resolver] done — %d/%d subtasks assigned",
            len(state.resource_assignments), len(state.plan.subtasks),
        )

    # ── Step 2 internals ────────────────────────────────────────────────────────

    def _resolve_pending(
        self, pending: PendingCapability, state: "AgentState"
    ) -> ResolverResult | None:
        """
        2a. ordena os GAs candidatos por UCB1 (não-testados primeiro)
        2b. consulta — gather quando nada se sabe; senão líder + fallback
        2c. monta ResolverResult, registra update_partial, persiste e atribui

        Retorna o ResolverResult escolhido ou None se nenhum GA cobriu a capability.
        """
        ranked      = self._rank_gateways(pending.capability)
        all_unknown = self._all_untested(pending.capability)

        logger.info(
            "[Resolver] step2 subtask=%s capability=%s — mode=%s, ranked GAs=%s",
            pending.subtask_id, pending.capability,
            "broadcast (gather)" if all_unknown else "leader+fallback", ranked,
        )

        chosen:      ResolverResult | None = None
        queried_any: bool                  = False

        for ga_url in ranked:
            try:
                result = self._client_factory(ga_url).search(
                    query=pending.description,
                    capability=pending.capability,
                    subtask_id=pending.subtask_id,
                    max_results=self._max_results,
                )
            except GAClientError as exc:
                logger.warning("[Resolver] GA %s search failed: %s", ga_url, exc)
                continue

            if result is None:
                logger.debug(
                    "[Resolver] GA %s has no resource for capability=%s",
                    ga_url, pending.capability,
                )
                continue

            queried_any = True

            # reward parcial (match + speed) deste GA — fase 1 do bandit
            if self._affinity is not None:
                self._affinity.update_partial(
                    ga_url=ga_url,
                    capability=pending.capability,
                    match_score=result.match_score,
                    latency_ms=result.latency_ms,
                )

            if result.match_score >= self._min_match_score:
                if chosen is None or result.match_score > chosen.match_score:
                    chosen = result
                # líder definido: para no primeiro que passa (fallback só se falhar);
                # se nada é conhecido (all_unknown), continua para coletar reward de todos
                if not all_unknown:
                    break

        if (
            self._affinity is not None
            and self._affinity_path is not None
            and queried_any
        ):
            self._affinity.save(self._affinity_path)

        if chosen is None:
            logger.info(
                "[Resolver] step2 miss subtask=%s capability=%s — no GA covered it",
                pending.subtask_id, pending.capability,
            )
            return None

        state.resource_assignments[pending.subtask_id] = chosen
        state.resource_pool.append(chosen.manifest)        # disponível no resto desta run
        if self._cache is not None:
            self._cache.put(chosen.manifest)               # persiste p/ a próxima run → cache hit
        logger.info(
            "[Resolver] step2 ✓ subtask=%s capability=%s → %s via %s (match=%.2f, %.0fms)",
            pending.subtask_id, pending.capability, chosen.manifest.name,
            chosen.ga_url, chosen.match_score, chosen.latency_ms,
        )
        return chosen

    def _rank_gateways(self, capability: str) -> list[str]:
        """GAs candidatos ordenados por UCB desc — não-testados (score ∞) primeiro."""
        if self._affinity is None:
            return list(self._gateways)
        total = self._affinity.total_queries(capability)
        return sorted(
            self._gateways,
            key=lambda ga: self._affinity.ucb_score(ga, capability, total),
            reverse=True,
        )

    def _all_untested(self, capability: str) -> bool:
        """True quando nenhum GA candidato tem histórico para esta capability."""
        if self._affinity is None:
            return True
        total = self._affinity.total_queries(capability)
        return all(
            self._affinity.ucb_score(ga, capability, total) == float("inf")
            for ga in self._gateways
        )


# ── helpers ───────────────────────────────────────────────────────────────────

def _find_in_pool(
    capability: str,
    pool:       list[ResourceManifest],
) -> ResourceManifest | None:
    """
    Encontra o melhor manifest no pool para a capability requerida.

    Critério de seleção:
      1. capability em capability_tags (match exato)
      2. success_count desc — prefere recursos com histórico positivo
      3. failure_count asc  — descarta recursos com muitas falhas
      4. ordem do pool      — local tools vêm antes do cache por construção
    """
    candidates = [m for m in pool if capability in m.capability_tags]

    if not candidates:
        return None

    candidates.sort(
        key=lambda m: (m.success_count, -m.failure_count),
        reverse=True,
    )
    return candidates[0]
