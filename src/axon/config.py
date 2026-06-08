"""Configuration models and path resolution for the Axon platform.

``AxonConfig`` is the root configuration object, loaded from ``axon.config.json``
in the current working directory.  It contains nested sub-configs for the
Principal Agent (``PAConfig``) and any registered Gateway Agent instances
(``GAInstanceConfig``).

Environment variables:

    AXON_DATA_DIR    Override the data directory (abs or relative to cwd).
    AXON_GA_CONTEXT  Override the active Gateway Agent context name.

Typical usage::

    config = read_config()          # raises FileNotFoundError if missing
    p = paths()                     # AxonPaths derived from config.data_dir
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIG_FILENAME = "axon.config.json"

_ENV_DATA_DIR = "AXON_DATA_DIR"
_ENV_GA_CONTEXT = "AXON_GA_CONTEXT"

#: Default local tool manifest written by ``axon init``.
DEFAULT_LOCAL_TOOLS: dict = {
    "version": "0.1.0",
    "tools": [
        {
            "name": "calculator",
            "capability": "calculation",
            "description": "Evaluates mathematical expressions safely",
            "transport": "stdio",
            "command": ["python", "-m", "axon.local_pool.server"],
            "tool": "calculate",
            "enabled": True,
        },
        {
            "name": "web_search",
            "capability": "web_search",
            "description": "Searches the web via DuckDuckGo",
            "transport": "stdio",
            "command": ["python", "-m", "axon.local_pool.server"],
            "tool": "web_search",
            "enabled": True,
        },
        {
            "name": "file_reader",
            "capability": "file_reading",
            "description": "Reads local files — PDF, TXT, CSV, MD",
            "transport": "stdio",
            "command": ["python", "-m", "axon.local_pool.server"],
            "tool": "read_file_tool",
            "enabled": True,
        },
        {
            "name": "datetime_tool",
            "capability": "datetime",
            "description": "Returns current date/time — weekday, ISO timestamp, timezone",
            "transport": "stdio",
            "command": ["python", "-m", "axon.local_pool.server"],
            "tool": "get_datetime",
            "enabled": True,
        },
        {
            "name": "date_diff",
            "capability": "date_diff",
            "description": "Calculates days between two dates; accepts YYYY-MM-DD, 'today', or datetime dict",
            "transport": "stdio",
            "command": ["python", "-m", "axon.local_pool.server"],
            "tool": "days_between_dates",
            "enabled": True,
        },
    ],
}


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


class AxonPaths:
    """Resolved filesystem paths for the Principal Agent data directory.

    All paths are derived from a single ``data_dir`` root so callers never
    hard-code internal layout.

    Attributes:
        root: Base data directory (e.g. ``.axon``).
        pa_dir: Principal Agent subdirectory.
        pa_sessions: Conversation session storage.
        pa_resource_cache: Cached Gateway Agent resource manifests.
        pa_memory_bank: Persistent user memory entries.
        pa_local_tools: Local tool manifest (``local_tools.json``).
        pa_ga_affinity: UCB1 affinity scores per gateway.
        pa_traces: Per-run execution traces.
    """

    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir
        self.pa_dir = data_dir / "pa"
        self.pa_sessions = data_dir / "pa" / "sessions"
        self.pa_resource_cache = data_dir / "pa" / "resource_cache.json"
        self.pa_memory_bank = data_dir / "pa" / "memory_bank.json"
        self.pa_local_tools = data_dir / "pa" / "local_tools.json"
        self.pa_ga_affinity = data_dir / "pa" / "ga_affinity.json"
        self.pa_traces = data_dir / "pa" / "traces"

    def makedirs(self) -> None:
        """Create all required directories, ignoring those that already exist."""
        for d in (self.pa_dir, self.pa_sessions, self.pa_traces):
            d.mkdir(parents=True, exist_ok=True)


class GAPaths:
    """Resolved filesystem paths for a single Gateway Agent instance.

    Attributes:
        root: Base directory for this GA instance.
        registry: Resource registry file.
        tokens: Auth token store.
        traces: Per-request execution traces.
        ga_config: Instance configuration file (``ga.json``).
    """

    def __init__(self, ga_dir: Path) -> None:
        self.root = ga_dir
        self.registry = ga_dir / "registry.json"
        self.tokens = ga_dir / "tokens.json"
        self.traces = ga_dir / "traces"
        self.ga_config = ga_dir / "ga.json"

    def makedirs(self) -> None:
        """Create all required directories, ignoring those that already exist."""
        for d in (self.root, self.traces):
            d.mkdir(parents=True, exist_ok=True)


def resolve_data_dir(
    config_data_dir: str | None = None,
    cwd: Path | None = None,
) -> Path:
    """Resolve the effective data directory, applying the env-var override.

    Priority order:

    1. ``AXON_DATA_DIR`` environment variable.
    2. *config_data_dir* from the config file.
    3. ``<cwd>/.axon`` (default).

    Relative paths are resolved relative to *cwd* (or ``Path.cwd()``).
    """
    base = cwd or Path.cwd()
    env = os.environ.get(_ENV_DATA_DIR)
    if env:
        p = Path(env)
        return p if p.is_absolute() else base / p
    if config_data_dir:
        p = Path(config_data_dir)
        return p if p.is_absolute() else base / p
    return base / ".axon"


def paths(cwd: Path | None = None) -> AxonPaths:
    """Return ``AxonPaths`` for the current working directory.

    Reads ``axon.config.json`` to obtain ``data_dir``; falls back to
    ``.axon`` if the config file is not found.
    """
    config_data_dir: str | None = None
    try:
        cfg = read_config(cwd)
        config_data_dir = cfg.data_dir
    except FileNotFoundError:
        pass
    return AxonPaths(resolve_data_dir(config_data_dir, cwd))


def ga_paths(context: str | None = None, cwd: Path | None = None) -> GAPaths:
    """Return ``GAPaths`` for the active Gateway Agent context.

    Context resolution priority:

    1. ``AXON_GA_CONTEXT`` environment variable.
    2. *context* argument.
    3. ``config.current_gateway``.
    4. ``"default"``.

    Falls back to ``<data_dir>/ga`` when the config file is not found or
    the resolved context has no matching entry.
    """
    env_ctx = os.environ.get(_ENV_GA_CONTEXT)
    ctx = env_ctx or context

    try:
        cfg = read_config(cwd)
        if ctx is None:
            ctx = cfg.current_gateway
        ga_cfg = cfg.gateways.get(ctx or "default")
        if ga_cfg:
            base = cwd or Path.cwd()
            p = Path(ga_cfg.data_dir)
            return GAPaths(p if p.is_absolute() else base / p)
    except FileNotFoundError:
        pass

    return GAPaths(resolve_data_dir(None, cwd) / "ga")


# ---------------------------------------------------------------------------
# Configuration models
# ---------------------------------------------------------------------------


class LLMConfig(BaseModel):
    """Connection settings for the local Ollama LLM backend.

    Attributes:
        host: Base URL of the Ollama server.
        model: Model tag to use for all LLM calls.
        temperature: Sampling temperature (0.0 = deterministic).
        timeout: Request timeout in seconds.
    """

    host: str = "http://localhost:11434"
    model: str = "deepseek-r1:14b"
    temperature: float = 0.0
    timeout: int = 180


class BudgetConfig(BaseModel):
    """Hard resource limits for a single Principal Agent run.

    These values are copied into ``Budget`` at the start of each run and
    enforced by ``BudgetGuard`` before every LLM call and tool call.

    Attributes:
        tokens_max: Maximum total tokens across the run.
        cost_max_usd: Maximum total cost in USD.
        calls_max: Maximum number of LLM or tool calls.
        timeout_ms: Maximum wall-clock time in milliseconds.
    """

    tokens_max: int = 60_000
    cost_max_usd: float = 0.50
    calls_max: int = 40
    timeout_ms: float = 120_000.0


class ConversationConfig(BaseModel):
    """Controls how much conversation history is injected into prompts.

    Attributes:
        max_messages: Maximum number of past messages to include.
        max_tokens: Maximum token budget for history (``None`` = unlimited).
        window_mode: Whether to limit by message count, token count, or both.
    """

    max_messages: int = 10
    max_tokens: int | None = None
    window_mode: Literal["messages", "tokens", "both"] = "messages"


class CacheConfig(BaseModel):
    """Settings for the Gateway Agent resource manifest cache.

    Attributes:
        enabled: When ``False``, the cache is bypassed entirely.
        max_size: Maximum number of resource manifests to retain (LRU eviction).
    """

    enabled: bool = True
    max_size: int = 50


class IntentExtractorConfig(BaseModel):
    """Optional domain-specific settings for the ``IntentExtractor``.

    Attributes:
        domain: Name of the domain skill file to load from
            ``pa/skills/domains/<domain>.md``.  ``None`` uses the base skill.
        intents: Reserved for future intent-specific overrides.
    """

    domain: str | None = None
    intents: dict = Field(default_factory=dict)


class ResourcePolicyConfig(BaseModel):
    """Operator-level policy controlling which resources the PA may use.

    Applied by the Resolver before handing a ``ResourceManifest`` to the
    Executor.  The Executor is policy-blind — it only executes.

    Resources whose auth token is not configured are always rejected by the
    Resolver regardless of this policy.

    Attributes:
        allow_paid: Whether the PA may call resources marked ``is_paid=True``.
        max_cost_per_call: Per-call cost ceiling in USD (``None`` = no limit).
        fallback_strategy: Action taken when no eligible resource is found.

            - ``"skip"`` — skip the subtask and continue the plan.
            - ``"fail"`` — abort the run with an error.
            - ``"ask_user"`` — surface a ``ClarificationNeeded`` to the user.
        match_threshold: Minimum similarity score in [0, 1] required to accept
            a resource returned by a Gateway Agent.
    """

    allow_paid: bool = True
    max_cost_per_call: float | None = None
    fallback_strategy: Literal["skip", "fail", "ask_user"] = "ask_user"
    match_threshold: float = 0.0


class ConnectedGateway(BaseModel):
    """A Gateway Agent registered with the Principal Agent.

    Persisted when ``axon pa gateway add`` is run.  Survives GA restarts so
    the PA can reconnect without re-registration.

    Attributes:
        url: Base URL of the Gateway Agent HTTP API.
        name: Human-readable display name.
        version: GA software version at registration time.
        trust_level: Operator-assigned trust level (free-form string).
        organization: Owning organisation, if known.
        added_at: UTC timestamp of registration.
        last_seen: UTC timestamp of the most recent successful contact.
    """

    url: str
    name: str
    version: str = "0.1.0"
    trust_level: str = "unknown"
    organization: str | None = None
    added_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime | None = None


class GAInstanceConfig(BaseModel):
    """Configuration for a locally managed Gateway Agent instance.

    Attributes:
        name: Display name of this instance.
        port: HTTP port the GA listens on.
        data_dir: Directory for registry, tokens, and traces.
        version: GA software version.
        retrieval_strategy: How the GA matches capability queries.
        embedding_model: Ollama model used for embedding (required when
            *retrieval_strategy* is ``"embedding"``).
        embedding_host: Ollama host used for embedding inference.
        embedding_threshold: Minimum cosine similarity to accept a match.
        embedding_top_k: Maximum number of candidates returned per query.
    """

    name: str
    port: int = 5000
    data_dir: str = ".axon/ga/default"
    version: str = "0.1.0"
    retrieval_strategy: Literal["keyword", "embedding"] = "keyword"
    embedding_model: str | None = None
    embedding_host: str = "http://localhost:11434"
    embedding_threshold: float = 0.3
    embedding_top_k: int = 5


class PAConfig(BaseModel):
    """Full configuration for the Principal Agent.

    Attributes:
        port: HTTP port the PA API listens on.
        default_reasoning: Default execution strategy (``"react"`` or ``"rewoo"``).
        max_iterations: Maximum Executor loop iterations per subtask.
        gateways: Registered Gateway Agents, ordered by preference.
        llm: LLM backend connection settings.
        budget: Hard resource limits per run.
        conversation: Conversation history window settings.
        cache: Resource manifest cache settings.
        intent_extractor: Intent extraction overrides.
        resource_policy: Operator resource-use policy.
    """

    port: int = 4100
    default_reasoning: str = "rewoo"
    max_plan_subtasks: int = 5 
    
    gateways: list[ConnectedGateway] = Field(default_factory=list)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    conversation: ConversationConfig = Field(default_factory=ConversationConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    intent_extractor: IntentExtractorConfig = Field(default_factory=IntentExtractorConfig)
    resource_policy: ResourcePolicyConfig = Field(default_factory=ResourcePolicyConfig)


class AxonConfig(BaseModel):
    """Root configuration object, loaded from ``axon.config.json``.

    Attributes:
        version: Config schema version.
        data_dir: Base data directory (relative to project root or absolute).
        pa: Principal Agent configuration.
        gateways: Named Gateway Agent instance configurations.
        current_gateway: Active GA context used by ``ga_paths()``.
    """

    version: str = "0.1.0"
    data_dir: str = ".axon"
    pa: PAConfig = Field(default_factory=PAConfig)
    gateways: dict[str, GAInstanceConfig] = Field(
        default_factory=lambda: {
            "default": GAInstanceConfig(
                name="Axon Local Gateway",
                port=5000,
                data_dir=".axon/ga/default",
            )
        }
    )
    current_gateway: str = "default"


# ---------------------------------------------------------------------------
# Config I/O
# ---------------------------------------------------------------------------


def config_path(cwd: Path | None = None) -> Path:
    """Return the expected path of ``axon.config.json`` in *cwd*."""
    return (cwd or Path.cwd()) / CONFIG_FILENAME


def config_exists(cwd: Path | None = None) -> bool:
    """Return ``True`` if ``axon.config.json`` exists in *cwd*."""
    return config_path(cwd).exists()


def read_config(cwd: Path | None = None) -> AxonConfig:
    """Load and validate ``axon.config.json`` from *cwd*.

    Raises:
        FileNotFoundError: When the config file does not exist.
    """
    p = config_path(cwd)
    if not p.exists():
        raise FileNotFoundError(
            'axon.config.json not found. Run "axon init" to create one.'
        )
    return AxonConfig.model_validate(json.loads(p.read_text(encoding="utf-8")))


def write_config(config: AxonConfig, cwd: Path | None = None) -> None:
    """Serialise *config* and write it to ``axon.config.json`` in *cwd*."""
    p = config_path(cwd)
    p.write_text(config.model_dump_json(indent=2) + "\n", encoding="utf-8")


def patch_config(
    fn: Callable[[AxonConfig], AxonConfig],
    cwd: Path | None = None,
) -> AxonConfig:
    """Read the config, apply *fn*, write it back, and return the result.

    Args:
        fn: Pure function that takes the current config and returns the updated one.
        cwd: Working directory override.
    """
    updated = fn(read_config(cwd))
    write_config(updated, cwd)
    return updated
