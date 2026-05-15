from __future__ import annotations

from axon.config import PAConfig


class PrincipalAgent:
    """
    Orquestrador central do Axon.

    Recebe uma query em linguagem natural e coordena o ciclo completo:
      1. IntentExtractor  — query → Objective | ClarificationNeeded
      2. Decomposer       — Objective → list[Subtask]
      3. Planner          — list[Subtask] → Plan (DAG)
      4. Resolver         — Plan + GatewayAgents → resource_pool
      5. Executor         — Plan + resource_pool → Facts + Failures
    """

    def __init__(self, config: PAConfig) -> None:
        self.config = config
        # TODO: instanciar OllamaClient, IntentExtractor e demais componentes

    # ------------------------------------------------------------------

    def run(self, query: str) -> str:
        """
        Ponto de entrada síncrono.

        Args:
            query: entrada bruta do usuário.

        Returns:
            str — resposta final produzida pelo sistema.
        """
        # 1. extrair intenção
        # intent = self._intent_extractor.extract(query)

        # 2. se ClarificationNeeded → retornar perguntas ao usuário
        # if isinstance(intent, ClarificationNeeded):
        #     return self._format_clarification(intent)

        # 3. decompor objetivo em subtarefas
        # subtasks = self._decomposer.decompose(intent)

        # 4. montar plano (DAG)
        # plan = self._planner.plan(subtasks)

        # 5. resolver recursos via Gateway Agents
        # resource_pool = self._resolver.resolve(plan)

        # 6. executar plano
        # result = self._executor.execute(plan, resource_pool)

        # 7. retornar resposta final
        # return result.summary

        return f"[PrincipalAgent] query recebida: {query!r}"