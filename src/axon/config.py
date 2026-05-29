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
_ENV_DATA_DIR   = "AXON_DATA_DIR"
_ENV_GA_CONTEXT = "AXON_GA_CONTEXT"

# ======================================================
#   Default local tools
# ======================================================
# sim está hardocoded por hora 
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
#   AxonPaths — PA paths
# ======================================================

class AxonPaths:
    """PA paths derivados do data_dir global."""

    def __init__(self, data_dir: Path) -> None:
        self.root              = data_dir
        self.pa_dir            = data_dir / "pa"
        self.pa_sessions       = data_dir / "pa" / "sessions"
        self.pa_resource_cache = data_dir / "pa" / "resource_cache.json"
        self.pa_memory_bank    = data_dir / "pa" / "memory_bank.json"
        self.pa_local_tools    = data_dir / "pa" / "local_tools.json"
        self.pa_traces         = data_dir / "pa" / "traces"

    def makedirs(self) -> None:
        for d in (self.pa_dir, self.pa_sessions, self.pa_traces):
            d.mkdir(parents=True, exist_ok=True)


class GAPaths:
    """Paths de uma instância específica do Gateway Agent."""

    def __init__(self, ga_dir: Path) -> None:
        self.root      = ga_dir
        self.registry  = ga_dir / "registry.json"
        self.tokens    = ga_dir / "tokens.json"
        self.traces    = ga_dir / "traces"
        self.ga_config = ga_dir / "ga.json"   # config da instância

    def makedirs(self) -> None:
        for d in (self.root, self.traces):
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
    """Retorna AxonPaths (PA) para o contexto atual."""
    config_data_dir: str | None = None
    try:
        cfg = read_config(cwd)
        config_data_dir = cfg.data_dir
    except FileNotFoundError:
        pass
    return AxonPaths(resolve_data_dir(config_data_dir, cwd))


def ga_paths(context: str | None = None, cwd: Path | None = None) -> GAPaths:
    """
    Retorna GAPaths para o contexto GA ativo.

    Prioridade:
      1. AXON_GA_CONTEXT env var 
      2. context argumento
      3. config.current_gateway
      4. "default"
    """

    # para conseguir trocar o GA em contexto de containers sem ter que mudar a imagem 
    #   docker run -e axon_ga_context = ga_corp
    # Checando o arquivo com cli/ga/serve é possivel ver que usamos a variavel como 
    # usamos o resolver do GAConfig; Dentro do GAConfig.resolver() tem uma hierarquia de 
    # configuração que segue primeiro o argumento, depois a variavel de ambiente e por fim se
    # nenhum deses é passo o default que é o GA obrigatoriamente criado com o axon init 
    env_ctx = os.environ.get(_ENV_GA_CONTEXT)
    ctx     = env_ctx or context

    try:
        # Adendo que o contexto é sempre relacionado com o gateway agent que o operador do ga 
        # vai estar configurando na cli, para permitir melhor experiência e manter a ideia de 
        # que um operador tem a liberdade sim de criar um gateway agent que pode funcionar como 
        # um produto sozinho desaclopado do PA; Contudo para mvp nós vamos manter ele atrelado 
        # à existencia do axon.config.json primeiro atraves do axon init 
        cfg = read_config(cwd)
        if ctx is None:
            ctx = cfg.current_gateway

        ga_cfg = cfg.gateways.get(ctx or "default")
        if ga_cfg:
            base = cwd or Path.cwd()
            p    = Path(ga_cfg.data_dir)
            ga_dir = p if p.is_absolute() else base / p
            return GAPaths(ga_dir)
    except FileNotFoundError:
        pass

    # fallback: .axon/ga
    base   = cwd or Path.cwd()
    ga_dir = resolve_data_dir(None, cwd) / "ga"
    return GAPaths(ga_dir)


# ======================================================
#   Modelos de configuração
# ======================================================

class GAInstanceConfig(BaseModel):
    """Configuração de uma instância do Gateway Agent."""
    name:                str
    port:                int                              = 5000
    data_dir:            str                             = ".axon/ga/default"
    version:             str                             = "0.1.0"
    retrieval_strategy:  Literal["keyword", "embedding"] = "keyword"
    embedding_model:     str | None                      = None
    embedding_host:      str                             = "http://localhost:11434"
    embedding_threshold: float                           = 0.3
    embedding_top_k:     int                             = 5


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


class AxonConfig(BaseModel):
    version:         str                          = "0.1.0"
    data_dir:        str                          = ".axon"
    pa:              PAConfig                     = Field(default_factory=PAConfig)
    gateways:        dict[str, GAInstanceConfig]  = Field(default_factory=lambda: {
        "default": GAInstanceConfig(name="Axon Local Gateway", port=5000, data_dir=".axon/ga/default")
    })
    current_gateway: str                          = "default"


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