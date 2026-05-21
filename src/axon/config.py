from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, Field

from axon.types import OperationalMode, ReasoningMode

# ======================================================
#   Arquivo de configuração
# ======================================================

CONFIG_FILENAME = "axon.config.json"

# ======================================================
#   data_dir — resolvido em runtime
#
#   Prioridade:
#     1. AXON_DATA_DIR (env var)          → produção / container
#     2. axon.config.json → data_dir      → operador configurou explicitamente
#     3. ".axon"                          → default dev local
#
#   Uso:
#     from axon.config import paths
#     p = paths()                         # usa cwd implícito
#     p = paths(cwd=Path("/app"))         # override
#     p.ga_registry                       # Path resolvido
# ======================================================

_ENV_DATA_DIR = "AXON_DATA_DIR"


class AxonPaths:
    """
    Todos os paths do projeto derivados de um único data_dir.

    Nunca construa paths manualmente fora desta classe —
    registry.py, tokens.py e conversation.py importam daqui.
    """

    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir

        # GA
        self.ga_dir      = data_dir / "ga"
        self.ga_registry = data_dir / "ga" / "registry.json"
        self.ga_tokens   = data_dir / "ga" / "tokens.json"
        self.ga_traces   = data_dir / "ga" / "traces"

        # PA
        self.pa_dir            = data_dir / "pa"
        self.pa_sessions       = data_dir / "pa" / "sessions"
        self.pa_resource_cache = data_dir / "pa" / "resource_cache.json"
        self.pa_memory_bank    = data_dir / "pa" / "memory_bank.json"
        self.pa_traces         = data_dir / "pa" / "traces"

    def makedirs(self) -> None:
        """Cria toda a estrutura de diretórios."""
        for d in (
            self.ga_dir,
            self.ga_traces,
            self.pa_dir,
            self.pa_sessions,
            self.pa_traces,
        ):
            d.mkdir(parents=True, exist_ok=True)


def resolve_data_dir(
    config_data_dir: str | None = None,
    cwd: Path | None = None,
) -> Path:
    """
    Resolve o data_dir seguindo a ordem de prioridade:
      1. AXON_DATA_DIR env var  (absoluto ou relativo ao cwd)
      2. config.data_dir        (valor do axon.config.json)
      3. ".axon"                (default dev local, relativo ao cwd)
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
    """
    Retorna AxonPaths resolvido para o contexto atual.

    Lê o axon.config.json se existir para obter data_dir configurado.
    Se não existir (ex: durante o axon init), usa env var ou default.
    """
    config_data_dir: str | None = None
    try:
        cfg = read_config(cwd)
        config_data_dir = cfg.data_dir
    except FileNotFoundError:
        pass

    data_dir = resolve_data_dir(config_data_dir, cwd)
    return AxonPaths(data_dir)


# ======================================================
#   Modelos de configuração
# ======================================================

class GatewayEntry(BaseModel):
    id:       str
    url:      str
    added_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LLMConfig(BaseModel):
    host:    str = "http://localhost:11434"
    model:   str = "deepseek-r1:14b"    # Deixar como default um modelo com reasoning
    timeout: int = 60



# Discussão de se isso é realmente necessário ..... 
class ConversationConfig(BaseModel):
    """
    Configuração da janela deslizante do ConversationHistory.

    max_messages — quantas mensagens a janela mantém antes de sumarizar/descartar.
    window_mode  — critério da janela: "messages" (contagem de turnos) ou
                   "tokens" (orçamento de tokens, reservado para uso futuro).
    """

    max_messages: int                          = 10
    window_mode:  Literal["messages", "tokens"] = "messages"


class PAConfig(BaseModel):
    port:                   int                = 4100
    default_mode:           OperationalMode    = OperationalMode.agent
    default_reasoning_mode: ReasoningMode      = ReasoningMode.react
    gateways:               list[GatewayEntry] = Field(default_factory=list)
    max_iterations:         int                = 10
    cache:                  bool               = True
    llm:                    LLMConfig          = Field(default_factory=LLMConfig)
    window_size:            int                = 10


class GAConfig(BaseModel):
    port: int = 5000


class AxonConfig(BaseModel):
    version:  str      = "0.1.0"
    data_dir: str      = ".axon"   # sobrescrito em produção via env var ou aqui
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
    p.write_text(
        config.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def patch_config(
    fn: Callable[[AxonConfig], AxonConfig],
    cwd: Path | None = None,
) -> AxonConfig:
    updated = fn(read_config(cwd))
    write_config(updated, cwd)
    return updated