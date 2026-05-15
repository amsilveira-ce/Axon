from __future__ import annotations

from axon.config import PAConfig
from axon.llms.ollama_client import OllamaClient
from axon.pa.intent_extractor import IntentExtractor
from axon.pa.models import ClarificationNeeded, IntentResult, Objective


class PrincipalAgent:
    """
    Orquestrador central do Axon.

    Coordena o ciclo completo:
      1. IntentExtractor  — query → Objective | ClarificationNeeded  ✦ ativo
      2. Decomposer       — Objective → list[Subtask]
      3. Planner          — list[Subtask] → Plan (DAG)
      4. Resolver         — Plan + GatewayAgents → resource_pool
      5. Executor         — Plan + resource_pool → Facts + Failures
    """

    def __init__(self, config: PAConfig) -> None:
        self.config = config

        client = OllamaClient(
            host=config.llm.host,
            model=config.llm.model,
            timeout=config.llm.timeout,
        )
        self._intent_extractor = IntentExtractor(client)

    # ------------------------------------------------------------------
    #   API pública
    # ------------------------------------------------------------------

    def extract_intent(self, query: str) -> IntentResult:
        """
        Expõe o passo 1 isolado — usado pelo chat interativo.

        Args:
            query: entrada bruta do usuário, podendo incluir contexto
                   acumulado de rodadas anteriores de clarificação.

        Returns:
            Objective | ClarificationNeeded
        """
        return self._intent_extractor.extract(query)

    def run(self, query: str) -> str:
        """
        Ponto de entrada síncrono para one-shot (axon pa run).

        Args:
            query: entrada bruta do usuário.

        Returns:
            str — resposta final produzida pelo sistema.
        """
        intent = self.extract_intent(query)

        if isinstance(intent, ClarificationNeeded):
            return self._format_clarification(intent)

        assert isinstance(intent, Objective)

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

        return self._format_objective(intent)

    # ------------------------------------------------------------------
    #   Formatters
    # ------------------------------------------------------------------

    def _format_clarification(self, intent: ClarificationNeeded) -> str:
        lines = [f"Entendi: {intent.context}", ""]
        for i, q in enumerate(intent.questions, 1):
            lines.append(f"{i}. {q.question}")
            lines.append(f"   (trecho: \"{q.ambiguous_span}\")")
            if q.options:
                lines.append(f"   opções: {', '.join(q.options)}")
        return "\n".join(lines)

    def _format_objective(self, intent: Objective) -> str:
        lines = [
            f"goal: {intent.goal}",
            f"success: {intent.success_definition}",
        ]
        if intent.constraints:
            lines.append(f"constraints: {', '.join(intent.constraints)}")
        lines.append("")
        lines.append("[decomposer não implementado — próximo passo]")
        return "\n".join(lines)