"""
pa/intent_extractor.py — Primeira etapa do pipeline do Principal Agent.

Responsabilidade:
  Transformar uma query em linguagem natural em um Objective estruturado.
  O Objective é sempre produzido — quando a query está incompleta,
  o campo clarification é preenchido com perguntas ao usuário.

Idioma:
  Detecta o idioma da query via langdetect e injeta no system prompt
  como primeira instrução — antes de qualquer outra coisa.
  Isso garante que goal, clarification e todos os campos do JSON
  saiam no mesmo idioma da query, independente do modelo ou do prompt.

Structured output:
  Passa o JSON Schema do Objective no format= do Ollama.
  think=False suprime o <think> block em reasoning models.
  Parse em cascata com 5 níveis de fallback.

Skill:
  pa/skills/intent_extraction.md — system prompt e context template.
  O placeholder {language} no topo do prompt é preenchido em runtime.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from pydantic import ValidationError

from axon.llms.ollama_client import OllamaClient, OllamaConnectionError, OllamaError, OllamaParseError
from axon.config import PAConfig, LLMConfig
from axon.pa.models import Constraint, Objective, ClarificationNeeded, ClarificationQuestion

logger = logging.getLogger(__name__)

# ── Detecção de idioma ────────────────────────────────────────────────────────

# Mapa langdetect → nome legível pelo LLM
_LANG_NAMES: dict[str, str] = {
    "pt": "Portuguese",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "zh-cn": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "ar": "Arabic",
}

_MIN_QUERY_LENGTH = 8   # queries menores que isso são instáveis para detecção


def detect_language(text: str) -> str:
    """
    Detecta o idioma do texto e retorna o nome legível pelo LLM.

    Fallback para "English" quando:
      - langdetect não está instalado
      - texto muito curto (instável)
      - código de idioma não mapeado
    """
    if len(text.strip()) < _MIN_QUERY_LENGTH:
        return "English"

    try:
        # usando langdetect para manter consistência da saida utilizada pela llm 
        from langdetect import detect, DetectorFactory
        DetectorFactory.seed = 0   # resultado determinístico
        code = detect(text)
        return _LANG_NAMES.get(code, "English")
    
    except Exception:
        return "English"


# ── Skill ─────────────────────────────────────────────────────────────────────

_SKILL_PATH = Path(__file__).parent / "skills" / "intent_extraction.md"


def _load_skill() -> tuple[str, str]:
    """
    Carrega pa/skills/intent_extraction.md.
    Retorna (system_prompt_template, context_template).
    As duas seções são separadas por linha '---'.
    O system_prompt_template contém {language} para injeção em runtime.
    """
    raw = _SKILL_PATH.read_text(encoding="utf-8")
    parts = raw.split("\n---\n", maxsplit=1)
    if len(parts) != 2:
        raise ValueError(
            f"intent_extraction.md deve ter duas seções separadas por '---'. "
            f"Seções encontradas: {len(parts)}"
        )
    system_prompt_template = parts[0].strip()
    context_template       = parts[1].strip()

    # remove cabeçalho "# Context Template" se presente
    lines = context_template.splitlines()
    if lines and lines[0].startswith("#"):
        context_template = "\n".join(lines[1:]).strip()

    return system_prompt_template, context_template


# ── JSON Schema do Objective ──────────────────────────────────────────────────

def _objective_schema() -> dict:
    return Objective.model_json_schema()


# ── Contexto simulado para testes ─────────────────────────────────────────────

SIMULATED_HISTORY = "No previous conversation."

SIMULATED_MEMORY = """
- preferred_report_format: PDF
- data_source: HStory electronic health record system (Hospital Einstein)
- language: Portuguese (Brazil)
- patient_data_always_available: true
""".strip()

SIMULATED_RESOURCES = """
- health_search: searches patient data from HStory EHR (capability: patient_data_retrieval)
- healthcare_agent: analyzes clinical data and produces diagnoses (capability: clinical_analysis)
- content_creator: generates formatted documents and reports (capability: report_generation)
- resend: sends emails to medical staff (capability: email_delivery)
- notion: persists documents to workspace (capability: document_storage)
""".strip()


# ── IntentExtractor ───────────────────────────────────────────────────────────

class IntentExtractor:
    """
    Produz sempre um Objective.
    objective.clarification is None     → completo, vai para o Decomposer
    objective.clarification is not None → incompleto, pergunta ao usuário
    """

    def __init__(self, config: PAConfig) -> None:
        self._client = OllamaClient(
            host=config.llm.host,
            model=config.llm.model,
            timeout=config.llm.timeout,
        )
        self._system_prompt_template, self._context_template = _load_skill()
        self._schema = _objective_schema()

    def extract(
        self,
        query:     str,
        history:   str | None = None,
        memory:    str | None = None,
        resources: str | None = None,
    ) -> Objective:
        """
        Extrai a intenção da query e retorna um Objective.

        Args:
            query:     query do usuário em linguagem natural
            history:   ConversationHistory.get_context() (ou None → simulado)
            memory:    MemoryBank.get_summary() (ou None → simulado)
            resources: resource_pool serializado (ou None → simulado)
        """
        raw = self._llm_extract(query, history, memory, resources)
        return self._parse(query, raw)


    def _llm_extract(
        self,
        query:     str,
        history:   str | None,
        memory:    str | None,
        resources: str | None,
    ) -> str:
        # detecta idioma e monta system prompt com idioma no topo
        # usa replace() em vez de format() — o template contém chaves literais
        # nos exemplos de JSON que format() interpretaria como campos
        language      = detect_language(query)
        system_prompt = self._system_prompt_template.replace("{language}", language)

        logger.debug("[IntentExtractor] detected language: %s", language)

        context = self._context_template.format(
            history=history     or SIMULATED_HISTORY,
            memory=memory       or SIMULATED_MEMORY,
            resources=resources or SIMULATED_RESOURCES,
            query=query,
        )

        try:
            raw = self._client.generate(
                context,
                system=system_prompt,
                temperature=0.0,
                format=self._schema,
                think=False,
                retries=2,
            )
            logger.debug("[IntentExtractor] raw response:\n%s", raw)
            return raw

        except OllamaConnectionError:
            logger.error("[IntentExtractor] LLM unreachable")
            raise
        except OllamaParseError as e:
            logger.error("[IntentExtractor] LLM parse error after retries: %s", e)
            raise

    def _parse(self, query: str, raw: str) -> Objective:
        """
        Parse em cascata:
          1. json.loads() direto    → json_schema mode funcionou
          2. <output>...</output>   → reasoning model com think=True
          3. ```json ... ```        → modelo formatou em markdown
          4. bare JSON balanceado   → JSON solto no texto
          5. fallback               → pede reformulação
        """
        json_str = (
            _try_direct(raw)
            or _extract_tag(raw, "output")
            or _extract_markdown_json(raw)
            or _extract_bare_json(raw)
        )

        if not json_str:
            logger.warning("[IntentExtractor] Could not extract JSON — using fallback")
            return _fallback_objective(query)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning("[IntentExtractor] JSON decode failed: %s", e)
            return _fallback_objective(query)

        try:
            constraints = [
                Constraint(**c)
                for c in data.get("constraints", [])
                if isinstance(c, dict)
            ]

            clarification = None
            raw_clar = data.get("clarification")
            if isinstance(raw_clar, dict):
                questions = [
                    ClarificationQuestion(
                        question=q.get("question", ""),
                        ambiguous_span=q.get("ambiguous_span", ""),
                        options=q.get("options"),
                    )
                    for q in raw_clar.get("questions", [])
                    if isinstance(q, dict)
                ]
                if questions:
                    clarification = ClarificationNeeded(
                        context=raw_clar.get("context", ""),
                        questions=questions[:3],
                    )

            return Objective(
                goal=data.get("goal", ""),
                constraints=constraints,
                success_definition=data.get("success_definition", ""),
                capability_hints=data.get("capability_hints", []),
                extracted_inputs=data.get("extracted_inputs", {}),
                assumptions=data.get("assumptions", []),
                clarification=clarification,
            )

        except (ValidationError, TypeError) as e:
            logger.warning("[IntentExtractor] Objective build failed: %s", e)
            return _fallback_objective(query)


# == Helpers para lidar com parsing da saida da llm
def _try_direct(text: str) -> str | None:
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            json.loads(stripped)
            return stripped
        except json.JSONDecodeError:
            pass
    return None


def _extract_tag(text: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    if match:
        content = match.group(1).strip()
        return _extract_bare_json(content) or content
    return None


def _extract_markdown_json(text: str) -> str | None:
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        logger.warning("[IntentExtractor] Used markdown json fallback")
        return match.group(1)
    return None


def _extract_bare_json(text: str) -> str | None:
    for m in re.finditer(r"\{", text):
        start, depth = m.start(), 0
        in_str, esc = False, False
        for i, ch in enumerate(text[start:], start):
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start: i + 1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        break
    return None

# Caso não seja possivel extrair, nós temos uma mensagem de fallback para o usuário 
def _fallback_objective(query: str) -> Objective:
    lang = detect_language(query)
    if lang == "Portuguese":
        msg     = "Não consegui entender sua solicitação."
        question = "Pode reformular sua solicitação com mais detalhes?"
    else:
        msg      = "I could not understand your request."
        question = "Could you rephrase your request with more details?"

    return Objective(
        goal="",
        constraints=[],
        success_definition="",
        capability_hints=[],
        extracted_inputs={},
        assumptions=[],
        clarification=ClarificationNeeded(
            context=msg,
            questions=[
                ClarificationQuestion(
                    question=question,
                    ambiguous_span=query,
                    options=None,
                )
            ],
        ),
    )


# ── Testes 

def _run_tests(host: str = "http://localhost:11434", model: str = "deepseek-r1:14b") -> None:
    config    = PAConfig(llm=LLMConfig(host=host, model=model))
    extractor = IntentExtractor(config)

    cases = [
        "Create a 5-slide pitch deck about Q3 results for investors using last quarter revenue data",
        "analise os dados do paciente João e gere um relatório clínico",
        "Monte um excel sobre patos",
        "help me with my project",
        "crea una presentación sobre gatos para estudiantes",
    ]

    for query in cases:
        lang = detect_language(query)
        print(f"\n{'─' * 60}")
        print(f"QUERY   : {query!r}")
        print(f"LANG    : {lang}")
        try:
            obj = extractor.extract(query)

            if obj.clarification is None:
                print("STATUS  : ✓ READY → Decomposer")
                print(f"  goal         : {obj.goal}")
                print(f"  success      : {obj.success_definition}")
                if obj.capability_hints:
                    print(f"  capabilities : {', '.join(obj.capability_hints)}")
                if obj.extracted_inputs:
                    for k, v in obj.extracted_inputs.items():
                        print(f"  input [{k}]  : {v}")
                if obj.constraints:
                    for c in obj.constraints:
                        print(f"  constraint   : [{c.type}] {c.value}")
                if obj.assumptions:
                    for a in obj.assumptions:
                        print(f"  assumption   : {a}")
            else:
                print("STATUS  : ✗ NEEDS CLARIFICATION")
                print(f"  goal so far  : {obj.goal or '(unclear)'}")
                print(f"  context      : {obj.clarification.context}")
                print(f"  questions ({len(obj.clarification.questions)}):")
                for i, q in enumerate(obj.clarification.questions, 1):
                    print(f"    {i}. {q.question}")
                    if q.options:
                        for opt in q.options:
                            print(f"       • {opt}")

        except OllamaError as exc:
            print(f"ERROR   : {type(exc).__name__}: {exc}")

    print(f"\n{'─' * 60}")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s — %(message)s")
    host  = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:11434"
    model = sys.argv[2] if len(sys.argv) > 2 else "deepseek-r1:14b"
    _run_tests(host=host, model=model)