from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError

from axon.llms.ollama_client import OllamaClient, OllamaError
from axon.pa.models import ClarificationNeeded, Objective, ClarificationQuestion, IntentResult
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

    def __init__(self, client: OllamaClient) -> None:
        self._client = client
        self._system = _load_skill()


    def extract(self, query: str) -> IntentResult:
        """
        Args:
            query: entrada bruta do usuário.

        Returns:
            Objective | ClarificationNeeded

        Raises:
            OllamaError:    falha de comunicação com o servidor.
            ValueError:     LLM retornou JSON que não encaixa em nenhum schema.
        """
        raw = self._client.chat(
            messages=[
                {"role": "system",  "content": self._system},
                {"role": "user",    "content": query},
            ],
            temperature=0.0,
            format="json",
        )

        return self._parse(raw, query)

    # ------------------------------------------------------------------
    #   Internals
    # ------------------------------------------------------------------

    def _parse(self, raw: str, query: str) -> IntentResult:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM returned invalid JSON: {exc}\nRaw: {raw!r}") from exc

        # Schema A: tem "goal" → Objective
        if "goal" in data:
            try:
                return Objective.model_validate(data)
            except ValidationError as exc:
                raise ValueError(f"Failed to parse Objective: {exc}") from exc

        # Schema B: tem "questions" → ClarificationNeeded
        if "questions" in data:
            try:
                return ClarificationNeeded.model_validate(data)
            except ValidationError as exc:
                raise ValueError(f"Failed to parse ClarificationNeeded: {exc}") from exc

        raise ValueError(
            f"LLM response does not match Objective or ClarificationNeeded.\n"
            f"Keys received: {list(data.keys())}\nQuery: {query!r}"
        )


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