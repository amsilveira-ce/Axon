from __future__ import annotations

from enum import Enum


class OperationalMode(str, Enum):
    agent   = "agent"
    copilot = "copilot"
    no_llm  = "no-llm"


class ReasoningMode(str, Enum):
    react = "react"
    rewoo = "rewoo"
    # tot   = "tot"