from __future__ import annotations
 
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, ClassVar
 
from pydantic import BaseModel, Field
 
from axon.types import OperationalMode, ReasoningMode

# ==============================================
#   caminho default do arquivo de configuração
# ==============================================

CONFIG_FILENAME = "axon.config.json"

# ============================
#   Modelos de configuração
# ============================

# obs:Por serem models relacionados ao arquivo de configuração eles ficam aqui por hora 

class GatewayEntry(BaseModel):
    id: str
    url: str 
    added_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PAConfig(BaseModel):
    port: int = 4100
    default_mode: OperationalMode = OperationalMode.agent 
    default_reasoning_mode: ReasoningMode = ReasoningMode.react
    gateways: list[GatewayEntry] = Field(default_factory=list)
    max_iterations: int = 10 
    cache: bool = True 

class GAConfig(BaseModel):
    port: int = 5000
    # Diretório que guardamos os arquivos runtime - default config
    registry_path: ClassVar[str] = ".axon/registry.json"

class AxonConfig(BaseModel):
    # Configuração do Axon básica envolve configurar o Principal Agent e Gateway Agent 
    # esses objetos criam a concepção do axon.config.json
    version: str      = "0.1.0"
    pa:      PAConfig = Field(default_factory=PAConfig)
    ga:      GAConfig = Field(default_factory=GAConfig)


# ===================================================
#  Metodos para lidar com o arquivo de configuração
# ===================================================


def config_path(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / CONFIG_FILENAME
 
 
def config_exists(cwd: Path | None = None) -> bool:
    return config_path(cwd).exists()

def read_config(cwd: Path | None = None)-> AxonConfig:
    p = config_path(cwd)
    if not p.exists():
        raise FileNotFoundError(
            f'axon.config.json not found. Run "axon init" to create one.'
        )
    return AxonConfig.model_validate(json.loads(p.read_text(encoding="utf-8")))

def write_config(config: AxonConfig, cwd: Path | None = None) -> None:
    p = config_path(cwd)
    p.write_text(
        config.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

def patch_config(fn: Callable[[AxonConfig], AxonConfig],cwd: Path | None = None,) -> AxonConfig:
    updated = fn(read_config(cwd))
    write_config(updated, cwd)
    return updated