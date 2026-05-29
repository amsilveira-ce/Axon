from __future__ import annotations

import logging
from pathlib import Path

from axon.config import PAConfig
from axon.llms.ollama_client import OllamaClient
from axon.pa.context.conversation import ConversationHistory
from axon.pa.context.memory import MemoryBank
from axon.pa.decomposer import Decomposer
from axon.pa.intent_extractor import ExtractionTrace, IntentExtractor
from axon.pa.local_pool import LocalResourcePool
from axon.pa.models import AgentState, ClarificationNeeded, Objective, Plan
from axon.pa.resource_cache import ResourceCache

logger = logging.getLogger(__name__)


class PrincipalAgent:
    """
    Orquestrador central do Axon.

    Coordena o ciclo completo:
      1. IntentExtractor  — query → Objective              ✦ ativo
      2. Decomposer       — Objective → Plan (ReWOO)       ✦ ativo
      3. Resolver         — Plan + GatewayAgents → resource_pool
      4. Executor         — Plan + resource_pool → Facts + Failures

    Opera inteiramente em inglês.
    Tradução de/para o idioma do usuário acontece em pa/api.py.

    Resource pool por run:
      LocalResourcePool  → tools locais (MCP stdio, pa_direct)
      ResourceCache      → recursos GA descobertos em runs anteriores
      Resolver           → recursos novos descobertos nesta run (adicionados ao state)
    """

    def __init__(
        self,
        config:       PAConfig,
        sessions_dir: Path | None = None,
        memory_path:  Path | None = None,
        cache_path:   Path | None = None,
        session_id:   str | None  = None,
    ) -> None:
        self.config = config

        self._llm_client = OllamaClient(
            host=config.llm.host,
            model=config.llm.model,
            timeout=config.llm.timeout,
        )

        self._intent_extractor = IntentExtractor(config)
        self._decomposer       = Decomposer(config)
        self.last_trace: ExtractionTrace | None = None

        # paths
        self._sessions_dir = sessions_dir or _default_sessions_dir()
        self._memory_path  = memory_path  or _default_memory_path()
        self._cache_path   = cache_path   or _default_cache_path()

        # Step 1 — LocalResourcePool (MCP stdio, pa_direct)
        local_tools_path = (
            (sessions_dir.parent / "local_tools.json")
            if sessions_dir else _default_local_tools_path()
        )
        self._local_pool = LocalResourcePool.load(local_tools_path)
        logger.info("[PA] local pool — %d tools", len(self._local_pool))

        # Step 2 — ResourceCache (recursos GA de runs anteriores)
        self._resource_cache = ResourceCache.load(self._cache_path)
        logger.info("[PA] resource cache — %d resources", len(self._resource_cache))

        # MemoryBank
        self._memory = MemoryBank.load_or_create(self._memory_path)
        logger.info("[PA] memory — %d entries", len(self._memory.entries))

        # ConversationHistory
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
        """Extrai intenção. Usado pelo chat — não registra no histórico."""
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
        Ponto de entrada one-shot. Executa o pipeline completo.

        Fluxo atual:
          1. IntentExtractor → Objective
          2. AgentState criado e resource_pool populado
          3. Decomposer → Plan
          4. Resolver (pendente)
          5. Executor (pendente)
        """
        self._history.add_message("user", query, llm_client=self._llm_client)

        # 1. IntentExtractor
        intent, trace = self._intent_extractor.extract(
            query,
            history=self._history,
            memory=self._memory,
            resources=self._local_pool.get_capabilities(),
        )
        self.last_trace = trace

        if intent.clarification is not None:
            response = self._format_clarification(intent.clarification)
            self._history.add_message("assistant", response, llm_client=self._llm_client)
            self._persist_session()
            return response

        # Step 3 — cria AgentState e pré-popula resource_pool
        state = AgentState(raw_query=query, objective=intent)
        state.resource_pool = (
            self._local_pool.tools
            + self._resource_cache.all()
        )

        logger.info(
            "[PA] resource_pool — %d resources (%d local, %d cached)",
            len(state.resource_pool),
            len(self._local_pool.tools),
            len(self._resource_cache),
        )

        # Step 4 — Decomposer lê state.objective + state.resource_pool
        #           escreve state.plan
        self._decomposer.decompose(state)

        # 3. Resolver (pendente)
        # self._resolver.resolve(state)

        # 4. Executor (pendente)
        # self._executor.execute(state)
        # response = state.summary

        response = self._format_plan(intent, state.plan)

        self._history.add_message("assistant", response, llm_client=self._llm_client)
        self._persist_session()
        return response

    # ------------------------------------------------------------------
    #   Memory API
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
        """Formata só o Objective — usado pelo chat.py."""
        lines = [
            f"goal: {intent.goal}",
            f"success: {intent.success_definition}",
        ]
        if intent.constraints:
            lines.append(f"constraints: {', '.join(c.value for c in intent.constraints)}")
        return "\n".join(lines)

    def _format_plan(self, intent: Objective, plan: Plan) -> str:
        """Formata Objective + Plan — usado pelo run()."""
        lines = [
            f"goal: {intent.goal}",
            f"success: {intent.success_definition}",
            "",
            f"plan ({len(plan.subtasks)} subtask(s)):",
        ]
        for s in plan.subtasks:
            lines.append(f"  [{s.id}] {s.description}")
            lines.append(f"    capability : {s.capability_required}")
            if s.output_artifact:
                lines.append(f"    output     : {s.output_artifact}")
            if s.depends_on:
                lines.append(f"    depends_on : {', '.join(s.depends_on)}")
        lines.extend(["", "[resolver not implemented — next step]"])
        return "\n".join(lines)


# ---------------------------------------------------------------------------
#   Path helpers
# ---------------------------------------------------------------------------

def _default_sessions_dir() -> Path:
    try:
        from axon.config import paths
        return paths().pa_sessions
    except Exception:
        return Path(".axon/pa/sessions")


def _default_memory_path() -> Path:
    try:
        from axon.config import paths
        return paths().pa_memory_bank
    except Exception:
        return Path(".axon/pa/memory_bank.json")


def _default_cache_path() -> Path:
    try:
        from axon.config import paths
        return paths().pa_resource_cache
    except Exception:
        return Path(".axon/pa/resource_cache.json")


def _default_local_tools_path() -> Path:
    try:
        from axon.config import paths
        return paths().pa_local_tools
    except Exception:
        return Path(".axon/pa/local_tools.json")