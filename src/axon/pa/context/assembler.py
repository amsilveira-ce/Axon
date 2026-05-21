"""
pa/context/assembler.py — Context Layer: PromptAssembler

Responsabilidade:
  Montar o contexto que será injetado no prompt do IntentExtractor.
  Gerencia o budget de tokens entre as três seções variáveis:
    history   → prioridade mais alta  (nunca corta summary)
    memory    → prioridade média
    resources → prioridade mais baixa

Budget:
  ConversationConfig.max_tokens cobre history + memory + resources.
  OUTPUT_CONTRACT e behavior do skill são fixos — fora desse budget.
  Estimativa: len(content) // 4  (aprox. tokens GPT-style)

Corte quando budget estoura:
  1. resources   → removido primeiro (capability tags)
  2. memory      → removido segundo
  3. history     → mensagens mais antigas removidas; summary sempre fica
  4. query       → nunca cortado
"""

from __future__ import annotations

from axon.config import ConversationConfig
from axon.pa.context.conversation import ConversationHistory
from axon.pa.context.memory import MemoryBank

# ---------------------------------------------------------------------------
#   Template hardcoded — saiu do intent_extractor.py
# ---------------------------------------------------------------------------

CONTEXT_TEMPLATE = """\
--- Conversation History ---
{history}

--- User Memory ---
{memory}

--- Available Resources ---
{resources}

--- User Query ---
{query}\
"""

_SECTION_EMPTY = {
    "history":   "No previous conversation.",
    "memory":    "No user memory available.",
    "resources": "No resources available.",
}


# ---------------------------------------------------------------------------
#   Estimativa de tokens
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """Estimativa rápida: 1 token ≈ 4 caracteres."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
#   PromptAssembler
# ---------------------------------------------------------------------------

class PromptAssembler:
    """
    Monta o contexto para o IntentExtractor respeitando o budget de tokens.

    Uso:
        assembler = PromptAssembler(config.conversation)
        context   = assembler.build(query, history, memory, resources)
        # context é a string pronta para CONTEXT_TEMPLATE
    """

    def __init__(self, config: ConversationConfig) -> None:
        self._max_tokens: int | None = config.max_tokens

    def build(
        self,
        query:     str,
        history:   ConversationHistory | None = None,
        memory:    MemoryBank | None          = None,
        resources: list[str] | None           = None,
    ) -> str:
        """
        Monta o contexto completo respeitando o budget de tokens.

        Args:
            query:     query do usuário (nunca cortada)
            history:   ConversationHistory da sessão atual
            memory:    MemoryBank cross-session
            resources: lista de capability tags disponíveis

        Returns:
            str — contexto formatado pronto para injetar no prompt
        """

        print(f"\n[DEBUG assembler] history type: {type(history)}")
        print(f"[DEBUG assembler] history is_empty: {history.is_empty() if history else 'None'}")
        print(f"[DEBUG assembler] messages count: {len(history.messages) if history else 0}")
        if history and history.messages:
            for m in history.messages:
                print(f"  [{m.role}]: {m.content[:80]}")
        history_str   = self._render_history(history)
        memory_str    = self._render_memory(memory)
        resources_str = self._render_resources(resources)

        # aplica budget — corta na ordem de prioridade
        history_str, memory_str, resources_str = self._apply_budget(
            history_str, memory_str, resources_str, history
        )

        return CONTEXT_TEMPLATE.format(
            history=history_str   or _SECTION_EMPTY["history"],
            memory=memory_str     or _SECTION_EMPTY["memory"],
            resources=resources_str or _SECTION_EMPTY["resources"],
            query=query,
        )

    # ------------------------------------------------------------------
    #   Renderers
    # ------------------------------------------------------------------

    def _render_history(self, history: ConversationHistory | None) -> str:
        if history is None or history.is_empty():
            return ""
        return history.get_context()

    def _render_memory(self, memory: MemoryBank | None) -> str:
        if memory is None or memory.is_empty():
            return ""
        return memory.get_summary()

    def _render_resources(self, resources: list[str] | None) -> str:
        if not resources:
            return ""
        return "\n".join(f"- {r}" for r in resources)

    # ------------------------------------------------------------------
    #   Budget
    # ------------------------------------------------------------------

    def _apply_budget(
        self,
        history_str:   str,
        memory_str:    str,
        resources_str: str,
        history:       ConversationHistory | None,
    ) -> tuple[str, str, str]:
        """
        Aplica o budget de tokens na ordem de prioridade de corte:
          1. resources (remove tudo se necessário)
          2. memory    (remove tudo se necessário)
          3. history   (remove mensagens mais antigas; summary sempre fica)

        Se max_tokens é None, retorna sem cortes.
        Retorna (history_str, memory_str, resources_str) ajustados.
        """
        if self._max_tokens is None:
            return history_str, memory_str, resources_str

        total = (
            _estimate_tokens(history_str)
            + _estimate_tokens(memory_str)
            + _estimate_tokens(resources_str)
        )

        if total <= self._max_tokens:
            return history_str, memory_str, resources_str

        # 1. corta resources
        resources_str, total = self._trim_section(
            resources_str, total, priority="resources"
        )
        if total <= self._max_tokens:
            return history_str, memory_str, resources_str

        # 2. corta memory
        memory_str, total = self._trim_section(
            memory_str, total, priority="memory"
        )
        if total <= self._max_tokens:
            return history_str, memory_str, resources_str

        # 3. corta history — mensagens mais antigas primeiro, summary fica
        if history is not None:
            history_str = self._trim_history(history, total)

        return history_str, memory_str, resources_str

    def _trim_section(
        self, content: str, current_total: int, priority: str
    ) -> tuple[str, int]:
        """Remove a seção inteira e recalcula o total."""
        tokens = _estimate_tokens(content)
        return "", current_total - tokens

    def _trim_history(
        self, history: ConversationHistory, current_total: int
    ) -> str:
        """
        Remove mensagens mais antigas até o budget ser respeitado.
        O summary nunca é removido — é o contexto acumulado das sessões.
        """
        # começa com o summary (sempre fica)
        summary_part = ""
        if history.summary:
            summary_part = (
                f"[Summary of previous conversation]\n{history.summary}"
            )

        budget_remaining = self._max_tokens - _estimate_tokens(summary_part)
        if budget_remaining <= 0:
            return summary_part

        # adiciona mensagens do mais recente para o mais antigo
        kept: list[str] = []
        for msg in reversed(history.messages):
            line   = f"{msg.role}: {msg.content}"
            tokens = _estimate_tokens(line)
            if tokens > budget_remaining:
                break
            kept.append(line)
            budget_remaining -= tokens

        kept.reverse()
        parts = [p for p in [summary_part, "\n".join(kept)] if p]
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    #   Diagnóstico
    # ------------------------------------------------------------------

    def token_breakdown(
        self,
        history:   ConversationHistory | None = None,
        memory:    MemoryBank | None          = None,
        resources: list[str] | None           = None,
    ) -> dict[str, int]:
        """
        Retorna estimativa de tokens por seção — útil para debug.
        """
        return {
            "history":    _estimate_tokens(self._render_history(history)),
            "memory":     _estimate_tokens(self._render_memory(memory)),
            "resources":  _estimate_tokens(self._render_resources(resources)),
            "max_tokens": self._max_tokens if self._max_tokens is not None else -1,
        }