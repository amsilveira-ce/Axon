from __future__ import annotations
 
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
 
from pydantic import BaseModel, Field
 
from axon.types import OperationalMode, ReasoningMode


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
    max_intractions: int = 10 
    cache: bool = True 

class GAConfig(BaseModel):
    port: int = 5000
    # Diretório que guardamos os arquivos runtime - default config
    registry_path = ".axon/registry.json"

class AxonConfig(BaseModel):
    # Configuração do Axon básica envolve configurar o Principal Agent e Gateway Agent 
    # esses objetos criam a concepção do axon.config.json
    version: str      = "0.1.0"
    pa:      PAConfig = Field(default_factory=PAConfig)
    ga:      GAConfig = Field(default_factory=GAConfig)
