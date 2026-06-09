"""Principal Agent — orchestrator for the Axon pipeline.

``PrincipalAgent`` coordinates a six-stage pipeline that turns a raw user
query into a grounded, executable response:

    1. IntentExtractor      — query → Objective
    2. Decomposer           — Objective → Plan (subtasks)
    3. Planner              — Plan → validated, dependency-ordered Plan
    4. Resolver             — Plan + Gateway Agents → resource assignments
    5. Executor             — resource assignments → Facts + Failures
    6. ResponseSynthesizer  — Facts → natural-language response

The agent operates entirely in English.  Language translation is the
caller's responsibility (see ``axon.cli.pa.run`` and ``axon.pa.api``).
"""

from __future__ import annotations

import logging
from pathlib import Path

from axon.config import AxonPaths, PAConfig
from axon.llms.ollama_client import OllamaClient
from axon.pa.context.conversation import ConversationHistory
from axon.pa.context.memory import MemoryBank
from axon.pa.decomposer import Decomposer
from axon.pa.ga_affinity import GAAffinityStore
from axon.pa.planner import Planner, PlanError
from axon.pa.intent_extractor import ExtractionTrace, IntentExtractor
from axon.pa.local_pool import LocalResourcePool
from axon.pa.local_mcp_session import LocalMCPSession, LocalMCPSessionError
from axon.pa.models import (
    AgentState,
    ClarificationNeeded,
    Objective,
    Plan,
    SubtaskStatus,
)
from axon.pa.resolver import Resolver, ResolverClarification, ResolverError
from axon.pa.resource_cache import ResourceCache
from axon.pa.executor import Executor, _short
from axon.pa.parameterizer import Parameterizer
from axon.pa.synthesizer import ResponseSynthesizer

logger = logging.getLogger(__name__)


class PrincipalAgent:
    """Orchestrator for the Axon Principal Agent pipeline.

    Coordinates a six-stage pipeline from raw user query to natural-language
    response.  All stages communicate through a shared ``AgentState`` object
    created at the start of each ``run()`` call.

    The resource pool for each run is assembled from three sources:
    ``LocalResourcePool`` (local MCP tools), ``ResourceCache`` (GA resources
    discovered in previous runs), and the ``Resolver`` (newly discovered
    resources in this run).

    Attributes:
        config: PAConfig used for this agent instance.
        last_trace: ExtractionTrace from the most recent ``run()`` or
            ``extract_intent()`` call; ``None`` before the first call.
        last_state: AgentState from the most recent ``run()``; ``None``
            before the first call or when clarification was returned.
    """

    def __init__(
        self,
        config: PAConfig,
        sessions_dir: Path | None = None,
        memory_path: Path | None = None,
        cache_path: Path | None = None,
        session_id: str | None = None,
    ) -> None:
        self.config = config
        self.last_trace: ExtractionTrace | None = None
        self.last_state: AgentState | None = None

        self._llm_client = OllamaClient(
            host=config.llm.host,
            model=config.llm.model,
            timeout=config.llm.timeout,
        )
        self._intent_extractor = IntentExtractor(config)
        self._decomposer = Decomposer(config)
        self._planner = Planner()

        # Resolve all filesystem paths from sessions_dir or config defaults.
        p = _pa_paths(sessions_dir)
        self._sessions_dir = p.pa_sessions
        self._traces_dir = p.pa_traces

        # Local tool pool — loaded from the manifest JSON.
        self._local_pool = LocalResourcePool.load(p.pa_local_tools)
        logger.info("[PA] local pool — %d tools", len(self._local_pool))

        # Single shared stdio MCP connection for all local tools.
        # Falls back to per-call subprocess when no stdio tools are present.
        self._local_session: LocalMCPSession | None = None
        stdio_tools = [m for m in self._local_pool.tools if m.command]
        if stdio_tools:
            try:
                self._local_session = LocalMCPSession(stdio_tools).__enter__()
                logger.info("[PA] local MCP session connected")
            except LocalMCPSessionError as exc:
                logger.warning(
                    "[PA] local MCP session failed to start (%s) — "
                    "falling back to per-call subprocess",
                    exc,
                )

        # Resource cache — GA manifests discovered in previous runs (LRU).
        self._resource_cache = ResourceCache.load(
            cache_path or p.pa_resource_cache, max_size=config.cache.max_size
        )
        logger.info(
            "[PA] resource cache — %d/%d resources",
            len(self._resource_cache), config.cache.max_size,
        )

        # Affinity, Resolver, and Executor share the same object and path.
        # Exposed as self._affinity so callers can read UCB scores after a run.
        self._affinity = GAAffinityStore.load(p.pa_ga_affinity)
        self._resolver = Resolver(
            gateways=[g.url for g in config.gateways],
            affinity=self._affinity,
            affinity_path=p.pa_ga_affinity,
            cache=self._resource_cache,
            policy=config.resource_policy,
            min_match_score=config.resource_policy.match_threshold,
        )
        self._executor = Executor(
            affinity=self._affinity,
            affinity_path=p.pa_ga_affinity,
            parameterizer=Parameterizer(self._llm_client),
            local_session=self._local_session,
        )

        self._synthesizer = ResponseSynthesizer(config)

        self._memory = MemoryBank.load_or_create(memory_path or p.pa_memory_bank)
        logger.info("[PA] memory — %d entries", len(self._memory.entries))

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


    # ── lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the local MCP session (subprocess + event-loop thread)."""
        if self._local_session is not None:
            self._local_session.__exit__(None, None, None)
            self._local_session = None
            logger.info("[PA] local MCP session closed")

    def __enter__(self) -> "PrincipalAgent":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ── public API ────────────────────────────────────────────────────────────

    @property
    def session_id(self) -> str:
        return self._history.session_id

    def extract_intent(self, query: str) -> Objective:
        """Extract intent without recording the query in conversation history.

        Used by the interactive chat loop, which manages history separately.
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
        """Execute the full pipeline for a one-shot query.

        Runs all six stages in sequence, collecting ``Facts`` and ``Failures``
        in ``AgentState``.  Returns a natural-language response string in all
        cases, including clarification requests and pipeline errors.
        """

        self._history.add_message("user", query, llm_client=self._llm_client)

        # Stage 1 — intent extraction
        intent, trace = self._intent_extractor.extract(
            query,
            history=self._history,
            memory=self._memory,
            resources=self._local_pool.get_capabilities(),
        )

        self.last_trace = trace

        if intent.clarification is not None:
            return self._respond_clarification(intent.clarification)

        # Initialise AgentState and expose it early so --verbose can read partial state.
        state = AgentState(raw_query=query, objective=intent, session_id=self.session_id)
        state.resource_pool = self._local_pool.tools + self._resource_cache.all()
        self.last_state = state

        logger.info(
            "[PA] resource pool — %d resources (%d local, %d cached)",
            len(state.resource_pool),
            len(self._local_pool.tools),
            len(self._resource_cache),
        )

        # Stage 2 — decompose objective into subtasks
        try:
            self._decomposer.decompose(state)
        except Exception as exc:
            logger.error("[PA] decomposer: %s", exc)
            return self._respond(
                f"I was unable to decompose your request into steps.\n"
                f"Reason: {exc}\n\n"
                f"Please rephrase your query and try again."
            )

        if _is_fallback_plan(state.plan):
            reason = state.plan.subtasks[0].description if state.plan.subtasks else "unknown"
            logger.warning("[PA] decomposer returned fallback plan — %s", reason)
            return self._respond(
                f"I was unable to break down your request into executable steps.\n\n"
                f"{reason}\n\n"
                f"Suggestions:\n"
                f"  - Be more specific about what you want to achieve\n"
                f"  - Break the request into smaller parts\n"
                f"  - Check if the required capabilities are available (axon pa tools list)"
            )

        # Stage 3 — validate and dependency-order the plan
        try:
            self._planner.plan(state)
        except PlanError as exc:
            logger.error("[PA] planner: %s", exc)
            return self._respond(
                f"The execution plan is inconsistent and cannot be scheduled.\n"
                f"Reason: {exc}\n\n"
                f"Please rephrase your query and try again."
            )

        # Stage 4 — resolve capabilities to resources
        try:
            self._resolver.resolve(state)
        except ResolverClarification as clar:
            logger.info("[PA] resolver needs clarification: %s", clar)
            return self._respond_clarification(clar.clarification)
        except ResolverError as exc:
            logger.error("[PA] resolver: %s", exc)
            return self._respond(
                f"I couldn't find a resource to perform part of your request.\n\n{exc}"
            )

        # Stage 5 — execute the plan
        try:
            self._executor.execute(state)
        except Exception as exc:
            logger.error("[PA] executor: %s", exc, exc_info=True)
            self._persist_trace(state)
            return self._respond(
                f"An error interrupted execution of your request.\n\n{exc}"
            )

        self._persist_trace(state)

        # Stage 6 — synthesize natural-language response
        try:
            response = self._synthesizer.synthesize(state, self._history)
            if not response:
                response = self._format_result(intent, state)
        except Exception as exc:
            logger.warning("[PA] synthesizer failed (%s) — using structured fallback", exc)
            response = self._format_result(intent, state)

        return self._respond(response)

    # ── private helpers ───────────────────────────────────────────────────────

    def _respond(self, message: str) -> str:
        """Record *message* as an assistant turn, persist the session, and return it."""
        self._history.add_message("assistant", message, llm_client=self._llm_client)
        self._persist_session()
        return message

    def _respond_clarification(self, clarification: ClarificationNeeded) -> str:
        return self._respond(self._format_clarification(clarification))

    def _persist_session(self) -> None:
        try:
            self._history.persist(self._sessions_dir)
        except Exception as exc:
            logger.warning("[PA] failed to persist session: %s", exc)

    def _persist_trace(self, state: AgentState) -> None:
        """Write AgentState to ``{traces}/{session_id}/{request_id}.json``."""
        try:
            trace_dir = self._traces_dir / state.session_id
            trace_dir.mkdir(parents=True, exist_ok=True)
            path = trace_dir / f"{state.request_id}.json"
            path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
            logger.info("[PA] trace saved → %s", path)
        except Exception as exc:
            logger.warning("[PA] failed to persist trace: %s", exc)

    def _format_clarification(self, clarification: ClarificationNeeded) -> str:
        lines = [clarification.context, ""]
        for i, q in enumerate(clarification.questions, 1):
            lines.append(f"{i}. {q.question}")
            if q.options:
                lines.append(f"   options: {', '.join(q.options)}")
        return "\n".join(lines)

    def _format_objective(self, intent: Objective) -> str:
        """Format an Objective for display — used by the interactive chat loop."""
        lines = [
            f"goal: {intent.goal}",
            f"success: {intent.success_definition}",
        ]
        if intent.constraints:
            lines.append(f"constraints: {', '.join(c.value for c in intent.constraints)}")
        return "\n".join(lines)

    def _format_result(self, intent: Objective, state: AgentState) -> str:
        """Format the structured run result — fallback when synthesis fails."""
        plan = state.plan
        lines = [
            f"goal: {intent.goal}",
            f"success: {intent.success_definition}",
            "",
            f"plan ({len(plan.subtasks)} subtask(s)):",
        ]
        for s in plan.subtasks:
            status = state.progress.get(s.id)
            lines.append(
                f"  [{s.id}] {s.description}  [{status.value if status else 'pending'}]"
            )
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


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _is_fallback_plan(plan: Plan) -> bool:
    """Return ``True`` if the Decomposer returned a single-subtask error plan."""
    return (
        len(plan.subtasks) == 1
        and plan.subtasks[0].id == "subtask-fallback"
        and plan.subtasks[0].status == SubtaskStatus.FAILED
    )


def _pa_paths(sessions_dir: Path | None) -> AxonPaths:
    """Return ``AxonPaths`` derived from *sessions_dir* or the config file.

    When *sessions_dir* is provided the root is inferred as
    ``sessions_dir.parent.parent`` (i.e. ``.axon/pa/sessions`` → ``.axon``).
    Falls back to ``.axon`` when the config file is not found.
    """
    if sessions_dir is not None:
        return AxonPaths(sessions_dir.parent.parent)
    try:
        from axon.config import paths
        return paths()
    except Exception:
        return AxonPaths(Path(".axon"))
