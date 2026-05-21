from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, Field

# ======================================================
#   Arquivo de configuração
# ======================================================

CONFIG_FILENAME = "axon.config.json"

_ENV_DATA_DIR = "AXON_DATA_DIR"

# ======================================================
#   Default local tools — criado pelo axon init
# ======================================================

DEFAULT_LOCAL_TOOLS: dict = {
    "version": "0.1.0",
    "tools": [
        {
            "name":        "calculator",
            "capability":  "calculation",
            "description": "Evaluates mathematical expressions safely",
            "transport":   "stdio",
            "command":     ["python", "-m", "axon.pa.tools.server"],
            "enabled":     True,
        },
        {
            "name":        "web_search",
            "capability":  "web_search",
            "description": "Searches the web via DuckDuckGo",
            "transport":   "stdio",
            "command":     ["python", "-m", "axon.pa.tools.server"],
            "enabled":     True,
        },
        {
            "name":        "file_reader",
            "capability":  "file_reading",
            "description": "Reads local files — PDF, TXT, CSV, MD",
            "transport":   "stdio",
            "command":     ["python", "-m", "axon.pa.tools.server"],
            "enabled":     True,
        },
        {
            "name":        "datetime_tool",
            "capability":  "datetime",
            "description": "Returns current date/time and resolves date expressions",
            "transport":   "stdio",
            "command":     ["python", "-m", "axon.pa.tools.server"],
            "enabled":     True,
        },
    ],
}


# ======================================================
#   AxonPaths
# ======================================================

class AxonPaths:
    """Todos os paths do projeto derivados de um único data_dir."""

    def __init__(self, data_dir: Path) -> None:
        self.root              = data_dir
        # GA
        self.ga_dir            = data_dir / "ga"
        self.ga_registry       = data_dir / "ga" / "registry.json"
        self.ga_tokens         = data_dir / "ga" / "tokens.json"
        self.ga_traces         = data_dir / "ga" / "traces"
        # PA
        self.pa_dir            = data_dir / "pa"
        self.pa_sessions       = data_dir / "pa" / "sessions"
        self.pa_resource_cache = data_dir / "pa" / "resource_cache.json"
        self.pa_memory_bank    = data_dir / "pa" / "memory_bank.json"
        self.pa_local_tools    = data_dir / "pa" / "local_tools.json"
        self.pa_traces         = data_dir / "pa" / "traces"

    def makedirs(self) -> None:
        for d in (
            self.ga_dir, self.ga_traces,
            self.pa_dir, self.pa_sessions, self.pa_traces,
        ):
            d.mkdir(parents=True, exist_ok=True)


def resolve_data_dir(config_data_dir: str | None = None, cwd: Path | None = None) -> Path:
    base = cwd or Path.cwd()
    env  = os.environ.get(_ENV_DATA_DIR)
    if env:
        p = Path(env)
        return p if p.is_absolute() else base / p
    if config_data_dir:
        p = Path(config_data_dir)
        return p if p.is_absolute() else base / p
    return base / ".axon"


def paths(cwd: Path | None = None) -> AxonPaths:
    config_data_dir: str | None = None
    try:
        cfg = read_config(cwd)
        config_data_dir = cfg.data_dir
    except FileNotFoundError:
        pass
    return AxonPaths(resolve_data_dir(config_data_dir, cwd))


# ======================================================
#   Modelos de configuração
# ======================================================

class GatewayEntry(BaseModel):
    id:       str
    url:      str
    added_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LLMConfig(BaseModel):
    host:        str   = "http://localhost:11434"
    model:       str   = "deepseek-r1:14b"
    temperature: float = 0.0
    timeout:     int   = 60


class BudgetConfig(BaseModel):
    tokens_max:   int   = 60_000
    cost_max_usd: float = 0.50
    calls_max:    int   = 40
    timeout_ms:   float = 120_000.0


class ConversationConfig(BaseModel):
    max_messages: int                                    = 10
    max_tokens:   int | None                             = None
    window_mode:  Literal["messages", "tokens", "both"] = "messages"


class CacheConfig(BaseModel):
    enabled:  bool = True
    max_size: int  = 50


class IntentExtractorConfig(BaseModel):
    domain:  str | None = None
    intents: dict       = Field(default_factory=dict)


class PAConfig(BaseModel):
    port:              int                   = 4100
    default_reasoning: str                   = "react"
    max_iterations:    int                   = 10
    gateways:          list[str]             = Field(default_factory=list)
    llm:               LLMConfig             = Field(default_factory=LLMConfig)
    budget:            BudgetConfig          = Field(default_factory=BudgetConfig)
    conversation:      ConversationConfig    = Field(default_factory=ConversationConfig)
    cache:             CacheConfig           = Field(default_factory=CacheConfig)
    intent_extractor:  IntentExtractorConfig = Field(default_factory=IntentExtractorConfig)


class GAConfig(BaseModel):
    port: int = 5000


class AxonConfig(BaseModel):
    version:  str      = "0.1.0"
    data_dir: str      = ".axon"
    pa:       PAConfig = Field(default_factory=PAConfig)
    ga:       GAConfig = Field(default_factory=GAConfig)


# ======================================================
#   Métodos para lidar com o arquivo de configuração
# ======================================================

def config_path(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / CONFIG_FILENAME


def config_exists(cwd: Path | None = None) -> bool:
    return config_path(cwd).exists()


def read_config(cwd: Path | None = None) -> AxonConfig:
    p = config_path(cwd)
    if not p.exists():
        raise FileNotFoundError(
            'axon.config.json not found. Run "axon init" to create one.'
        )
    return AxonConfig.model_validate(json.loads(p.read_text(encoding="utf-8")))


def write_config(config: AxonConfig, cwd: Path | None = None) -> None:
    p = config_path(cwd)
    p.write_text(config.model_dump_json(indent=2) + "\n", encoding="utf-8")


def patch_config(fn: Callable[[AxonConfig], AxonConfig], cwd: Path | None = None) -> AxonConfig:
    updated = fn(read_config(cwd))
    write_config(updated, cwd)
    return updated