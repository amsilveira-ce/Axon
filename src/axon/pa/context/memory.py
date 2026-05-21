"""
pa/context/memory.py — Context Layer: MemoryBank
 
Responsabilidade:
  Armazenar preferências e defaults do domínio que persistem entre sessões.
  Injetado no prompt do IntentExtractor via get_summary().
 
Diferença em relação ao ConversationHistory:
  ConversationHistory  → histórico de uma sessão específica (volátil)
  MemoryBank           → preferências cross-session do operador/domínio (persistente)
 
Exemplos de entradas:
  preferred_format: PDF
  data_source: HStory EHR
  language: Portuguese (Brazil)
  patient_data_always_available: true
 
Persistência:
  .axon/pa/memory_bank.json  (paths().pa_memory_bank)
"""

 
from __future__ import annotations
 
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
 
from pydantic import BaseModel, Field


class MemoryEntry(BaseModel):
    key:        str
    value:      Any
    source:     str       = "operator"   # "operator" | "learned" 
    updated_at: datetime  = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
 
 
class MemoryBank(BaseModel):
    entries:    list[MemoryEntry] = Field(default_factory=list)
    version:    str               = "0.1.0"
    updated_at: datetime          = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
 

    def set(
        self,
        key:    str,
        value:  Any,
        source: str = "operator",
    ) -> None:
        """
        Define ou atualiza uma entrada.
        Se a chave já existe, substitui o valor e atualiza o timestamp.
        """
        for entry in self.entries:
            if entry.key == key:
                entry.value      = value
                entry.source     = source
                entry.updated_at = datetime.now(timezone.utc)
                self.updated_at  = datetime.now(timezone.utc)
                return
 
        self.entries.append(MemoryEntry(key=key, value=value, source=source))
        self.updated_at = datetime.now(timezone.utc)
 
    def get(self, key: str, default: Any = None) -> Any:
        """Retorna o valor de uma chave ou default se não existir."""

        for entry in self.entries:

            if entry.key == key:
                return entry.value
            
        return default
 
    def delete(self, key: str) -> bool:
        """Remove uma entrada. Retorna True se removida, False se não encontrada."""

        before = len(self.entries)

        self.entries = [e for e in self.entries if e.key != key]

        if len(self.entries) < before:

            self.updated_at = datetime.now(timezone.utc)
            return True
        
        return False
 
    def clear(self) -> None:
        """Remove todas as entradas."""
        self.entries    = []
        self.updated_at = datetime.now(timezone.utc)
 
    def keys(self) -> list[str]:
        return [e.key for e in self.entries]
 
    def is_empty(self) -> bool:
        return len(self.entries) == 0
 
    #   get_summary: injetado no prompt do IntentExtractor
    # ========================================================
 
    def get_summary(self) -> str:
        """
        Formata as entradas como string para injeção no CONTEXT_TEMPLATE.
 
        Formato:
            - key: value
            - key: value
 
        Retorna string vazia se não há entradas.
        """
        if self.is_empty():
            return "No user memory available."
 
        lines = [f"- {e.key}: {e.value}" for e in self.entries]
        return "\n".join(lines)
 
    def persist(self, path: Path) -> None:
        """
        Persiste em .axon/pa/memory_bank.json.
 
        Args:
            path: caminho completo do arquivo
                  obtido via paths().pa_memory_bank
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            self.model_dump_json(indent=2),
            encoding="utf-8",
        )
 
    @classmethod
    def load(cls, path: Path) -> "MemoryBank":
        """
        Carrega do arquivo. Chamado no startup do PA.

        Args:
            path: caminho completo do arquivo

        Returns:
            MemoryBank carregado, ou MemoryBank vazio se arquivo não existir.
        """
        if not path.exists():
            return cls()

        return cls.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )

    # Alias retrocompatível.
    load_or_create = load
