from __future__ import annotations

from enum import Enum
from datetime import datetime, timezone
from pydantic import AliasChoices, BaseModel, Field
from typing import Any


class ClarificationQuestion(BaseModel):
    question:       str
    ambiguous_span: str
    options:        list[str] | None = None
 
 
class ClarificationNeeded(BaseModel):
    questions: list[ClarificationQuestion]   # 1-3
    context:   str
 
 
class Objective(BaseModel):
    goal:               str
    constraints:        list[str]
    success_definition: str
    is_ambiguous:       bool
 
 
# Union de saída
IntentResult = Objective | ClarificationNeeded