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

Step 3 — filtra por ResourcePolicy (pago / custo)
Step 4 — TokenResolver (fail-fast: descarta auth sem token)

Quando nada resolve uma capability obrigatória, aplica o fallback_strategy do
operador (ResourcePolicyConfig): skip → marca SKIPPED e segue; fail → registra
Failure e interrompe; ask_user → devolve ClarificationNeeded ao usuário.
Subtasks opcionais são sempre SKIPPED, independente da estratégia.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from axon.pa.clients.ga_client import GAClient, GAClientError
from axon.pa.ga_affinity import GAAffinityStore
from axon.pa.models import ResolverResult
from axon.types import ResourceManifest

if TYPE_CHECKING:
    from axon.config import ResourcePolicyConfig
    from axon.pa.models import AgentState, ClarificationNeeded, Subtask
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
    """Raised quando uma subtask obrigatória não pode ser resolvida (fallback_strategy=fail)."""


class ResolverClarification(Exception):
    """
    Raised quando fallback_strategy=ask_user e uma subtask obrigatória não pôde
    ser resolvida. Carrega o ClarificationNeeded para o agent devolver ao usuário,
    pelo mesmo caminho que o IntentExtractor usa para pedir esclarecimento.
    """
    def __init__(self, clarification: "ClarificationNeeded") -> None:
        self.clarification = clarification
        super().__init__(clarification.context)


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
        policy:          "ResourcePolicyConfig | None"     = None,
        client_factory:  Callable[[str], GAClient] | None  = None,
        max_results:     int                               = 5,
        min_match_score: float                             = 0.0,
    ) -> None:
        self._gateways        = list(gateways or [])
        self._affinity        = affinity
        self._affinity_path   = affinity_path
        self._cache           = cache
        self._policy          = policy
        self._client_factory  = client_factory or GAClient
        self._max_results     = max_results
        self._min_match_score = min_match_score

    def resolve(self, state: "AgentState") -> None:
        """
        Itera sobre as subtasks e preenche state.resource_assignments.

        Raises:
            ResolverError: fallback_strategy=fail e subtask obrigatória não resolvida.
            ResolverClarification: fallback_strategy=ask_user nessa mesma situação.
        """
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

        # ── subtasks ainda não cobertas → fallback do operador ────────────────────
        if unresolved:
            self._handle_unresolved(unresolved, state)

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

            # reward parcial (match + speed) deste GA — fase 1 do bandit.
            # Registrado ANTES do filtro de política: o UCB mede a qualidade de
            # retrieval do GA, não é penalizado por recursos que a política do
            # operador descarta (a restrição é do operador, não do recurso).
            if self._affinity is not None:
                self._affinity.update_partial(
                    ga_url=ga_url,
                    capability=pending.capability,
                    match_score=result.match_score,
                    latency_ms=result.latency_ms,
                )

            # Step 3 (política) + Step 4 (token) — descarta os inelegíveis
            allowed = self._filter_candidates(
                [result.manifest, *result.alternatives], pending
            )
            if not allowed:
                logger.info(
                    "[Resolver] step3/4 — todos os candidatos de %s descartados (subtask=%s)",
                    ga_url, pending.subtask_id,
                )
                continue
            result = result.model_copy(
                update={"manifest": allowed[0], "alternatives": allowed[1:]}
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
            chosen.manifest.last_used = datetime.now(timezone.utc)   # marca descoberta/refresh
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

    # ── fallback: nenhum recurso elegível para uma capability ─────────────────────

    def _handle_unresolved(
        self, unresolved: list["Subtask"], state: "AgentState"
    ) -> None:
        """
        Decide o destino das subtasks que ficaram sem recurso.

        Opcionais são sempre SKIPPED (o plano foi desenhado para sobreviver sem
        elas). As obrigatórias seguem o fallback_strategy do operador:

          skip     → marca SKIPPED e o plano continua sem a subtask
          fail     → registra Failure no AgentState e interrompe (ResolverError)
          ask_user → devolve ClarificationNeeded ao usuário (ResolverClarification)

        Sem política configurada, o default é fail — preserva o comportamento
        anterior (erro duro) para um Resolver construído sem ResourcePolicyConfig.
        """
        from axon.pa.models import Failure, SubtaskStatus

        required: list["Subtask"] = []
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
                required.append(subtask)

        if not required:
            return

        strategy = self._policy.fallback_strategy if self._policy else "fail"
        caps = ", ".join(sorted({s.capability_required for s in required}))
        logger.info(
            "[Resolver] %d required subtask(s) unresolved (%s) — fallback_strategy=%s",
            len(required), caps, strategy,
        )

        if strategy == "skip":
            for s in required:
                state.progress[s.id] = SubtaskStatus.SKIPPED
                logger.warning(
                    "[Resolver] fallback skip — subtask=%s capability=%s dropped",
                    s.id, s.capability_required,
                )
                state.append_step(
                    subtask_id=s.id,
                    action=f"resolve capability: {s.capability_required}",
                    observation="skipped — no resource available (fallback_strategy=skip)",
                )
            return

        if strategy == "ask_user":
            raise ResolverClarification(self._build_clarification(required))

        # strategy == "fail" (e default sem política)
        for s in required:
            state.progress[s.id] = SubtaskStatus.FAILED
            state.failures.append(Failure(
                subtask_id=s.id,
                tool=None,
                error=f"no resource for capability '{s.capability_required}'",
                reason="no connected Gateway Agent provided an eligible resource",
            ))
        raise ResolverError(self._fail_message(required, state))

    def _build_clarification(self, subtasks: list["Subtask"]) -> "ClarificationNeeded":
        """Monta o ClarificationNeeded (máx. 3 perguntas — contrato do modelo)."""
        from axon.pa.models import ClarificationNeeded, ClarificationQuestion

        questions = [
            ClarificationQuestion(
                question=(
                    f"I couldn't find a resource for '{s.capability_required}' "
                    f"(needed to: {s.description}). Do you have access to a system "
                    f"that provides this capability?"
                ),
                ambiguous_span=s.capability_required,
            )
            for s in subtasks[:3]
        ]
        context = (
            f"I couldn't resolve {len(subtasks)} step(s) of your request: no "
            f"connected Gateway Agent offers the required capability."
        )
        extra = len(subtasks) - len(questions)
        if extra > 0:
            context += f" ({extra} more not shown.)"
        return ClarificationNeeded(questions=questions, context=context)

    def _fail_message(self, subtasks: list["Subtask"], state: "AgentState") -> str:
        caps = ", ".join(sorted({s.capability_required for s in subtasks}))
        available = sorted({t for m in state.resource_pool for t in m.capability_tags})
        return (
            f"no resource found for required capabilit(ies): {caps}\n"
            f"  available capabilities: {available}\n"
            f"  connect a Gateway Agent that provides them: axon pa gateway add <url>"
        )

    # ── Step 3 (política) + Step 4 (token) ────────────────────────────────────────

    def _filter_candidates(
        self, manifests: list[ResourceManifest], pending: PendingCapability
    ) -> list[ResourceManifest]:
        """
        Descarta candidatos por duas etapas distintas, preservando a ordem
        (best-first do GA). Usa os mesmos checks que a CLI mostra na tabela.

          Step 3 — política do operador (pago / custo)
          Step 4 — token: auth != none/oauth precisa do segredo resolvível

        Falha cedo: um recurso sem token configurado é descartado AQUI, não na
        execução. Nenhum dos descartes penaliza o UCB.
        """
        from axon.pa.policy import policy_violations, token_status

        kept: list[ResourceManifest] = []
        for m in manifests:
            # Step 3 — política econômica
            viol = policy_violations(m, self._policy)
            if viol:
                logger.info(
                    "[Resolver] step3 descarte (política) subtask=%s resource=%s — %s",
                    pending.subtask_id, m.name, "; ".join(viol),
                )
                continue

            # Step 4 — resolução de token (fail-fast)
            ready, _env, reason = token_status(m)
            if not ready:
                logger.info(
                    "[Resolver] step4 descarte (token) subtask=%s resource=%s — %s",
                    pending.subtask_id, m.name, reason,
                )
                continue

            kept.append(m)
        return kept


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
