"""
pa/decomposer.py — Decomposer (ReWOO)

Segunda etapa do pipeline do PA.

Responsabilidade:
  Traduzir um Objective em uma lista de Subtasks com params_template
  completo usando {{artifact:name}} para referenciar outputs anteriores.

ReWOO — todo o plano é construído antes de qualquer execução.
  Cada subtask declara entradas e saídas explicitamente.
  O Executor apenas executa — sem raciocinar sobre dependências.

Separação de responsabilidades:
  pa/skills/decomposer.md  → BEHAVIOR (operador edita)
  decomposer.py            → OUTPUT_CONTRACT + lógica de parse + capability matching
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from axon.config import PAConfig, LLMConfig
from axon.llms.ollama_client import OllamaClient, OllamaConnectionError, OllamaParseError
from axon.pa.models import (
    ExecutionStrategy,
    Objective,
    Plan,
    Subtask,
    SubtaskStatus,
)
from axon.types import ResourceManifest

logger = logging.getLogger(__name__)

# ── Skill ─────────────────────────────────────────────────────────────────────

_SKILL_PATH = Path(__file__).parent / "skills" / "decomposer.md"


def _load_behavior() -> str:
    return _SKILL_PATH.read_text(encoding="utf-8").strip()


# ── Output contract — hardcoded ───────────────────────────────────────────────

_OUTPUT_CONTRACT = """
---

Always produce exactly two blocks:

BLOCK 1 — Reasoning
<think>
Step-by-step reasoning about the decomposition.
</think>

BLOCK 2 — Subtask list
<output>
[
  {
    "id": "subtask-<n>",
    "description": "<what this subtask does>",
    "capability_required": "<exact capability tag from Available Resources, or natural language if not available>",
    "input_artifacts": ["<artifact_name_from_previous_subtask>"],
    "output_artifact": "<short_descriptive_name>",
    "params_template": {
      "<param_name>": "<concrete value or {{artifact:output_artifact_name}}>"
    },
    "depends_on": ["<subtask-id-whose-output-is-referenced>"],
    "is_optional": false
  }
]
</output>

Output rules (enforced by parser — do not change):
- Always produce both <think> and <output> blocks.
- params_template must be fully specified. No vague values like "previous output".
  Use {{artifact:name}} to reference a previous subtask's output_artifact.
- depends_on must list exactly the subtask ids referenced via {{artifact:name}} in params_template.
- output_artifact must be unique within the plan and follow snake_case.
- The first subtask has no input_artifacts and no depends_on.
- capability_required: use exact name from Available Resources when the capability exists there.
  If no resource matches, use a short descriptive tag — the Resolver will query the GA.
- is_optional: true only when the subtask genuinely does not affect the main result.
""".strip()


# ── Context template — hardcoded ──────────────────────────────────────────────

_CONTEXT_TEMPLATE = """
--- Objective ---
goal: {goal}
success: {success_definition}
{constraints_block}
{inputs_block}

--- Available Resources ---
{resources}

--- User Memory ---
{memory}

--- Instructions ---
Decompose the objective into a minimal list of subtasks following ReWOO strategy.
Build the complete execution plan upfront — params_template must be fully specified.
""".strip()


def _build_prompt(behavior: str) -> str:
    return f"{behavior}\n\n{_OUTPUT_CONTRACT}"


def _subtask_schema() -> dict:
    from pydantic import RootModel
    class SubtaskList(RootModel[list[Subtask]]):
        pass
    return SubtaskList.model_json_schema()


# ── Context builder ───────────────────────────────────────────────────────────

def _build_context(
    objective:     Objective,
    resource_pool: list[ResourceManifest],
    memory:        str = "No user memory available.",
) -> str:
    constraints_block = ""
    if objective.constraints:
        lines = [f"- [{c.type}] {c.value}" for c in objective.constraints]
        constraints_block = "constraints:\n" + "\n".join(lines)

    inputs_block = ""
    if objective.extracted_inputs:
        lines = [f"- {k}: {v}" for k, v in objective.extracted_inputs.items()]
        inputs_block = "extracted inputs:\n" + "\n".join(lines)

    # resources: capability tags disponíveis
    if resource_pool:
        res_lines = []
        for m in resource_pool:
            tags = ", ".join(m.capability_tags)
            res_lines.append(f"- {m.name} [{tags}]: {m.description}")
        resources = "\n".join(res_lines)
    else:
        resources = "No resources available in local pool — Resolver will query the GA."

    return _CONTEXT_TEMPLATE.format(
        goal=objective.goal,
        success_definition=objective.success_definition,
        constraints_block=constraints_block,
        inputs_block=inputs_block,
        resources=resources,
        memory=memory,
    )


# ── Capability matching ───────────────────────────────────────────────────────

def _normalize_capabilities(resource_pool: list[ResourceManifest]) -> set[str]:
    return {tag for m in resource_pool for tag in m.capability_tags}


def _match_capability(raw: str, available: set[str]) -> str:
    """
    Se capability_required existe no pool → retorna exato.
    Se não existe → mantém como linguagem natural para o Resolver buscar no GA.
    """
    if raw in available:
        return raw
    # tentativa de match parcial case-insensitive
    raw_lower = raw.lower()
    for cap in available:
        if cap.lower() == raw_lower:
            return cap
    return raw  # mantém — Resolver vai ao GA


# ── Decomposer ────────────────────────────────────────────────────────────────

class Decomposer:
    """
    Transforma um Objective em uma lista de Subtasks (ReWOO).

    O plano completo é gerado antes de qualquer execução.
    O Executor apenas executa — sem raciocinar sobre dependências.
    """

    def __init__(self, config: PAConfig) -> None:
        self._client = OllamaClient(
            host=config.llm.host,
            model=config.llm.model,
            timeout=config.llm.timeout,
        )
        behavior      = _load_behavior()
        self._system  = _build_prompt(behavior)
        self._schema  = _subtask_schema()

        logger.debug("[Decomposer] initialized — model=%s", config.llm.model)

    def decompose(self, state: "AgentState") -> None:  # type: ignore[name-defined]
        """
        Decompõe o Objective do AgentState em um Plan com Subtasks ReWOO.

        Lê state.objective e state.resource_pool — que já devem estar
        populados pelo agent.py antes desta chamada.

        Args:
            state: AgentState com objective e resource_pool preenchidos

        Escreve:
            state.plan
        """
        from axon.pa.models import AgentState

        objective = state.objective
        if objective is None:
            raise ValueError("AgentState.objective must be set before decompose()")

        pool     = state.resource_pool or []
        context  = _build_context(objective, pool)
        raw      = self._llm_decompose(context)
        subtasks = self._parse(raw, pool)
        state.plan = Plan(subtasks=subtasks)

    # ── LLM ──────────────────────────────────────────────────────────────────

    def _llm_decompose(self, context: str) -> str:
        try:
            raw = self._client.generate(
                context,
                system=self._system,
                temperature=0.0,
                format=None,    # schema livre — parser cascade cuida do resto
                think=True,     # raciocínio livre melhora depends_on e params
                retries=2,
            )
            logger.debug("[Decomposer] raw response:\n%s", raw)
            return raw
        except OllamaConnectionError:
            logger.error("[Decomposer] LLM unreachable")
            raise
        except OllamaParseError as e:
            logger.error("[Decomposer] parse error after retries: %s", e)
            raise

    # ── Parse ─────────────────────────────────────────────────────────────────

    def _parse(self, raw: str, resource_pool: list[ResourceManifest]) -> list[Subtask]:
        """
        Cascata:
          1. json.loads() direto
          2. <output>...</output>
          3. ```json ... ```
          4. bare JSON array
          5. fallback com motivo explícito
        """
        available = _normalize_capabilities(resource_pool)

        # nível 1 — array direto
        json_str = _try_direct_array(raw)

        # nível 2 — tag <output>
        if not json_str:
            json_str = _extract_tag(raw, "output")
            if json_str:
                logger.debug("[Decomposer] extracted from <output> tag")

        # nível 3 — markdown json
        if not json_str:
            json_str = _extract_markdown_json(raw)
            if json_str:
                logger.warning("[Decomposer] markdown json fallback used")

        # nível 4 — bare array no texto
        if not json_str:
            json_str = _extract_bare_array(raw)
            if json_str:
                logger.warning("[Decomposer] bare array fallback used")

        if not json_str:
            logger.warning(
                "[Decomposer] all parse levels failed — raw response (first 500 chars):\n%s",
                raw[:500],
            )
            return _fallback_plan("LLM response did not contain a valid JSON array")

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning("[Decomposer] JSON decode failed: %s\nExtracted: %s", e, json_str[:300])
            return _fallback_plan(f"JSON decode error: {e}")

        # normaliza wrapper {"subtasks": [...]}
        if not isinstance(data, list):
            if isinstance(data, dict):
                data = (
                    data.get("subtasks")
                    or data.get("tasks")
                    or data.get("steps")
                    or data.get("root")
                    or []
                )
            if not isinstance(data, list):
                logger.warning("[Decomposer] expected list, got %s — raw: %s", type(data).__name__, json_str[:200])
                return _fallback_plan(f"unexpected JSON shape: {type(data).__name__}")

        subtasks: list[Subtask] = []
        validation_errors: list[str] = []

        for i, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            try:
                if not item.get("id"):
                    item["id"] = f"subtask-{i + 1}"

                cap = item.get("capability_required", "")
                item["capability_required"] = _match_capability(cap, available)

                item["execution_strategy"] = ExecutionStrategy.REWOO.value
                item["status"]             = SubtaskStatus.PENDING.value

                subtasks.append(Subtask(**item))
            except (ValidationError, TypeError) as e:
                msg = f"item {i} ({item.get('id', '?')}): {e}"
                validation_errors.append(msg)
                logger.warning("[Decomposer] Subtask validation failed — %s", msg)

        if validation_errors and not subtasks:
            reason = f"{len(validation_errors)} subtask(s) failed validation: {validation_errors[0]}"
            return _fallback_plan(reason)

        if not subtasks:
            return _fallback_plan("LLM returned an empty subtask list")

        if validation_errors:
            logger.warning(
                "[Decomposer] %d/%d subtask(s) failed validation — proceeding with %d valid",
                len(validation_errors), len(data), len(subtasks),
            )

        return subtasks


# ── Parse helpers ─────────────────────────────────────────────────────────────

def _try_direct_array(text: str) -> str | None:
    stripped = text.strip()
    if stripped.startswith("["):
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
        return _extract_bare_array(content) or content
    return None


def _extract_markdown_json(text: str) -> str | None:
    match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if match:
        logger.warning("[Decomposer] markdown json fallback used")
        return match.group(1)
    return None


def _extract_bare_array(text: str) -> str | None:
    for m in re.finditer(r"\[", text):
        start, depth = m.start(), 0
        in_str, esc = False, False
        for i, ch in enumerate(text[start:], start):
            if esc:
                esc = False; continue
            if ch == "\\": esc = True; continue
            if ch == '"': in_str = not in_str; continue
            if in_str: continue
            if ch == "[": depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    candidate = text[start: i + 1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        break
    return None


def _fallback_plan(reason: str = "unknown error") -> list[Subtask]:
    logger.error("[Decomposer] fallback plan — reason: %s", reason)
    return [
        Subtask(
            id="subtask-fallback",
            description=f"Decomposition failed: {reason}. Please rephrase your query.",
            capability_required="general",
            params_template={},
            execution_strategy=ExecutionStrategy.REWOO,
            status=SubtaskStatus.FAILED,
        )
    ]


# ── CLI test ──────────────────────────────────────────────────────────────────

def _run_tests(
    host:  str = "http://localhost:11434",
    model: str = "deepseek-r1:14b",
) -> None:
    """
    POC embutida — rode com: python -m axon.pa.decomposer

    Simula dois cenários:
      1. Goal simples    — 1-2 subtasks
      2. Goal composto   — 4-5 subtasks com artefatos encadeados
    """
    from axon.pa.models import Constraint
    from axon.types import AuthConfig, AuthScheme, ProtocolBinding, ResourceType

    config     = PAConfig(llm=LLMConfig(host=host, model=model))
    decomposer = Decomposer(config)

    # pool simulado
    pool = [
        ResourceManifest(
            resource_id="health-search",
            name="health_search",
            type=ResourceType.mcp,
            protocol_binding=ProtocolBinding.MCP_HTTP,
            description="Searches patient data from HStory EHR",
            capability_tags=["patient_data_retrieval", "health_search"],
            callable_by="pa_direct",
            endpoint="http://health-search:8002",
        ),
        ResourceManifest(
            resource_id="healthcare-agent-1",
            name="healthcare_agent",
            type=ResourceType.agent,
            protocol_binding=ProtocolBinding.HTTP_JSON,
            description="Analyzes clinical data and produces diagnoses",
            capability_tags=["clinical_analysis", "health_analysis"],
            callable_by="pa_direct",
            endpoint="http://healthcare-agent:8001",
        ),
        ResourceManifest(
            resource_id="content-creator-1",
            name="content_creator",
            type=ResourceType.agent,
            protocol_binding=ProtocolBinding.HTTP_JSON,
            description="Generates formatted documents and reports",
            capability_tags=["report_generation", "document_creation"],
            callable_by="pa_direct",
            endpoint="http://content-creator:8003",
        ),
    ]

    cases = [
        Objective(
            goal="search patient João data in HStory and generate a clinical report",
            success_definition="A clinical report with patient data is delivered",
            capability_hints=["patient_data_retrieval", "clinical_analysis", "report_generation"],
            extracted_inputs={"patient_name": "João"},
        ),
        Objective(
            goal="analyze Q3 sales data from the uploaded CSV and generate a PDF report with charts",
            success_definition="PDF report with Q3 analysis and charts is ready",
            constraints=[Constraint(value="PDF format", type="format", source="query")],
            capability_hints=["file_reading", "data_analysis", "report_generation"],
            extracted_inputs={"file": "q3_sales.csv", "format": "PDF"},
        ),
    ]

    for obj in cases:
        print(f"\n{'─' * 64}")
        print(f"GOAL: {obj.goal!r}")
        try:
            from axon.pa.models import AgentState
            state = AgentState(raw_query=obj.goal, objective=obj, resource_pool=pool)
            decomposer.decompose(state)
            plan = state.plan
            print(f"SUBTASKS ({len(plan.subtasks)}):")
            for s in plan.subtasks:
                print(f"\n  [{s.id}] {s.description}")
                print(f"    capability : {s.capability_required}")
                print(f"    output     : {s.output_artifact or '—'}")
                if s.input_artifacts:
                    print(f"    inputs     : {', '.join(s.input_artifacts)}")
                if s.depends_on:
                    print(f"    depends_on : {', '.join(s.depends_on)}")
                if s.params_template:
                    for k, v in s.params_template.items():
                        print(f"    param [{k}] : {v}")
        except Exception as exc:
            print(f"ERROR: {type(exc).__name__}: {exc}")

    print(f"\n{'─' * 64}")


if __name__ == "__main__":
    import sys, logging
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s — %(message)s")
    host  = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:11434"
    model = sys.argv[2] if len(sys.argv) > 2 else "deepseek-r1:14b"
    _run_tests(host=host, model=model)