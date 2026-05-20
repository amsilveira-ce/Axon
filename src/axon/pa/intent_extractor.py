from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError
from axon.config import PAConfig
from axon.llms.ollama_client import OllamaClient, OllamaError
from axon.pa.models import ClarificationNeeded, Objective, ClarificationQuestion, IntentResult

'''
    system prompt 
    output format 


'''
# ---------------------------------------------------------------------------
#   Skill (prompt)
# ---------------------------------------------------------------------------

_SKILL_PATH = Path(__file__).parent / "skills" / "intent_extraction.md"


def _load_skill() -> str:
    return _SKILL_PATH.read_text(encoding="utf-8")




# ---------------------------------------------------------------------------
#   IntentExtractor
# ---------------------------------------------------------------------------

class IntentExtractor:
    """
    Recebe uma query em linguagem natural e retorna:
      - Objective          quando há informação suficiente para agir
      - ClarificationNeeded quando a query é ambígua demais para prosseguir

    A decisão é tomada pela LLM (via Ollama) usando o skill
    pa/skills/intent_extraction.md como system prompt.
    """

    def __init__(self, config: PAConfig) -> None:

        self._client = OllamaClient(
            host=config.llm.host,
            model=config.llm.model,
            timeout=config.llm.timeout,
        )
        self._system = _load_skill()


    def extract(self, 
            query: str, 
            history:   str,
            memory: str, 
            resources: str
            ) -> IntentResult:
        """
        Args:
            query: entrada bruta do usuário.

        Returns:
            Objective | ClarificationNeeded

        Raises:
            OllamaError:    falha de comunicação com o servidor.
            ValueError:     LLM retornou JSON que não encaixa em nenhum schema.
        """
        raw = self._llm_extraxct(query, history, memory, resources)


        return 
    
    def _llm_extract(self,
        query:     str,
        history:   str | None,
        memory:    str | None,
        resources: str | None,
        ) -> str:


# ---------------------------------------------------------------------------
#   Testes embutidos
# ---------------------------------------------------------------------------

def _run_tests(host: str = "http://localhost:11434", model: str = "llama3.2") -> None:
    """
    Executa dois casos de teste diretamente contra o Ollama local.
    Rode com:  python -m axon.pa.intent_extractor
    """
    client    = OllamaClient(host=host, model=model)
    extractor = IntentExtractor(client)

    cases = [
        # deve retornar Objective
        "Create a 5-slide pitch deck about our Q3 results for investors",
        # deve retornar ClarificationNeeded
        "help me with my project",
    ]

    for query in cases:
        print(f"\n{'─'*60}")
        print(f"QUERY : {query!r}")
        try:
            result = extractor.extract(query)
            kind   = type(result).__name__
            print(f"TYPE  : {kind}")
            print(f"RESULT:\n{result.model_dump_json(indent=2)}")
        except (OllamaError, ValueError) as exc:
            print(f"ERROR : {exc}")

    print(f"\n{'─'*60}")


if __name__ == "__main__":
    import sys

    host  = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:11434"
    model = sys.argv[2] if len(sys.argv) > 2 else "llama3.2"
    _run_tests(host=host, model=model)