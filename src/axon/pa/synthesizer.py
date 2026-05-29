"""
pa/synthesizer.py — ResponseSynthesizer

Última etapa do pipeline do PA. Chamada LLM simples (sem reasoning) que transforma
o resultado da run em uma resposta em linguagem natural para o usuário.

  IntentExtractor → Decomposer → Planner → Resolver → Executor → ResponseSynthesizer

É o único componente cujo output vai DIRETO para o usuário, não para o AgentState.
Não escreve no state — só lê. O comportamento (tom, formato, língua, domínio) vive
em pa/skills/response_synthesis.md, editável pelo operador.

Recebe: state.objective.goal, state.facts, state.failures, state.plan.subtasks,
        history.last_turn() (contexto do turno atual).
Produz: str — a resposta final.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from axon.config import PAConfig
from axon.llms.ollama_client import OllamaClient

if TYPE_CHECKING:
    from axon.pa.context.conversation import ConversationHistory
    from axon.pa.models import AgentState

logger = logging.getLogger(__name__)

_SKILL_PATH = Path(__file__).parent / "skills" / "response_synthesis.md"
_THINK_RE   = re.compile(r"<think>.*?</think>", re.DOTALL)


def _load_behavior() -> str:
    return _SKILL_PATH.read_text(encoding="utf-8").strip()


class ResponseSynthesizer:
    """
    Gera a resposta final ao usuário a partir do resultado da run.

    Chamada LLM simples: temperatura baixa, sem reasoning (think=False) — não é o
    lugar de raciocinar, só de comunicar o que já foi produzido.
    """

    def __init__(self, config: PAConfig) -> None:
        self._client = OllamaClient(
            host=config.llm.host,
            model=config.llm.model,
            timeout=config.llm.timeout,
        )
        self._system = _load_behavior()

    def synthesize(self, state: "AgentState", history: "ConversationHistory | None" = None) -> str:
        """Lê o state (e o turno atual) e devolve a resposta em linguagem natural."""
        context = self._build_context(state, history)
        raw = self._client.generate(
            context,
            system=self._system,
            temperature=0.3,   # prosa natural; ainda quase determinístico
            format=None,
            think=False,       # resposta simples, sem reasoning
            retries=2,
        )
        return _THINK_RE.sub("", raw).strip()

    # ------------------------------------------------------------------

    def _build_context(self, state: "AgentState", history: "ConversationHistory | None") -> str:
        objective = state.objective
        goal      = objective.goal if objective else state.raw_query

        lines = [f"User request: {goal}"]
        if objective and objective.success_definition:
            lines.append(f"Success criteria: {objective.success_definition}")

        last_turn = None
        if history is not None:
            try:
                last_turn = history.last_turn()
            except Exception:
                last_turn = None
        if last_turn and last_turn != goal:
            lines.append(f"Current user message: {last_turn}")

        lines.append("")
        lines.append("Executed plan and results:")
        for s in state.plan.subtasks:
            status = state.progress.get(s.id)
            label  = status.value if status else "pending"
            lines.append(f"- {s.description} [{label}]")
            fact = state.get_fact(s.id)
            if fact is not None:
                lines.append(f"    result: {_truncate(fact.output)}")
            else:
                fails = [f for f in state.failures if f.subtask_id == s.id]
                if fails:
                    lines.append(f"    failed: {fails[-1].reason}")

        if not state.facts and state.failures:
            lines.append("")
            lines.append("Note: no step produced a result — explain what went wrong.")

        return "\n".join(lines)


def _truncate(value: Any, limit: int = 2000) -> str:
    """Serializa o output de um Fact para o prompt, com teto generoso."""
    try:
        s = json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        s = str(value)
    return s if len(s) <= limit else s[:limit] + "…"
