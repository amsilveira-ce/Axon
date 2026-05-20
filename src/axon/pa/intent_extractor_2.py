"""
pa/intent_extractor.py — Primeira etapa do pipeline do Principal Agent.

Responsabilidade:
  Transformar uma query em linguagem natural em um Objective estruturado.
  O Objective é sempre produzido — quando a query está incompleta,
  o campo clarification é preenchido com perguntas ao usuário.

Arquitetura:
  1. _llm_extract()  → reasoning model produz <think> + Objective JSON
  2. _parse()        → extrai JSON e constrói Objective
  3. agent.py verifica: objective.clarification is None → planeja
                        objective.clarification is not None → pergunta usuário

Modelo:
  Reasoning model via Ollama (DeepSeek-R1 ou equivalente).
  O <think> block vai para o logger — não entra no AgentState.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from axon.llms.ollama_client import OllamaClient, OllamaConnectionError, OllamaError, OllamaResponseError
from axon.config import PAConfig, LLMConfig
from axon.pa.models import Constraint, Objective, ClarificationNeeded, ClarificationQuestion

logger = logging.getLogger(__name__)



# ── Hardcoded context for testing ─────────────────────────────────────────────
# Simula o que virá de ConversationHistory, MemoryBank e resource_pool
# Substitua por valores reais quando os componentes estiverem prontos
 
SIMULATED_HISTORY = """
No previous conversation.
"""
 
SIMULATED_MEMORY = """
- preferred_report_format: PDF
- data_source: HStory electronic health record system (Hospital Einstein)
- language: Portuguese (Brazil)
- patient_data_always_available: true
"""
 
SIMULATED_RESOURCES = """
- health_search: searches patient data from HStory EHR (capability: patient_data_retrieval)
- healthcare_agent: analyzes clinical data and produces diagnoses (capability: clinical_analysis)
- content_creator: generates formatted documents and reports (capability: report_generation)
- resend: sends emails to medical staff (capability: email_delivery)
- notion: persists documents to workspace (capability: document_storage)
"""
 

# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are the intent extraction engine of a multi-agent orchestration system.

Your job: analyze the user's query and produce a structured Objective.

PART 1 — Write your reasoning inside <think> tags. Think freely step by step:
- What does the user want to do?
- What information is explicitly present in the query or context?
- What information is missing but required to act safely?
- For each missing input: what question should be asked? Are there 2-3 predictable options, or is it open-ended?
- What is ambiguous?
- Can the system proceed now, or does it need clarification first?

PART 2 — Write the Objective inside <output> tags.
If you have enough information to act: set clarification to null.
If you need more information: fill clarification with 1-3 specific questions from your PART 1 reasoning.
Do not infer information that is not explicitly present in the query or context.

<output>
{
  "goal": "<verb + object + context — e.g. 'create 5-slide pitch deck about Q3 results for investors'>",
  "constraints": [
    {"value": "<constraint>", "type": "<temporal|size|policy|format>", "implicit": false, "source": "<phrase>"}
  ],
  "success_definition": "<verifiable condition that means the task is complete>",
  "capability_hints": ["<capability_1>", "<capability_2>"],
  "extracted_inputs": {"<slot>": "<value>"},
  "assumptions": ["<assumption made from context — not invented>"],
  "clarification": null
}
</output>

When clarification is needed, replace null with:
{
  "context": "<what you understood so far>",
  "questions": [
    {
      "question": "<specific question derived from PART 1>",
      "ambiguous_span": "<exact phrase or slot name that triggered this question>",
      "options": ["<opt1>", "<opt2>", "<opt3>"] or null
    }
  ]
}

Rules:
- constraints: restrictions on HOW to execute (format, size, policy, deadline)
  Do NOT repeat extracted_inputs as constraints.
- extracted_inputs: only information explicitly provided by the user in the query
- assumptions: defaults from Memory or context that the system is using
- always produce both <think> and <output> blocks
- goal: full phrase with verb + object + context. WRONG: "create". RIGHT: "create presentation about cats for students"
- assumptions: only use information explicitly present in query, history, memory or resources
- options: 2-3 when domain is closed and predictable. null when open-ended
- clarification null = proceed. clarification filled = needs more info
- return ONLY the two blocks — no markdown, no explanation outside the tags
- Do not ask the user about information that Available Resources can retrieve autonomously. Only ask for information that 
only the user can provide.
""".strip()

CONTEXT_TEMPLATE = """
--- Conversation History ---
{history}
 
--- User Memory ---
{memory}
 
--- Available Resources ---
{resources}
 
--- User Query ---
{query}
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

    def extract(self,   query:     str,
        history:   str | None = None,
        memory:    str | None = None,
        resources: str | None = None,
        ) -> Objective:
        """
        Extrai a intenção da query e retorna um Objective.
 
        Args:
            query:     query do usuário em linguagem natural
            history:   ConversationHistory serializado (ou None)
            memory:    MemoryBank serializado (ou None)
            resources: resource_pool serializado (ou None)
 
        Quando None, usa os valores hardcoded de simulação.
        """
        raw = self._llm_extract(query, history, memory, resources)
        return self._parse(query, raw)

    # ── LLM ──────────────────────────────────────────────────────────────────

    def _llm_extract(self,
        query:     str,
        history:   str | None,
        memory:    str | None,
        resources: str | None,
        ) -> str:
        context = CONTEXT_TEMPLATE.format(
            history=history   or SIMULATED_HISTORY,
            memory=memory     or SIMULATED_MEMORY,
            resources=resources or SIMULATED_RESOURCES,
            query=query,
        )
        try:
            chunks: list[str] = []
            print("STREAM ▶ ", end="", flush=True)
            for piece in self._client.generate_stream(
                context,
                system=SYSTEM_PROMPT,
                format=None,
            ):
                chunks.append(piece)
                print(piece, end="", flush=True)
            print()  # newline ao fim do stream

            raw = "".join(chunks)
            logger.debug("[IntentExtractor] raw response:\n%s", raw)

            think = _extract_tag(raw, "think")
            if think:
                logger.debug("[IntentExtractor] <think>\n%s\n</think>", think)

            return raw
        except OllamaConnectionError:
            logger.error("[IntentExtractor] LLM unreachable")
            raise
        except OllamaResponseError as e:
            logger.error("[IntentExtractor] LLM response error: %s", e)
            raise

    # ── Parse ─────────────────────────────────────────────────────────────────

    def _parse(self, query: str, raw: str) -> Objective:
        """
        Extrai o JSON do response com três estratégias em cascata:
          1. <output>...</output>
          2. ```json ... ```
          3. Maior JSON object solto no texto
        Fallback: Objective vazio com clarification pedindo reformulação.
        """
        tag_content = _extract_tag(raw, "output")
        json_str = (
            _extract_bare_json(tag_content) if tag_content else None
        ) or _extract_markdown_json(raw) or _extract_bare_json(raw)
 
        if not json_str:
            logger.warning("[IntentExtractor] Could not extract JSON — using fallback")
            return _fallback_objective(query)
 
        try:
            data = json.loads(json_str)
 
            # parse constraints
            constraints = [
                Constraint(**c)
                for c in data.get("constraints", [])
                if isinstance(c, dict)
            ]
 
            # parse clarification
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
 
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            logger.warning("[IntentExtractor] Parse failed: %s", e)
            return _fallback_objective(query)
 
 
# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_tag(text: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return match.group(1).strip() if match else None


def _extract_markdown_json(text: str) -> str | None:
    match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if match:
        logger.warning("[IntentExtractor] Used markdown fallback")
        return match.group(1)
    return None


def _extract_bare_json(text: str) -> str | None:
    """Extrai o primeiro JSON object balanceado encontrado no texto (forward scan)."""
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
                    candidate = text[start:i + 1]
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


# ── Testes ────────────────────────────────────────────────────────────────────

def _run_tests(host: str = "http://localhost:11434", model: str = "deepseek-r1:14b") -> None:
    config    = PAConfig(llm=LLMConfig(host=host, model=model))
    extractor = IntentExtractor(config)

    cases = [
        
        "Create a 5-slide pitch deck about Q3 results for investors using last quarter revenue data",
        "analise os dados do paciente João e gere um relatório clínico",
    ]

    for query in cases:
        print(f"\n{'─' * 60}")
        print(f"QUERY: {query!r}")
        try:
            obj = extractor.extract(query)

            if obj.clarification is None:
                print("STATUS: ✓ READY → Decomposer")
                print(f"  goal             : {obj.goal}")
                print(f"  success          : {obj.success_definition}")
                if obj.capability_hints:
                    print(f"  capabilities     : {', '.join(obj.capability_hints)}")
                if obj.extracted_inputs:
                    for k, v in obj.extracted_inputs.items():
                        print(f"  input [{k}]  : {v}")
                if obj.constraints:
                    for c in obj.constraints:
                        print(f"  constraint       : [{c.type}] {c.value}")
                if obj.assumptions:
                    for a in obj.assumptions:
                        print(f"  assumption       : {a}")
            else:
                print("STATUS: ✗ NEEDS CLARIFICATION")
                print(f"  goal so far      : {obj.goal or '(unclear)'}")
                print(f"  context          : {obj.clarification.context}")
                print(f"  questions ({len(obj.clarification.questions)}):")
                for i, q in enumerate(obj.clarification.questions, 1):
                    print(f"    {i}. {q.question}")
                    if q.options:
                        for opt in q.options:
                            print(f"       • {opt}")

        except OllamaError as exc:
            print(f"ERROR: {type(exc).__name__}: {exc}")

    print(f"\n{'─' * 60}")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s — %(message)s")
    host  = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:11434"
    model = sys.argv[2] if len(sys.argv) > 2 else "deepseek-r1:14b"
    _run_tests(host=host, model=model)