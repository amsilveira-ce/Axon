"""
pa/intent_extractor.py — Primeira etapa do pipeline do Principal Agent.

Separação de responsabilidades:
  pa/skills/intent_extraction.md  → BEHAVIOR (operador edita livremente)
  intent_extractor.py             → OUTPUT_CONTRACT + lógica de extração
  pa/context/assembler.py         → CONTEXT_TEMPLATE + budget de tokens

Fluxo:
  PromptAssembler.build()  → contexto formatado com budget
  _llm_extract()           → generate() com JSON Schema do Objective
  _parse()                 → parse em cascata com fallback robusto
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from pydantic import ValidationError

from axon.config import PAConfig, LLMConfig
from axon.llms.ollama_client import OllamaClient, OllamaConnectionError, OllamaParseError
from axon.pa.context.assembler import PromptAssembler
from axon.pa.context.conversation import ConversationHistory
from axon.pa.context.memory import MemoryBank
from axon.pa.models import Constraint, Objective, ClarificationNeeded, ClarificationQuestion

logger = logging.getLogger(__name__)

# ── Skill ─────────────────────────────────────────────────────────────────────

_SKILL_PATH  = Path(__file__).parent / "skills" / "intent_extraction.md"
_DOMAINS_DIR = Path(__file__).parent / "skills" / "domains"


def _load_behavior(domain: str | None = None) -> str:
    base = _SKILL_PATH.read_text(encoding="utf-8").strip()
    if domain is None:
        return base
    domain_path = _DOMAINS_DIR / f"{domain}.md"
    if not domain_path.exists():
        raise FileNotFoundError(
            f"Domain skill not found: {domain_path}\n"
            f"Create pa/skills/domains/{domain}.md to define this domain."
        )
    extension = domain_path.read_text(encoding="utf-8").strip()
    logger.info("[IntentExtractor] domain loaded: %s", domain)
    return f"{base}\n\n--- Domain Context ---\n{extension}"


# ── Output contract — hardcoded 
# Ao inves de deixar tudo orgnizado no .md mantemos a estrutura mais importante para que o Axon funcione
# harcoded aqui, no caso o output; Já que o controle inteno é feito através dos objetos Objective| ClarificationNeeded 

# Nos testes o <think> não está funcionando direto 

_OUTPUT_CONTRACT = """
---

Always produce exactly two blocks in your response:

BLOCK 1 — Reasoning
<think>
Your step-by-step reasoning about the query.
</think>

BLOCK 2 — Structured output
<output>
{
  "goal": "<verb + object + context — full phrase, not just a verb>",
  "constraints": [
    {"value": "<constraint>", "type": "<temporal|size|policy|format>", "implicit": false, "source": "<phrase from query>"}
  ],
  "success_definition": "<verifiable condition that means the task is complete>",
  "capability_hints": ["<capability_tag>"],
  "extracted_inputs": {"<slot>": "<value explicitly stated in query>"},
  "assumptions": ["<default from memory or context — never invented>"],
  "clarification": null
}
</output>

When clarification is needed, replace clarification null with:
{
  "context": "<one sentence: what you already understood>",
  "questions": [
    {
      "question": "<specific question targeting one missing piece>",
      "ambiguous_span": "<exact phrase from query that triggered this>",
      "options": ["<opt1>", "<opt2>"] or null
    }
  ]
}

Output rules (enforced by parser — do not change):
- Always produce both <think> and <output> blocks.
- goal: full phrase. WRONG: "create". RIGHT: "create 5-slide pitch deck about Q3 for investors".
- constraints: only restrictions on HOW to execute. Do NOT copy extracted_inputs here.
- extracted_inputs: only information explicitly stated in the query.
- assumptions: only defaults from Memory or context. Never invent.
- clarification null = proceed. clarification filled = needs user input.
- Do not ask about information that Available Resources can retrieve autonomously.
""".strip()


def _build_prompt(behavior: str) -> str:
    return f"{behavior}\n\n{_OUTPUT_CONTRACT}"


def _objective_schema() -> dict:
    return Objective.model_json_schema()


# ── IntentExtractor 

class IntentExtractor:
    """
    Produz sempre um Objective. Opera em inglês.

    O contexto é montado pelo PromptAssembler — que gerencia o budget
    de tokens entre history, memory e resources.

    objective.clarification is None     → completo, vai para o Decomposer
    objective.clarification is not None → incompleto, pergunta ao usuário
    """

    def __init__(self, config: PAConfig) -> None:
        self._client = OllamaClient(
            host=config.llm.host,
            model=config.llm.model,
            timeout=config.llm.timeout,
        )
        domain        = getattr(config.intent_extractor, "domain", None)
        behavior      = _load_behavior(domain)

        self._system  = _build_prompt(behavior)
        self._schema  = _objective_schema()
        self._assembler = PromptAssembler(config.conversation)

        logger.debug(
            "[IntentExtractor] initialized — model=%s domain=%s",
            config.llm.model,
            domain,
        )

    def extract(
        self,
        query:     str,
        history:   ConversationHistory | None = None,
        memory:    MemoryBank | None          = None,
        resources: list[str] | None           = None,
    ) -> Objective:
        """
        Extrai a intenção da query e retorna um Objective.

        Args:
            query:     query do usuário em inglês
            history:   ConversationHistory da sessão atual
            memory:    MemoryBank cross-session
            resources: lista de capability tags disponíveis
        """
        
        context = self._assembler.build(
            query,
            history=history,
            memory=memory,
            resources=resources,
        )

        raw = self._llm_extract(context)
        return self._parse(query, raw)

    def _llm_extract(self, context: str) -> str:
        try:
            raw = self._client.generate(
                context,
                system=self._system,
                temperature=0.0,
                format=self._schema,
                think=False,
                retries=2,
            )
            logger.debug("[IntentExtractor] raw:\n%s", raw)
            return raw

        except OllamaConnectionError:
            logger.error("[IntentExtractor] LLM unreachable")
            raise
        except OllamaParseError as e:
            logger.error("[IntentExtractor] parse error after retries: %s", e)
            raise


    def _parse(self, query: str, raw: str) -> Objective:
        json_str = (
            _try_direct(raw)
            or _extract_tag(raw, "output")
            or _extract_markdown_json(raw)
            or _extract_bare_json(raw)
        )

        if not json_str:
            logger.warning("[IntentExtractor] could not extract JSON — fallback")
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


# ── Parse helpers - para parser saida da llm 

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
        logger.warning("[IntentExtractor] markdown json fallback used")
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


def _fallback_objective(query: str) -> Objective:
    return Objective(
        goal="",
        constraints=[],
        success_definition="",
        capability_hints=[],
        extracted_inputs={},
        assumptions=[],
        clarification=ClarificationNeeded(
            context="I could not understand your request.",
            questions=[
                ClarificationQuestion(
                    question="Could you rephrase your request with more details?",
                    ambiguous_span=query,
                    options=None,
                )
            ],
        ),
    )


# teste local - rodar esse arquivo como main 

def _run_tests(
    host:   str        = "http://localhost:11434",
    model:  str        = "deepseek-r1:14b",
    domain: str | None = None,
) -> None:
    """
    Rode com:
      python -m axon.pa.intent_extractor
      python -m axon.pa.intent_extractor http://localhost:11434 deepseek-r1:14b clinical
    """
    config    = PAConfig(llm=LLMConfig(host=host, model=model))
    extractor = IntentExtractor(config)

    cases = [
        "Create a 5-slide pitch deck about Q3 results for investors using last quarter revenue data",
        "Analyze patient João's data and generate a clinical report",
        "Create an Excel spreadsheet about ducks",
        "Help me with my project",
    ]

    for query in cases:
        print(f"\n{'─' * 60}")
        print(f"QUERY: {query!r}")
        try:
            obj = extractor.extract(query)

            if obj.clarification is None:
                print("STATUS: ✓ READY → Decomposer")
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
                print("STATUS: ✗ NEEDS CLARIFICATION")
                print(f"  goal so far  : {obj.goal or '(unclear)'}")
                print(f"  context      : {obj.clarification.context}")
                print(f"  questions ({len(obj.clarification.questions)}):")
                for i, q in enumerate(obj.clarification.questions, 1):
                    print(f"    {i}. {q.question}")
                    if q.options:
                        for opt in q.options:
                            print(f"       • {opt}")

        except FileNotFoundError as exc:
            print(f"CONFIG ERROR: {exc}")
        except Exception as exc:
            print(f"ERROR: {type(exc).__name__}: {exc}")

    print(f"\n{'─' * 60}")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s — %(message)s")
    host   = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:11434"
    model  = sys.argv[2] if len(sys.argv) > 2 else "deepseek-r1:14b"
    domain = sys.argv[3] if len(sys.argv) > 3 else None
    _run_tests(host=host, model=model, domain=domain)