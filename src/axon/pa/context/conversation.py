"""
pa/context/conversation.py — Context Layer: ConversationHistory

Mantém o histórico de uma sessão entre usuário e PA com sliding window.
Mensagens fora da janela são sumarizadas via LLM e guardadas em summary.
Persiste em .axon/pa/sessions/{session_id}.json.

Formato de mensagens segue o esquema OpenAI Chat API —
compatível diretamente com OllamaClient.chat().
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from axon.config import ConversationConfig


# Lógica relacionado ao processo de resumo quando estoura a context window da conversa
# ============================
_SUMMARIZER_SKILL = Path(__file__).parent / "skills" / "summarizer.md"

# Prefixo usado para marcar o resumo acumulado dentro do contexto.
_SUMMARY_HEADER = "[Summary of earlier conversation]"
 
 
def _load_summarizer_prompt() -> str:
    
    if _SUMMARIZER_SKILL.exists():
        return _SUMMARIZER_SKILL.read_text(encoding="utf-8").strip()
    

    # fallback inline se o arquivo não existir
    return (
        "Summarize the following conversation turns concisely, preserving "
        "the user's key intents, constraints, entities, and decisions. "
        "Be concise — 3 to 5 sentences. Respond in the same language as the conversation."
    )


def _summarize(overflow: list[Message], current_summary: str, llm_client: object) -> str:
    """Sumariza mensagens overflow. Retorna existing se o LLM falhar."""

    lines = []

    if current_summary:
        # A LLM que monta o resumo sabe o resumo atual ("nunca perdemos completamente um contexto")
        lines += [f"[Existing summary]\n{current_summary}", ""]

    lines.append("[New context to include in summary]")
    lines += [f"{m.role}: {m.content}" for m in overflow]

    try:
        return llm_client.chat(                    
            messages=[
                {"role": "system", "content": _load_summarizer_prompt()},
                {"role": "user",   "content": "\n".join(lines)},
            ],
            temperature=0.0,
            format=None,
        ).strip()
    
    except Exception:
        return current_summary


class Message(BaseModel):
    """
    Unidade atômica de conversa — equivalente a um ChatCompletionMessage.
    timestamp é interno ao Axon e não é enviado ao LLM.
    """

    role:      Literal["user", "assistant", "system"]
    content:   str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_openai(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}

class ConversationHistory(BaseModel):
    """Histórico de uma sessão com sliding window e sumarização automática."""

    session_id: str
    messages:   list[Message]      = Field(default_factory=list)
    summary:    str                = ""
    config:     ConversationConfig = Field(default_factory=ConversationConfig)
    created_at: datetime           = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime           = Field(default_factory=lambda: datetime.now(timezone.utc))

    def add_message(
        self,
        role:       Literal["user", "assistant"],
        content:    str,
        *,
        llm_client: object | None = None,
    ) -> None:
        """
        Adiciona uma mensagem e aplica o sliding window se necessário.
        Se llm_client for fornecido, overflow é sumarizado via LLM.
        Sem llm_client, overflow é descartado e summary preservado.
        """
        self.messages.append(Message(role=role, content=content))
        self.updated_at = datetime.now(timezone.utc)    # sabemos a ultima vez que foi atualizada 

        # limita a quantidade de mensagens de uma conversa que a llm vai ver 
        limit = self.config.max_messages    

        if len(self.messages) > limit:

            # Monta um resumo da parte mais antiga da conversa 
            overflow      = self.messages[:-limit]
            self.messages = self.messages[-limit:]

            if llm_client is not None:
                # Guarda o resumo atualizado
                self.summary = _summarize(overflow, self.summary, llm_client)


    def get_context(self) -> list[dict[str, str]]:
        """Histórico no formato OpenAI Chat — o summary entra como system message."""
        result: list[dict[str, str]] = []

        if self.summary:
            result.append({
                "role":    "system",
                "content": f"{_SUMMARY_HEADER}\n{self.summary}",
            })

        result += [m.to_openai() for m in self.messages]
        return result

    def get_context_str(self) -> str:
        """
        Histórico como texto plano — para prompts que não usam o formato chat
        (ex.: o IntentExtractor, que recebe history como string).
        """
        if self.is_empty():
            return "No previous conversation."

        lines: list[str] = []
        if self.summary:
            lines.append(f"{_SUMMARY_HEADER}\n{self.summary}")
        lines += [f"{m.role}: {m.content}" for m in self.messages]
        return "\n".join(lines)


    def is_empty(self) -> bool:
        return not self.messages and not self.summary
 
    def last_user_message(self) -> str | None:
        return next((m.content for m in reversed(self.messages) if m.role == "user"), None)

    def last_turn(self) -> str | None:
        """A última mensagem do usuário — o turno atual em curso."""
        return self.last_user_message()


    def persist(self, sessions_dir: Path) -> None:

        sessions_dir.mkdir(parents=True, exist_ok=True)

        (sessions_dir / f"{self.session_id}.json").write_text(
            self.model_dump_json(indent=2), encoding="utf-8"
        )

    @classmethod
    def load_or_create(
        cls,
        session_id:   str | None,
        sessions_dir: Path,
        config:       ConversationConfig | None = None,
    ) -> "ConversationHistory":
        
        cfg = config or ConversationConfig()

        if session_id is not None:
            # Se é uma sessão que ja estamos guardando
            path = sessions_dir / f"{session_id}.json"

            if path.exists():
                h = cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
                h.config = cfg
                return h
            
        # se já existe 
        return cls(session_id=session_id or str(uuid.uuid4()), config=cfg)