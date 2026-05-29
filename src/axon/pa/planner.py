"""
pa/planner.py — Planner

Terceira etapa do pipeline do PA.

Responsabilidade:
  Receber a list[Subtask] do Decomposer e produzir um Plan
  com depends_on corretos, validado e ordenado topologicamente.

Algoritmo determinístico — sem LLM.

Lê:    state.plan.subtasks  (gerado pelo Decomposer)
Escreve: state.plan          (subtasks ordenadas, depends_on resolvidos)
         state.progress      ({ subtask_id: PENDING })

Etapas:
  1. Constrói mapa de artefatos { output_artifact → subtask_id }
  2. Resolve depends_on a partir de input_artifacts
  3. Valida consistência (3 verificações)
  4. Ordena topologicamente (Kahn's BFS)
  5. Escreve em state.plan e state.progress
"""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING

from axon.pa.models import Plan, Subtask, SubtaskStatus

if TYPE_CHECKING:
    from axon.pa.models import AgentState

logger = logging.getLogger(__name__)


# ── Erros ─────────────────────────────────────────────────────────────────────

class PlanError(Exception):
    """Raised quando o plano é inconsistente ou inválido."""


# ── Planner ───────────────────────────────────────────────────────────────────

class Planner:
    """
    Valida e ordena o plan gerado pelo Decomposer.

    Uso:
        planner = Planner()
        planner.plan(state)     # lê state.plan.subtasks, escreve state.plan + state.progress

    Ou standalone (para testes):
        plan = planner.build_plan(subtasks)
    """

    def plan(self, state: "AgentState") -> None:
        """
        Lê state.plan.subtasks, valida, ordena e escreve em state.plan e state.progress.

        Lê:    state.plan.subtasks
        Escreve: state.plan, state.progress

        Raises:
            PlanError: se o plano for inconsistente (artefato sem produtor,
                       dependência circular, subtask inexistente)
        """
        subtasks = list(state.plan.subtasks)

        if not subtasks:
            logger.warning("[Planner] received empty subtask list — nothing to plan")
            return

        ordered_plan = self.build_plan(subtasks)

        state.plan     = ordered_plan
        state.progress = {
            s.id: SubtaskStatus.PENDING
            for s in ordered_plan.subtasks
        }

        topo_order = " → ".join(s.id for s in ordered_plan.subtasks)
        deps_summary = {
            s.id: s.depends_on
            for s in ordered_plan.subtasks
            if s.depends_on
        }

        logger.info(
            "[Planner] plan built — %d subtask(s) in topological order: %s",
            len(ordered_plan.subtasks),
            topo_order,
        )

        state.append_step(
            subtask_id="planner",
            action="build DAG and topological sort",
            observation=(
                f"order: {topo_order}"
                + (f" | deps: {deps_summary}" if deps_summary else " | no dependencies")
            ),
        )

    def build_plan(self, subtasks: list[Subtask]) -> Plan:
        """
        Puro — resolve depends_on, valida e ordena.
        Não modifica o AgentState. Útil para testes.

        Returns:
            Plan com subtasks ordenadas topologicamente e depends_on resolvidos

        Raises:
            PlanError: se o plano for inconsistente
        """
        # Step 1 — mapa de artefatos
        artifact_map = _build_artifact_map(subtasks)
        logger.debug("[Planner] artifact map: %s", artifact_map)

        # Step 2 — resolve depends_on a partir de input_artifacts
        subtasks = _resolve_depends_on(subtasks, artifact_map)

        # Step 3 — validação
        _validate(subtasks, artifact_map)

        # Step 4 — sort topológico
        ordered = _topological_sort(subtasks)

        return Plan(subtasks=ordered)


# ── Step 1 — mapa de artefatos ────────────────────────────────────────────────

def _build_artifact_map(subtasks: list[Subtask]) -> dict[str, str]:
    """
    Constrói { output_artifact → subtask_id } para todas as subtasks.

    Detecta duplicatas — dois produtores do mesmo artefato é um erro do Decomposer.
    """
    artifact_map: dict[str, str] = {}

    for s in subtasks:
        if not s.output_artifact:
            continue
        if s.output_artifact in artifact_map:
            raise PlanError(
                f"duplicate output_artifact '{s.output_artifact}': "
                f"produced by both '{artifact_map[s.output_artifact]}' and '{s.id}'"
            )
        artifact_map[s.output_artifact] = s.id

    return artifact_map


# ── Step 2 — resolve depends_on ───────────────────────────────────────────────

def _resolve_depends_on(
    subtasks:     list[Subtask],
    artifact_map: dict[str, str],
) -> list[Subtask]:
    """
    Para cada subtask, deriva depends_on a partir de input_artifacts.

    Regra:
      - Se input_artifacts estão preenchidos → deriva depends_on do artifact_map
      - Se depends_on já veio do Decomposer → mantém deps adicionais (não-artefato)
      - A união de ambos é o depends_on final (sem duplicatas)
    """
    resolved: list[Subtask] = []

    for s in subtasks:
        # deps derivados de input_artifacts
        artifact_deps: list[str] = []
        for artifact in s.input_artifacts:
            producer = artifact_map.get(artifact)
            if producer and producer != s.id:
                artifact_deps.append(producer)

        # união com o que o Decomposer já tinha (ex: deps explícitos não-artefato)
        existing_deps = list(s.depends_on)
        merged_deps   = existing_deps + [d for d in artifact_deps if d not in existing_deps]

        if merged_deps != list(s.depends_on):
            s = s.model_copy(update={"depends_on": merged_deps})

        resolved.append(s)

    return resolved


# ── Step 3 — validação ────────────────────────────────────────────────────────

def _validate(
    subtasks:     list[Subtask],
    artifact_map: dict[str, str],
) -> None:
    """
    Três verificações determinísticas.

    Verificação 1 — artefato sem produtor
    Verificação 2 — subtask_id referenciada em depends_on inexistente
    Verificação 3 — dependência circular (detectada pelo Kahn's — aqui só valida IDs)
    """
    subtask_ids = {s.id for s in subtasks}

    for s in subtasks:

        # Verificação 1 — input_artifact sem produtor no mapa
        for artifact in s.input_artifacts:
            if artifact not in artifact_map:
                raise PlanError(
                    f"subtask '{s.id}' requires artifact '{artifact}' "
                    f"but no subtask produces it — "
                    f"available artifacts: {sorted(artifact_map.keys()) or 'none'}"
                )

        # Verificação 2 — depends_on referencia subtask inexistente
        for dep_id in s.depends_on:
            if dep_id not in subtask_ids:
                raise PlanError(
                    f"subtask '{s.id}' depends_on '{dep_id}' "
                    f"but '{dep_id}' is not in the plan — "
                    f"available ids: {sorted(subtask_ids)}"
                )

    # Verificação 3 — ciclo — feita implicitamente pelo Kahn's:
    # se _topological_sort não conseguir incluir todos os nós, há um ciclo


# ── Step 4 — sort topológico (Kahn's BFS) ─────────────────────────────────────

def _topological_sort(subtasks: list[Subtask]) -> list[Subtask]:
    """
    Ordena subtasks em ordem de execução válida.

    Usa o algoritmo de Kahn (BFS) — O(V+E).
    Detecta ciclos: se o resultado não contém todas as subtasks,
    há uma dependência circular.

    Para subtasks sem dependências entre si, mantém a ordem original
    do Decomposer (inputs first → stable sort).
    """
    subtask_map = {s.id: s for s in subtasks}
    in_degree   = {s.id: 0 for s in subtasks}
    dependents: dict[str, list[str]] = {s.id: [] for s in subtasks}

    for s in subtasks:
        for dep_id in s.depends_on:
            in_degree[s.id] += 1
            dependents[dep_id].append(s.id)

    # fila inicial — subtasks sem dependências (ordem original preservada)
    queue: deque[str] = deque(
        s.id for s in subtasks if in_degree[s.id] == 0
    )
    ordered: list[Subtask] = []

    while queue:
        current_id = queue.popleft()
        ordered.append(subtask_map[current_id])

        for dep_id in dependents[current_id]:
            in_degree[dep_id] -= 1
            if in_degree[dep_id] == 0:
                queue.append(dep_id)

    # ciclo detectado — algum nó nunca chegou a in_degree == 0
    if len(ordered) != len(subtasks):
        in_cycle = [s.id for s in subtasks if s.id not in {s.id for s in ordered}]
        raise PlanError(
            f"circular dependency detected among subtasks: {in_cycle}"
        )

    return ordered