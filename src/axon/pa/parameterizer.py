"""
pa/parameterizer.py — Parameterizer (late-binding de parâmetros)

O Decomposer monta params_template SEM conhecer o schema da tool escolhida, então
às vezes erra os nomes (ex.: {percentage, number} para calculate(expression)). No
momento da execução o Executor já sabe a tool e pode ler o input schema dela
(MCP list_tools). O Parameterizer usa esse schema para remontar os argumentos.

Política (bind-if-mismatch): o Executor só chama o Parameterizer quando os params
correntes NÃO conformam ao schema da tool — quando conformam (ex.: web_search com
`query`), nada de LLM. Saída restringida pelo próprio schema via Ollama `format`.

É um passo que o Executor DELEGA — mantém o Executor como "só executa".
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from axon.llms.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You build the arguments for a single tool call. Output a JSON object whose keys "
    "are the parameter names from the schema. Make each value VALID for its parameter's "
    "type and description and sufficient to accomplish the task. The available values may "
    "be incomplete, misnamed, or malformed — transform and correct them to fit the "
    "schema; do not copy them blindly. Never invent facts not present in the inputs. "
    "Output only the JSON object."
)

_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


class ParameterizationError(Exception):
    """O binder não conseguiu produzir argumentos válidos para a tool."""


def conforms(params: dict[str, Any], schema: dict[str, Any]) -> bool:
    """
    True se `params` satisfaz o input schema da tool o suficiente para chamar:
      - todas as chaves `required` presentes;
      - se additionalProperties=false, nenhuma chave fora de `properties`.

    Checagem leve (presença/forma), não validação de tipos — o objetivo é decidir
    se vale a pena re-parametrizar, não validar exaustivamente.
    """
    props    = schema.get("properties", {})
    required = schema.get("required", [])
    if any(r not in params for r in required):
        return False
    if schema.get("additionalProperties") is False:
        if any(k not in props for k in params):
            return False
    return True


class Parameterizer:
    """Remonta argumentos de uma tool a partir do input schema dela (chamada LLM)."""

    def __init__(self, llm: OllamaClient) -> None:
        self._llm = llm

    def bind(
        self,
        *,
        tool_name:    str,
        input_schema: dict[str, Any],
        intent:       str,
        available:    dict[str, Any],
    ) -> dict[str, Any]:
        """
        Produz um dict de argumentos conforme `input_schema`.

        Raises:
            ParameterizationError: se a resposta não for um objeto JSON válido.
        """
        prompt = (
            f"Task to accomplish: {intent}\n\n"
            f"Tool: {tool_name}\n"
            f"Parameter schema (JSON Schema — follow each parameter's type and description):\n"
            f"{json.dumps(input_schema, ensure_ascii=False)}\n\n"
            f"Available raw values (may be misnamed or malformed — correct them): "
            f"{json.dumps(available, default=str, ensure_ascii=False)}\n\n"
            "Build the JSON arguments object that accomplishes the task. Use only the "
            "parameter names from the schema, and make each value valid for its description."
        )
        raw = self._llm.generate(
            prompt,
            system=_SYSTEM,
            temperature=0.0,
            format=input_schema,   # Ollama restringe a saída ao schema da tool
            think=False,
            retries=2,
        )
        data = _parse_obj(raw)
        if not isinstance(data, dict):
            raise ParameterizationError(
                f"parameter binding for '{tool_name}' did not return a JSON object"
            )
        logger.info("[Parameterizer] bound %s → %s", tool_name, sorted(data))
        return data


def _parse_obj(raw: str) -> Any:
    """json.loads direto; senão extrai o primeiro objeto {...} do texto."""
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = _JSON_OBJ_RE.search(raw)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError as e:
                raise ParameterizationError(f"invalid JSON from binder: {e}") from e
    raise ParameterizationError("binder returned no JSON object")
