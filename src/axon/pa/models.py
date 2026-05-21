from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
#   Constraint
# ---------------------------------------------------------------------------
# ajuda a llm a reconhecer "restrições" relacionada a tafera 
class Constraint(BaseModel):
    value:    str
    type:     Literal["temporal", "size", "policy", "format"]
    implicit: bool = False
    source:   str  = ""   # trecho da query que originou a constraint


# ---------------------------------------------------------------------------
#   Clarification — embutida no Objective
# ---------------------------------------------------------------------------

class ClarificationQuestion(BaseModel):
    question:       str
    ambiguous_span: str
    options:        list[str] | None = None


class ClarificationNeeded(BaseModel):
    questions: list[ClarificationQuestion]   # 1-3
    context:   str


# ---------------------------------------------------------------------------
#   Objective — único tipo de retorno do IntentExtractor
#
#   clarification is None     → completo, segue para o Decomposer
#   clarification is not None → incompleto, pergunta ao usuário
# ---------------------------------------------------------------------------

class Objective(BaseModel):
    goal:               str
    constraints:        list[Constraint]       = Field(default_factory=list)
    success_definition: str                    = ""
    capability_hints:   list[str]              = Field(default_factory=list)
    extracted_inputs:   dict[str, Any]         = Field(default_factory=dict)
    assumptions:        list[str]              = Field(default_factory=list)
    clarification:      ClarificationNeeded | None = None


# Alias para compatibilidade com agent.py e chat.py
IntentResult = Objective


# ---------------------------------------------------------------------------
#   ExtractionTrace — resultado + contexto injetado
# ---------------------------------------------------------------------------

class ExtractionTrace:
    """
    Carrega o contexto que foi injetado no prompt e o resultado.
    Usado pelo --verbose no CLI para mostrar o que o PA está vendo.
    """
    def __init__(
        self,
        objective: "Objective",
        context:   str,
        history_str:   str,
        memory_str:    str,
        resources_str: str,
    ) -> None:
        self.objective     = objective
        self.context       = context
        self.history_str   = history_str
        self.memory_str    = memory_str
        self.resources_str = resources_str