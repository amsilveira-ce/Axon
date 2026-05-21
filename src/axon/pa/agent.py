from __future__ import annotations

import logging
from pathlib import Path

from axon.config import PAConfig
from axon.llms.ollama_client import OllamaClient
from axon.pa.context.conversation import ConversationHistory
from axon.pa.local_pool import LocalResourcePool
from axon.pa.context.memory import MemoryBank
from axon.pa.intent_extractor import IntentExtractor, ExtractionTrace
from axon.pa.models import ClarificationNeeded, Objective

logger = logging.getLogger(__name__)


class PrincipalAgent:
    """
    Orquestrador central do Axon.

    Coordena o ciclo completo:
      1. IntentExtractor  — query → Objective              ✦ ativo
      2. Decomposer       — Objective → list[Subtask]
      3. Planner          — list[Subtask] → Plan (DAG)
      4. Resolver         — Plan + GatewayAgents → resource_pool
      5. Executor         — Plan + resource_pool → Facts + Failures

    Opera inteiramente em inglês.
    Tradução de/para o idioma do usuário acontece em pa/api.py.

    Context Layer:
      ConversationHistory — histórico da sessão atual, janela deslizante
      MemoryBank          — preferências cross-session, carregadas no startup
    """

    def __init__(
        self,
        config:       PAConfig,
        sessions_dir: Path | None = None,
        memory_path:  Path | None = None,
        session_id:   str | None  = None,
    ) -> None:
        self.config = config

        # cliente LLM compartilhado — IntentExtractor + summarizer + tradução
        self._llm_client = OllamaClient(
            host=config.llm.host,
            model=config.llm.model,
            timeout=config.llm.timeout,
        )

        self._intent_extractor = IntentExtractor(config)
        self.last_trace: ExtractionTrace | None = None
        

        # context layer — paths resolvidos pelo caller (api.py / cli)
        # ou derivados do cwd como fallback
        self._sessions_dir = sessions_dir or _default_sessions_dir()
        self._memory_path  = memory_path  or _default_memory_path()

        # LocalResourcePool — tools locais, carregadas no startup
        local_tools_path  = (sessions_dir.parent / 'local_tools.json') if sessions_dir else _default_local_tools_path()
        self._local_pool  = LocalResourcePool.load(local_tools_path)
        logger.info('[PA] local pool loaded — %d tools', len(self._local_pool))

        # MemoryBank — carregado uma vez no startup, persiste entre sessões
        self._memory = MemoryBank.load_or_create(self._memory_path)
        logger.info(
            "[PA] memory loaded — %d entries", len(self._memory.entries)
        )

        # ConversationHistory — carregada ou criada para esta sessão
        self._history = ConversationHistory.load_or_create(
            session_id=session_id,
            sessions_dir=self._sessions_dir,
            config=config.conversation,
        )
        logger.info(
            "[PA] session=%s messages=%d",
            self._history.session_id,
            len(self._history.messages),
        )

    # ------------------------------------------------------------------
    #   API pública
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> str:
        return self._history.session_id

    def extract_intent(self, query: str) -> Objective:
        """
        Extrai intenção passando contexto real de memória e histórico.
        Usado pelo chat interativo — não registra o turno no histórico.
        """
        intent, trace = self._intent_extractor.extract(
            query,
            history=self._history,
            memory=self._memory,
            resources=self._local_pool.get_capabilities(),
        )
        self.last_trace = trace
        return intent

    def run(self, query: str) -> str:
        """
        Ponto de entrada síncrono para one-shot (axon pa run / POST /run).

        Registra o turno no histórico e persiste a sessão.

        Args:
            query: query em inglês (já traduzida pelo endpoint se necessário)

        Returns:
            str — resposta em inglês (endpoint traduz de volta se necessário)
        """
        # registra turno do usuário
        self._history.add_message(
            "user", query, llm_client=self._llm_client
        )

        intent, trace = self._intent_extractor.extract(
            query,
            history=self._history,
            memory=self._memory,
            resources=self._local_pool.get_capabilities(),
        )
        self.last_trace = trace

        if intent.clarification is not None:
            response = self._format_clarification(intent.clarification)
        else:
            # 2. decompor objetivo em subtarefas
            # subtasks = self._decomposer.decompose(intent)

            # 3. montar plano (DAG)
            # plan = self._planner.plan(subtasks)

            # 4. resolver recursos via Gateway Agents
            # resource_pool = self._resolver.resolve(plan)

            # 5. executar plano
            # result = self._executor.execute(plan, resource_pool)

            # 6. retornar resposta final
            # response = result.summary

            response = self._format_objective(intent)

        # registra resposta do assistente e persiste
        self._history.add_message(
            "assistant", response, llm_client=self._llm_client
        )
        self._persist_session()

        return response

    # ------------------------------------------------------------------
    #   Memory API — exposta para axon pa memory (futuro)
    # ------------------------------------------------------------------

    def memory_set(self, key: str, value: object, source: str = "operator") -> None:
        self._memory.set(key, value, source=source)
        self._memory.persist(self._memory_path)

    def memory_get(self, key: str, default: object = None) -> object:
        return self._memory.get(key, default)

    def memory_delete(self, key: str) -> bool:
        result = self._memory.delete(key)
        if result:
            self._memory.persist(self._memory_path)
        return result

    def memory_summary(self) -> str:
        return self._memory.get_summary()

    # ------------------------------------------------------------------
    #   Internals
    # ------------------------------------------------------------------

    def _persist_session(self) -> None:
        try:
            self._history.persist(self._sessions_dir)
        except Exception as e:
            logger.warning("[PA] failed to persist session: %s", e)

    def _format_clarification(self, intent: ClarificationNeeded) -> str:
        lines = [intent.context, ""]
        for i, q in enumerate(intent.questions, 1):
            lines.append(f"{i}. {q.question}")
            if q.options:
                lines.append(f"   options: {', '.join(q.options)}")
        return "\n".join(lines)

    def _format_objective(self, intent: Objective) -> str:
        lines = [
            f"goal: {intent.goal}",
            f"success: {intent.success_definition}",
        ]
        if intent.constraints:
            lines.append(
                f"constraints: {', '.join(c.value for c in intent.constraints)}"
            )
        lines.append("")
        lines.append("[decomposer not implemented — next step]")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
#   Path helpers
# ---------------------------------------------------------------------------

def _default_sessions_dir() -> Path:
    """Fallback quando o caller não passa sessions_dir — usa paths() do cwd."""
    try:
        from axon.config import paths
        return paths().pa_sessions
    except Exception:
        return Path(".axon/pa/sessions")


def _default_memory_path() -> Path:
    """Fallback quando o caller não passa memory_path — usa paths() do cwd."""
    try:
        from axon.config import paths
        return paths().pa_memory_bank
    except Exception:
        return Path(".axon/pa/memory_bank.json")


def _default_local_tools_path() -> Path:
    try:
        from axon.config import paths
        return paths().pa_local_tools
    except Exception:
        return Path(".axon/pa/local_tools.json")