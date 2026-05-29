"""
Complemento para pa/models.py
Adicione ao final do arquivo existente.
 
Importações necessárias no topo do arquivo:
  from datetime import datetime, timezone
  from uuid import uuid4
  from axon.types import ResourceManifest
"""
 
from __future__ import annotations
 
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4
from typing import Literal
from pydantic import BaseModel, Field
from axon.types import ResourceManifest


# ---------------------------------------------------------------------------
#   Constraint
# ---------------------------------------------------------------------------
# ajuda a llm a reconhecer "restrições" relacionada a tafera 
class Constraint(BaseModel):
    value:    str
    type:     Literal["temporal", "size", "policy", "format"]
    implicit: bool = False
    source:   str  = ""   # trecho da query que originou a constraint


# ---------------------------------------------------------------------------
#   Clarification — embutida no Objective
# ---------------------------------------------------------------------------

class ClarificationQuestion(BaseModel):
    question:       str
    ambiguous_span: str
    options:        list[str] | None = None


class ClarificationNeeded(BaseModel):
    questions: list[ClarificationQuestion]   # 1-3
    context:   str


# ---------------------------------------------------------------------------
#   Objective — único tipo de retorno do IntentExtractor
#
#   clarification is None     → completo, segue para o Decomposer
#   clarification is not None → incompleto, pergunta ao usuário
# ---------------------------------------------------------------------------

class Objective(BaseModel):
    goal:               str
    constraints:        list[Constraint]       = Field(default_factory=list)
    success_definition: str                    = ""
    capability_hints:   list[str]              = Field(default_factory=list)
    extracted_inputs:   dict[str, Any]         = Field(default_factory=dict)
    assumptions:        list[str]              = Field(default_factory=list)
    clarification:      ClarificationNeeded | None = None


# Alias para compatibilidade com agent.py e chat.py
IntentResult = Objective


# ---------------------------------------------------------------------------
#   ExtractionTrace — resultado + contexto injetado
# ---------------------------------------------------------------------------

class ExtractionTrace:
    """
    Carrega o contexto que foi injetado no prompt e o resultado.
    Usado pelo --verbose no CLI para mostrar o que o PA está vendo.
    """
    def __init__(
        self,
        objective: "Objective",
        context:   str,
        history_str:   str,
        memory_str:    str,
        resources_str: str,
    ) -> None:
        self.objective     = objective
        self.context       = context
        self.history_str   = history_str
        self.memory_str    = memory_str
        self.resources_str = resources_str





# ---------------------------------------------------------------------------
#   Enums de execução
# ---------------------------------------------------------------------------
 
class ExecutionStrategy(str, Enum):
    REACT  = "react"
    REWOO  = "rewoo"
 
 
class SubtaskStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    SKIPPED   = "skipped"
 
 
class Provenance(str, Enum):
    A2A   = "a2a"
    MCP   = "mcp"
    LOCAL = "local"
 
 
# ---------------------------------------------------------------------------
#   Plano
# ---------------------------------------------------------------------------
 
class Subtask(BaseModel):
    """
    Unidade mínima de trabalho do plano.
    Delegável a um único recurso.
    Contrato de entrada e saída via artefatos nomeados.
 
    params_template:
      ReAct  → vazio — Executor decide em runtime
      ReWOO  → completo — usa {{artifact:nome}} para referenciar outputs anteriores
    """
    id:                  str
    description:         str
    capability_required: str
 
    input_artifacts:     list[str]         = Field(default_factory=list)
    output_artifact:     str | None        = None
 
    params_template:     dict[str, Any]    = Field(default_factory=dict)
 
    execution_strategy:  ExecutionStrategy = ExecutionStrategy.REACT
    depends_on:          list[str]         = Field(default_factory=list)
    is_optional:         bool              = False
    status:              SubtaskStatus     = SubtaskStatus.PENDING
 
 
class Plan(BaseModel):
    """
    Output do Decomposer + Planner.
    depends_on preenchido pelo Planner via matching de artefatos.
    """
    subtasks: list[Subtask] = Field(default_factory=list)


class ResolverResult(BaseModel):
    """
    O que o Step 2 do Resolver retorna por capability — o recurso escolhido via
    Gateway Agent, mais fallbacks e os sinais que alimentam o GAAffinityStore.

    match_score + latency_ms vão para GAAffinityStore.update_partial();
    o ga_url identifica qual gateway recompensar/penalizar.
    """
    capability:   str
    subtask_id:   str
    manifest:     ResourceManifest              # melhor match
    alternatives: list[ResourceManifest] = Field(default_factory=list)  # fallbacks
    ga_url:       str                           # de onde veio
    match_score:  float = 0.0
    latency_ms:   float = 0.0

# ---------------------------------------------------------------------------
#   Execução — append-only
# ---------------------------------------------------------------------------
 
class Fact(BaseModel):
    """
    Resultado de uma subtask bem sucedida.
    Append-only — nunca modificado após criação.
    """
    subtask_id:  str
    tool:        str
    output:      Any
    provenance:  Provenance
    timestamp:   datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
 
 
class Failure(BaseModel):
    """
    Falha em uma subtask.
    Append-only — nunca modificado após criação.
    """
    subtask_id:  str
    tool:        str | None    # None se falhou antes de chegar ao recurso
    error:       str
    reason:      str
    timestamp:   datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
 


# ---------------------------------------------------------------------------
#   Memória de trabalho da run
# ---------------------------------------------------------------------------
 
class ScratchpadEntry(BaseModel):
    """
    Uma iteração do loop de execução.
 
    ReAct:  reason + action + observation (raciocínio completo)
    ReWOO:  action + observation (reason vazio — planejado upfront)
    """
    step:        int
    subtask_id:  str
    reason:      str = ""
    action:      str
    observation: str
    timestamp:   datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
 

# ---------------------------------------------------------------------------
#   Controle de orçamento
# ---------------------------------------------------------------------------
 
class Budget(BaseModel):
    """
    Controle de recursos consumidos na run.
    Lido e escrito pelo BudgetGuard antes de cada chamada LLM e tool call.
    Limites copiados do PAConfig.budget no início da run.
    """
    # consumido
    tokens_used:  int   = 0
    cost_usd:     float = 0.0
    calls_used:   int   = 0
    elapsed_ms:   float = 0.0
 
    # limites
    tokens_max:   int   = 60_000
    cost_max_usd: float = 0.50
    calls_max:    int   = 40
    timeout_ms:   float = 120_000.0
 
    def is_exceeded(self) -> bool:
        return (
            self.tokens_used  >= self.tokens_max  or
            self.cost_usd     >= self.cost_max_usd or
            self.calls_used   >= self.calls_max    or
            self.elapsed_ms   >= self.timeout_ms
        )
 
    def remaining_tokens(self) -> int:
        return max(0, self.tokens_max - self.tokens_used)
 

# ---------------------------------------------------------------------------
#   AgentState — objeto de run
# ---------------------------------------------------------------------------
 
class AgentState(BaseModel):
    """
    Objeto central que representa uma run do Principal Agent.
 
    Criado quando agent.py recebe uma query do usuário.
    Encerrado quando o Executor conclui ou o BudgetGuard interrompe.
    Persiste em .axon/pa/traces/{session_id}/{request_id}.json
 
    Responsabilidade de escrita por componente:
      raw_query      → agent.py na criação
      objective      → IntentExtractor
      plan           → Decomposer + Planner
      resource_pool  → LocalResourcePool (startup) + Resolver (durante run)
      facts          → Executor (append-only)
      failures       → Executor (append-only)
      progress       → Executor (por subtask)
      scratchpad     → Executor (por iteração do loop)
      budget         → BudgetGuard (antes de cada chamada)
      tool_cache     → Executor (evita chamadas duplicadas na mesma run)
    """
 
    # rastreabilidade
    session_id:    str = Field(default_factory=lambda: str(uuid4())[:12])
    request_id:    str = Field(default_factory=lambda: str(uuid4())[:8])
    created_at:    datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
 
    # entrada
    raw_query:     str = ""
 
    # intenção — IntentExtractor
    objective:     Objective | None = None
 
    # plano — Decomposer + Planner
    plan:          Plan = Field(default_factory=Plan)
 
    # recursos disponíveis para esta run
    # pré-populado no startup com LocalResourcePool + ResourceCache
    # expandido pelo Resolver durante a run
    resource_pool: list[ResourceManifest] = Field(default_factory=list)
 
    # resultados (append-only)
    facts:         list[Fact]    = Field(default_factory=list)
    failures:      list[Failure] = Field(default_factory=list)
 
    # progresso — { subtask_id: SubtaskStatus }
    progress:      dict[str, SubtaskStatus] = Field(default_factory=dict)
 
    # memória de trabalho da run
    scratchpad:    list[ScratchpadEntry] = Field(default_factory=list)
 
    # orçamento
    budget:        Budget = Field(default_factory=Budget)
 
    # cache de chamadas na run — evita duplicatas
    # { "tool:params_hash": result }
    tool_cache:    dict[str, Any] = Field(default_factory=dict)

    # atribuição de recursos por subtask — preenchido pelo Resolver
    # { subtask_id: ResolverResult }
    #   local (Step 1): ResolverResult com ga_url="" → Executor NÃO atualiza UCB
    #   GA    (Step 2): ResolverResult com ga_url preenchido → update_final fecha o reward
    resource_assignments: dict[str, ResolverResult] = Field(default_factory=dict)
 
    # ── helpers ───────────────────────────────────────────────────────────────
 
    def append_step(
        self,
        subtask_id:  str,
        action:      str,
        observation: str,
        reason:      str = "",   # ReWOO: sempre vazio — ReAct: raciocínio do LLM
    ) -> None:
        """
        Registra uma etapa no scratchpad.

        ReWOO: reason vazio — planejamento upfront, sem raciocínio por etapa.
        ReAct: reason preenchido pelo LLM antes de cada action.

        step é auto-incrementado pelo tamanho atual do scratchpad.
        """
        self.scratchpad.append(ScratchpadEntry(
            step=len(self.scratchpad) + 1,
            subtask_id=subtask_id,
            action=action,
            observation=observation,
            reason=reason,
        ))

    def get_fact(self, subtask_id: str) -> Fact | None:
        """Retorna o Fact de uma subtask pelo id."""
        return next(
            (f for f in self.facts if f.subtask_id == subtask_id), None
        )
 
    def get_artifact(self, name: str) -> Any | None:
        """
        Busca o output de uma subtask pelo nome do output_artifact.
        Usado pelo Executor para resolver {{artifact:nome}} no ReWOO.
        """
        subtask = next(
            (s for s in self.plan.subtasks if s.output_artifact == name),
            None
        )
        if not subtask:
            return None
        fact = self.get_fact(subtask.id)
        return fact.output if fact else None
 
    def get_resource(self, capability: str) -> ResourceManifest | None:
        """Busca recurso no resource_pool por capability_tag."""
        return next(
            (r for r in self.resource_pool if capability in r.capability_tags),
            None
        )
 
    def is_complete(self) -> bool:
        """Todas as subtasks obrigatórias completadas."""
        return all(
            self.progress.get(s.id) == SubtaskStatus.COMPLETED
            for s in self.plan.subtasks
            if not s.is_optional
        )
 
    def has_failed(self) -> bool:
        """Alguma subtask obrigatória falhou."""
        return any(
            self.progress.get(s.id) == SubtaskStatus.FAILED
            for s in self.plan.subtasks
            if not s.is_optional
        )