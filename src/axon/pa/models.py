"""Data models for the Principal Agent pipeline.

Each stage of the pipeline owns a specific slice of ``AgentState``:

    IntentExtractor  → objective
    Decomposer       → plan
    Resolver         → resource_assignments
    Executor         → facts, failures, progress, scratchpad
    BudgetGuard      → budget
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from axon.types import ResourceManifest


# ---------------------------------------------------------------------------
# Intent extraction
# ---------------------------------------------------------------------------


class Constraint(BaseModel):
    """A single restriction on how a task must be executed.

    Constraints narrow the solution space without changing the goal itself.
    The LLM populates these from explicit or implicit signals in the user query.

    Attributes:
        value: Human-readable description of the restriction.
        type: Category of the restriction.
        implicit: ``True`` when inferred rather than stated explicitly.
        source: Exact phrase from the query that triggered this constraint.
    """

    value: str
    type: Literal["temporal", "size", "policy", "format"]
    implicit: bool = False
    source: str = ""


class ClarificationQuestion(BaseModel):
    """A single question targeting one ambiguous span in the user query.

    Attributes:
        question: Specific question for the user.
        ambiguous_span: Exact phrase from the query that triggered the question.
        options: Suggested answers, or ``None`` when open-ended.
    """

    question: str
    ambiguous_span: str
    options: list[str] | None = None


class ClarificationNeeded(BaseModel):
    """Signals that the IntentExtractor cannot produce a complete Objective.

    Returned when the query is too ambiguous to decompose safely.
    The pipeline pauses and asks the user to answer ``questions`` before
    proceeding.

    Attributes:
        questions: One to three questions, each targeting a distinct gap.
        context: One sentence summarising what the extractor already understood.
    """

    questions: list[ClarificationQuestion]
    context: str


class Objective(BaseModel):
    """Structured representation of what the user wants to accomplish.

    Produced by ``IntentExtractor`` and consumed by ``Decomposer``.

    When ``clarification`` is ``None`` the objective is complete and the
    pipeline continues.  When it is set, the agent must ask the user the
    listed questions before proceeding.

    Attributes:
        goal: Full verb-phrase describing the desired outcome.
        constraints: Restrictions on how the task must be executed.
        success_definition: Verifiable condition that means the task is done.
        extracted_inputs: Values explicitly stated in the query (slots).
        assumptions: Sensible defaults the extractor applied to proceed.
        clarification: Set when the query is too ambiguous to proceed.
    """

    goal: str
    constraints: list[Constraint] = Field(default_factory=list)
    success_definition: str = ""
    extracted_inputs: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    clarification: ClarificationNeeded | None = None

    # -- constraint helpers --------------------------------------------------

    def get_constraints(
        self,
        type: Literal["temporal", "size", "policy", "format"] | None = None,
    ) -> list[Constraint]:
        """Return all constraints, optionally filtered by *type*."""
        if type is None:
            return self.constraints
        return [c for c in self.constraints if c.type == type]

    def has_constraint(
        self,
        type: Literal["temporal", "size", "policy", "format"],
    ) -> bool:
        """Return ``True`` if at least one constraint of *type* exists."""
        return any(c.type == type for c in self.constraints)

    def constraints_summary(self) -> str:
        """Return a one-liner of all constraints for logging and prompts.

        Returns an empty string when there are no constraints.
        """
        if not self.constraints:
            return ""
        return "; ".join(f"[{c.type}] {c.value}" for c in self.constraints)

    # -- readiness -----------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        """``True`` when the objective is complete and can go to the Decomposer."""
        return bool(self.goal) and self.clarification is None


# Alias kept for backwards compatibility with agent.py and chat.py.
IntentResult = Objective


class ExtractionTrace:
    """Context snapshot produced alongside every ``Objective``.

    Carries the rendered context that was injected into the LLM prompt so
    the ``--verbose`` CLI flag can show exactly what the agent saw.

    Attributes:
        objective: The extracted (or partial) objective.
        context: Full rendered prompt context passed to the LLM.
        history_str: Rendered conversation history section.
        memory_str: Rendered memory bank section.
        resources_str: Rendered available resources section.
    """

    def __init__(
        self,
        objective: Objective,
        context: str,
        history_str: str,
        memory_str: str,
        resources_str: str,
    ) -> None:
        self.objective = objective
        self.context = context
        self.history_str = history_str
        self.memory_str = memory_str
        self.resources_str = resources_str


# ---------------------------------------------------------------------------
# Execution enums
# ---------------------------------------------------------------------------


class ExecutionStrategy(str, Enum):
    """Strategy used by the Executor to run a subtask."""

    REACT = "react"
    REWOO = "rewoo"


class SubtaskStatus(str, Enum):
    """Lifecycle status of a single subtask."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Provenance(str, Enum):
    """Origin of the resource that produced a ``Fact``."""

    A2A = "a2a"
    MCP = "mcp"
    LOCAL = "local"


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


class Subtask(BaseModel):
    """Smallest unit of work in a plan — delegatable to a single resource.

    Input and output are declared via named artifacts so the Executor can
    wire data between steps without reasoning about dependencies at runtime.

    ``params_template`` usage by strategy:

    - **ReAct**: empty — the Executor decides parameters at runtime.
    - **ReWOO**: fully populated — uses ``{{artifact:name}}`` placeholders
      to reference outputs from earlier subtasks.

    Attributes:
        id: Unique identifier within the plan.
        description: Human-readable description of what this subtask does.
        capability_required: Capability tag used by the Resolver to find a
            matching resource.
        input_artifacts: Names of artifacts this subtask reads.
        output_artifact: Name of the artifact this subtask produces.
        params_template: Parameters passed to the resource at execution time.
        execution_strategy: Whether this subtask uses ReAct or ReWOO.
        depends_on: IDs of subtasks that must complete before this one runs.
        is_optional: When ``True``, failure does not block plan completion.
        status: Current lifecycle status.
    """

    id: str
    description: str
    capability_required: str

    input_artifacts: list[str] = Field(default_factory=list)
    output_artifact: str | None = None
    params_template: dict[str, Any] = Field(default_factory=dict)

    execution_strategy: ExecutionStrategy = ExecutionStrategy.REWOO
    depends_on: list[str] = Field(default_factory=list)
    is_optional: bool = False
    status: SubtaskStatus = SubtaskStatus.PENDING


class Plan(BaseModel):
    """Ordered list of subtasks produced by the Decomposer and refined by the Planner.

    ``depends_on`` fields on each ``Subtask`` are resolved by the Planner
    through artifact-name matching before execution begins.
    """

    subtasks: list[Subtask] = Field(default_factory=list)


class ResolverResult(BaseModel):
    """Resource assignment for a single subtask, produced by the Resolver.

    Carries the best-matching resource manifest plus fallbacks, and the
    signals used to update the UCB1 affinity model in ``GAAffinityStore``.

    Attributes:
        capability: Capability tag that was resolved.
        subtask_id: ID of the subtask this result belongs to.
        manifest: Best-matching resource manifest.
        alternatives: Fallback manifests in descending match order.
        ga_url: Gateway Agent URL this result came from (empty for local pool).
        match_score: Similarity score in [0, 1] — fed to ``GAAffinityStore``.
        latency_ms: Round-trip latency to the GA — fed to ``GAAffinityStore``.
    """

    capability: str
    subtask_id: str
    manifest: ResourceManifest
    alternatives: list[ResourceManifest] = Field(default_factory=list)
    ga_url: str
    match_score: float = 0.0
    latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# Execution records (append-only)
# ---------------------------------------------------------------------------


class Fact(BaseModel):
    """Successful output of a subtask.

    Append-only — never modified after creation.

    Attributes:
        subtask_id: ID of the subtask that produced this fact.
        tool: Name of the resource or tool that was called.
        output: Raw output returned by the tool.
        provenance: Whether the tool was reached via A2A, MCP, or local.
        timestamp: UTC time of creation.
    """

    subtask_id: str
    tool: str
    output: Any
    provenance: Provenance
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Failure(BaseModel):
    """Failed execution record for a subtask.

    Append-only — never modified after creation.

    Attributes:
        subtask_id: ID of the subtask that failed.
        tool: Name of the resource that was called, or ``None`` if the
            failure occurred before a resource was reached.
        error: Raw exception or error message.
        reason: Human-readable explanation of why it failed.
        timestamp: UTC time of creation.
    """

    subtask_id: str
    tool: str | None
    error: str
    reason: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScratchpadEntry(BaseModel):
    """One iteration of the execution loop, stored for traceability.

    - **ReAct**: ``reason`` + ``action`` + ``observation`` (full chain-of-thought).
    - **ReWOO**: ``action`` + ``observation`` only — reasoning happens upfront.

    Attributes:
        step: 1-based sequence number within the run.
        subtask_id: ID of the subtask being executed.
        reason: LLM reasoning text (empty for ReWOO).
        action: Tool call or decision taken.
        observation: Result or observation after the action.
        timestamp: UTC time of creation.
    """

    step: int
    subtask_id: str
    reason: str = ""
    action: str
    observation: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


class Budget(BaseModel):
    """Resource consumption tracker for a single run.

    Read and updated by ``BudgetGuard`` before every LLM call and tool call.
    Limits are copied from ``PAConfig.budget`` at the start of the run.

    Attributes:
        tokens_used: Total tokens consumed so far.
        cost_usd: Total cost in USD so far.
        calls_used: Number of LLM or tool calls made so far.
        elapsed_ms: Wall-clock time elapsed since the run started.
        tokens_max: Hard token limit for the run.
        cost_max_usd: Hard cost limit for the run.
        calls_max: Hard call-count limit for the run.
        timeout_ms: Hard wall-clock timeout for the run.
    """

    tokens_used: int = 0
    cost_usd: float = 0.0
    calls_used: int = 0
    elapsed_ms: float = 0.0

    tokens_max: int = 60_000
    cost_max_usd: float = 0.50
    calls_max: int = 40
    timeout_ms: float = 120_000.0

    def is_exceeded(self) -> bool:
        """Return ``True`` if any limit has been reached."""
        return (
            self.tokens_used >= self.tokens_max
            or self.cost_usd >= self.cost_max_usd
            or self.calls_used >= self.calls_max
            or self.elapsed_ms >= self.timeout_ms
        )

    def remaining_tokens(self) -> int:
        """Return tokens remaining before the hard limit is hit."""
        return max(0, self.tokens_max - self.tokens_used)


# ---------------------------------------------------------------------------
# AgentState — central run object
# ---------------------------------------------------------------------------


class AgentState(BaseModel):
    """Central mutable object representing one Principal Agent run.

    Created by ``agent.py`` when a query is received and passed through every
    pipeline stage.  Each stage owns a specific slice (see module docstring).

    Persisted to ``.axon/pa/traces/{session_id}/{request_id}.json`` at the
    end of the run.

    Attributes:
        session_id: Identifies the conversation session (first 12 chars of a UUID).
        request_id: Identifies this specific run within the session.
        created_at: UTC timestamp of run creation.
        raw_query: Original user query string.
        objective: Structured intent, set by ``IntentExtractor``.
        plan: Ordered subtask list, set by ``Decomposer`` + ``Planner``.
        resource_pool: Available resources; pre-populated from ``LocalResourcePool``
            and ``ResourceCache``, then extended by the ``Resolver``.
        facts: Successful subtask outputs (append-only).
        failures: Failed subtask records (append-only).
        progress: Mapping of ``subtask_id`` → ``SubtaskStatus``.
        scratchpad: Ordered log of every execution iteration.
        budget: Live resource consumption counters.
        tool_cache: Deduplication cache keyed by ``"tool:params_hash"``.
        resource_assignments: Mapping of ``subtask_id`` → ``ResolverResult``.
    """

    # traceability
    session_id: str = Field(default_factory=lambda: str(uuid4())[:12])
    request_id: str = Field(default_factory=lambda: str(uuid4())[:8])
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # input
    raw_query: str = ""

    # pipeline stages
    objective: Objective | None = None
    plan: Plan = Field(default_factory=Plan)
    resource_pool: list[ResourceManifest] = Field(default_factory=list)

    # execution records (append-only)
    facts: list[Fact] = Field(default_factory=list)
    failures: list[Failure] = Field(default_factory=list)

    # runtime state
    progress: dict[str, SubtaskStatus] = Field(default_factory=dict)
    scratchpad: list[ScratchpadEntry] = Field(default_factory=list)
    budget: Budget = Field(default_factory=Budget)
    tool_cache: dict[str, Any] = Field(default_factory=dict)
    resource_assignments: dict[str, ResolverResult] = Field(default_factory=dict)

    # -- helpers -------------------------------------------------------------

    def append_step(
        self,
        subtask_id: str,
        action: str,
        observation: str,
        reason: str = "",
    ) -> None:
        """Append one iteration to the scratchpad.

        Args:
            subtask_id: ID of the subtask being executed.
            action: Tool call or decision taken this step.
            observation: Result received after the action.
            reason: LLM chain-of-thought (empty for ReWOO, populated for ReAct).
        """
        self.scratchpad.append(
            ScratchpadEntry(
                step=len(self.scratchpad) + 1,
                subtask_id=subtask_id,
                action=action,
                observation=observation,
                reason=reason,
            )
        )

    def get_fact(self, subtask_id: str) -> Fact | None:
        """Return the ``Fact`` for *subtask_id*, or ``None`` if not found."""
        return next((f for f in self.facts if f.subtask_id == subtask_id), None)

    def get_artifact(self, name: str) -> Any | None:
        """Return the output of the subtask whose ``output_artifact`` matches *name*.

        Used by the Executor to resolve ``{{artifact:name}}`` placeholders in
        ReWOO ``params_template`` values.
        """
        subtask = next(
            (s for s in self.plan.subtasks if s.output_artifact == name), None
        )
        if not subtask:
            return None
        fact = self.get_fact(subtask.id)
        return fact.output if fact else None

    def get_resource(self, capability: str) -> ResourceManifest | None:
        """Return the first resource in the pool that advertises *capability*."""
        return next(
            (r for r in self.resource_pool if capability in r.capability_tags), None
        )

    def is_complete(self) -> bool:
        """Return ``True`` when all non-optional subtasks have completed."""
        return all(
            self.progress.get(s.id) == SubtaskStatus.COMPLETED
            for s in self.plan.subtasks
            if not s.is_optional
        )

    def has_failed(self) -> bool:
        """Return ``True`` when at least one non-optional subtask has failed."""
        return any(
            self.progress.get(s.id) == SubtaskStatus.FAILED
            for s in self.plan.subtasks
            if not s.is_optional
        )
