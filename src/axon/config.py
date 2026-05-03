from __future__ import annotations
 
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
 
from pydantic import BaseModel, Field
 
from axon.types import OperationalMode, ReasoningMode


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