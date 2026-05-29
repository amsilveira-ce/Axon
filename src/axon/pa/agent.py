from __future__ import annotations

import logging
from pathlib import Path

from axon.config import PAConfig
from axon.llms.ollama_client import OllamaClient
from axon.pa.context.conversation import ConversationHistory
from axon.pa.context.memory import MemoryBank
from axon.pa.decomposer import Decomposer
from axon.pa.ga_affinity import GAAffinityStore
from axon.pa.planner import Planner, PlanError
from axon.pa.intent_extractor import ExtractionTrace, IntentExtractor
from axon.pa.local_pool import LocalResourcePool
from axon.pa.models import AgentState, ClarificationNeeded, Objective, Plan
from axon.pa.resolver import Resolver, ResolverClarification, ResolverError
from axon.pa.resource_cache import ResourceCache
from axon.pa.executor import Executor, _short
from axon.pa.parameterizer import Parameterizer
from axon.pa.synthesizer import ResponseSynthesizer

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
        self._planner          = Planner()
        self.last_trace: ExtractionTrace | None = None

        # paths
        self._sessions_dir = sessions_dir or _default_sessions_dir()
        self._memory_path  = memory_path  or _default_memory_path()
        self._cache_path   = cache_path   or _default_cache_path()
        self._traces_dir   = (sessions_dir.parent / "traces") if sessions_dir else _default_traces_dir()

        # Step 1 — LocalResourcePool (MCP stdio, pa_direct)
        local_tools_path = (
            (sessions_dir.parent / "local_tools.json")
            if sessions_dir else _default_local_tools_path()
        )
        self._local_pool = LocalResourcePool.load(local_tools_path)
        logger.info("[PA] local pool — %d tools", len(self._local_pool))

        # Step 2 — ResourceCache (recursos GA de runs anteriores) — LRU por cache.max_size
        self._resource_cache = ResourceCache.load(
            self._cache_path, max_size=config.cache.max_size
        )
        logger.info(
            "[PA] resource cache — %d/%d resources",
            len(self._resource_cache), config.cache.max_size,
        )

        # Step 3 — Resolver (discovery via GA + afinidade UCB1 por gateway)
        affinity_path = (
            (sessions_dir.parent / "ga_affinity.json")
            if sessions_dir else _default_affinity_path()
        )
        self._affinity = GAAffinityStore.load(affinity_path)
        self._resolver = Resolver(
            gateways=[g.url for g in config.gateways],
            affinity=self._affinity,
            affinity_path=affinity_path,
            cache=self._resource_cache,
            policy=config.resource_policy,
            min_match_score=config.resource_policy.match_threshold,
        )
        logger.info("[PA] resolver — %d gateway(s) configured", len(config.gateways))

        # Step 4 — Executor (executa o plano; fecha o reward UCB via update_final)
        # Parameterizer re-parametriza via LLM quando os params não batem com o
        # schema da tool (bind-if-mismatch) — compartilha o LLM client do PA.
        self._executor = Executor(
            affinity=self._affinity,
            affinity_path=affinity_path,
            parameterizer=Parameterizer(self._llm_client),
        )

        # Step 5 — ResponseSynthesizer (facts → resposta final; só lê o state)
        self._synthesizer = ResponseSynthesizer(config)

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
        # session_id atrelado à conversa → traces correlacionáveis por sessão
        state = AgentState(raw_query=query, objective=intent, session_id=self.session_id)
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
        try:
            self._decomposer.decompose(state)
        except Exception as exc:
            logger.error("[PA] decomposer raised: %s", exc)
            response = (
                f"I was unable to decompose your request into steps.\n"
                f"Reason: {exc}\n\n"
                f"Please rephrase your query and try again."
            )
            self._history.add_message("assistant", response, llm_client=self._llm_client)
            self._persist_session()
            return response

        # detecta plano fallback — subtask com status FAILED
        if _is_fallback_plan(state.plan):
            reason = state.plan.subtasks[0].description if state.plan.subtasks else "unknown"
            logger.warning("[PA] decomposer returned fallback plan — %s", reason)
            response = (
                f"I was unable to break down your request into executable steps.\n\n"
                f"{reason}\n\n"
                f"Suggestions:\n"
                f"  - Be more specific about what you want to achieve\n"
                f"  - Break the request into smaller parts\n"
                f"  - Check if the required capabilities are available (axon pa tools list)"
            )
            self._history.add_message("assistant", response, llm_client=self._llm_client)
            self._persist_session()
            return response

        # Step 5 — Planner lê state.plan.subtasks
        #           resolve depends_on, valida, ordena
        #           escreve state.plan + state.progress
        try:
            self._planner.plan(state)
        except PlanError as exc:
            logger.error("[PA] planner raised: %s", exc)
            response = (
                f"The execution plan is inconsistent and cannot be scheduled.\n"
                f"Reason: {exc}\n\n"
                f"Please rephrase your query and try again."
            )
            self._history.add_message("assistant", response, llm_client=self._llm_client)
            self._persist_session()
            return response

        # Step 6 — Resolver: atribui um recurso a cada subtask
        #           (local pool → Gateway Agent via UCB1)
        try:
            self._resolver.resolve(state)
        except ResolverClarification as clar:
            # fallback_strategy=ask_user — devolve pergunta ao usuário,
            # mesmo caminho que o IntentExtractor usa para esclarecimento.
            logger.info("[PA] resolver needs clarification: %s", clar)
            response = self._format_clarification(clar.clarification)
            self._history.add_message("assistant", response, llm_client=self._llm_client)
            self._persist_session()
            return response
        except ResolverError as exc:
            logger.error("[PA] resolver raised: %s", exc)
            response = (
                f"I couldn't find a resource to perform part of your request.\n\n"
                f"{exc}"
            )
            self._history.add_message("assistant", response, llm_client=self._llm_client)
            self._persist_session()
            return response

        # Step 7 — Executor: executa cada subtask resolvida (Fact/Failure + reward)
        try:
            self._executor.execute(state)
        except Exception as exc:
            logger.error("[PA] executor raised: %s", exc, exc_info=True)
            self._persist_trace(state)   # salva o que houver, mesmo parcial
            response = (
                f"An error interrupted execution of your request.\n\n{exc}"
            )
            self._history.add_message("assistant", response, llm_client=self._llm_client)
            self._persist_session()
            return response

        self._persist_trace(state)

        # Step 8 — ResponseSynthesizer: facts + contexto → resposta em linguagem
        # natural. Fallback para o resumo estruturado se a síntese falhar.
        try:
            response = self._synthesizer.synthesize(state, self._history)
            if not response:
                response = self._format_result(intent, state)
        except Exception as exc:
            logger.warning("[PA] synthesizer failed (%s) — using structured result", exc)
            response = self._format_result(intent, state)

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

    def _format_result(self, intent: Objective, state: AgentState) -> str:
        """Formata o resultado da run executada — usado pelo run()."""
        plan = state.plan
        lines = [
            f"goal: {intent.goal}",
            f"success: {intent.success_definition}",
            "",
            f"plan ({len(plan.subtasks)} subtask(s)):",
        ]
        for s in plan.subtasks:
            status = state.progress.get(s.id)
            status_label = status.value if status else "pending"
            lines.append(f"  [{s.id}] {s.description}  [{status_label}]")
            lines.append(f"    capability : {s.capability_required}")

            assignment = state.resource_assignments.get(s.id)
            if assignment is not None:
                via = f"GA {assignment.ga_url}" if assignment.ga_url else "local pool"
                lines.append(f"    resource   : {assignment.manifest.name} (via {via})")

            fact = state.get_fact(s.id)
            if fact is not None:
                lines.append(f"    output     : {_short(fact.output)}")
            else:
                fails = [f for f in state.failures if f.subtask_id == s.id]
                if fails:
                    lines.append(f"    error      : {fails[-1].reason}")

        b = state.budget
        lines.extend([
            "",
            f"budget: tokens {b.tokens_used}/{b.tokens_max} · "
            f"calls {b.calls_used}/{b.calls_max} · elapsed {b.elapsed_ms / 1000:.1f}s",
            "",
            f"inspect: axon pa inspect --session {state.session_id}",
        ])
        return "\n".join(lines)

    def _persist_trace(self, state: AgentState) -> None:
        """Salva o AgentState em {traces}/{session_id}/{request_id}.json."""
        try:
            trace_dir = self._traces_dir / state.session_id
            trace_dir.mkdir(parents=True, exist_ok=True)
            path = trace_dir / f"{state.request_id}.json"
            path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
            logger.info("[PA] trace saved → %s", path)
        except Exception as e:
            logger.warning("[PA] failed to persist trace: %s", e)


# ---------------------------------------------------------------------------
#   Plan helpers
# ---------------------------------------------------------------------------

def _is_fallback_plan(plan: "Plan") -> bool:
    """
    Detecta se o Decomposer retornou um plano fallback.
    Planos fallback têm exactamente 1 subtask com id="subtask-fallback"
    e status=FAILED.
    """
    from axon.pa.models import SubtaskStatus
    return (
        len(plan.subtasks) == 1
        and plan.subtasks[0].id == "subtask-fallback"
        and plan.subtasks[0].status == SubtaskStatus.FAILED
    )


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


def _default_affinity_path() -> Path:
    try:
        from axon.config import paths
        return paths().pa_ga_affinity
    except Exception:
        return Path(".axon/pa/ga_affinity.json")


def _default_traces_dir() -> Path:
    try:
        from axon.config import paths
        return paths().pa_traces
    except Exception:
        return Path(".axon/pa/traces")