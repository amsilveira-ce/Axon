"""
pa/executor.py — Executor (loop de execução do plano)

Última etapa do pipeline do PA. O Resolver já preencheu state.resource_assignments
(um ResourceManifest pronto por subtask). O Executor percorre o Plan já ordenado
pelo Planner e transforma cada subtask em ação real: chama o recurso, coleta o
resultado, registra Fact/Failure e mantém o raciocínio no scratchpad.

É o único componente do PA que fala com o mundo externo durante a run
(agentes A2A, ferramentas MCP, ou delegação ao GA via proxy).

Para cada subtask (na ordem topológica do Planner):
  1. BudgetGuard      — algum limite estourou? interrompe a run
  2. depends_on       — predecessoras COMPLETED? senão falha/skip
  3. tool_cache       — já chamado com os mesmos params nesta run? usa o cache
  4. monta parâmetros (ReWOO: resolve {{artifact:nome}})
  5. executa via cliente correto (callable_by); em falha, tenta alternatives
  6. registra Fact ou Failure (append-only)
  7. atualiza progress + scratchpad + budget (calls_used, elapsed_ms)
  8. fecha o reward UCB (update_final) — só para recursos vindos de GA

Lê:    state.plan.subtasks, state.resource_assignments, state.budget, state.progress
Escreve: state.facts, state.failures, state.progress, state.scratchpad,
         state.tool_cache, state.budget
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from axon.pa.ga_affinity import GAAffinityStore
from axon.pa.models import Fact, Failure, Provenance, SubtaskStatus
from axon.types import ResourceType

# {{artifact:nome}} — placeholder do ReWOO resolvido pelo output de um Fact
_ARTIFACT_RE = re.compile(r"\{\{\s*artifact:([^}]+?)\s*\}\}")

if TYPE_CHECKING:
    from axon.pa.models import AgentState, ResolverResult, Subtask
    from axon.pa.parameterizer import Parameterizer
    from axon.types import ResourceManifest

logger = logging.getLogger(__name__)


class ExecutorError(Exception):
    """Raised em falha irrecuperável do próprio loop (não de uma subtask)."""


class ParamResolutionError(Exception):
    """Um placeholder {{artifact:nome}} não pôde ser resolvido (Step 4)."""


class Executor:
    """
    Executa o Plan resolvido (Passos 1-8).

    pa_id, se informado, viaja no header X-Axon-PA-ID das chamadas ga_proxy
    (observabilidade no GA).

    Uso:
        executor = Executor(affinity=store, affinity_path=path)
        executor.execute(state)
    """

    def __init__(
        self,
        affinity:       GAAffinityStore | None  = None,
        affinity_path:  Path | None             = None,
        pa_id:          str | None              = None,
        parameterizer:  "Parameterizer | None"  = None,
        local_session:  "Any | None"            = None,
    ) -> None:
        self._affinity      = affinity   # Step 8 — update_final
        self._affinity_path = affinity_path
        self._pa_id         = pa_id
        self._parameterizer = parameterizer   # late-binding de params (bind-if-mismatch)
        # shared session para tools locais — evita spawn por subtask
        self._local_session = local_session

    # ------------------------------------------------------------------
    #   Loop principal
    # ------------------------------------------------------------------

    def execute(self, state: "AgentState") -> None:
        """Percorre as subtasks ordenadas e preenche facts/failures/progress."""
        for subtask in state.plan.subtasks:
            # mantém elapsed_ms atual para o BudgetGuard ver o tempo real
            self._update_elapsed(state)

            # subtasks já decididas pelo Resolver (fallback skip/optional) — respeita
            status = state.progress.get(subtask.id)
            if status in (SubtaskStatus.SKIPPED, SubtaskStatus.FAILED):
                logger.debug(
                    "[Executor] subtask=%s já %s pelo Resolver — pula",
                    subtask.id, status.value,
                )
                continue

            # ── Step 1 — BudgetGuard ────────────────────────────────────────────
            if state.budget.is_exceeded():
                reason = _budget_reason(state.budget)
                logger.warning("[Executor] budget exceeded — interrompendo: %s", reason)
                state.failures.append(Failure(
                    subtask_id=subtask.id,
                    tool=None,
                    error="budget_exceeded",
                    reason=reason,
                ))
                state.progress[subtask.id] = SubtaskStatus.FAILED
                state.append_step(
                    subtask_id=subtask.id,
                    action="budget check",
                    observation=f"halted — {reason}",
                )
                break  # nenhuma subtask seguinte roda

            # ── Step 2 — depends_on ──────────────────────────────────────────────
            if not self._dependencies_satisfied(subtask, state):
                continue  # _dependencies_satisfied já registrou falha/skip

            # ── Step 3 — tool_cache ──────────────────────────────────────────────
            assignment = state.resource_assignments.get(subtask.id)
            if assignment is None:
                logger.warning("[Executor] subtask=%s sem recurso atribuído", subtask.id)
                state.failures.append(Failure(
                    subtask_id=subtask.id,
                    tool=None,
                    error="no_resource",
                    reason="no resource assigned by the Resolver for this subtask",
                ))
                state.progress[subtask.id] = SubtaskStatus.FAILED
                continue

            # ── Step 4 — monta parâmetros (ReWOO: resolve {{artifact:nome}}) ─────
            try:
                params = self._build_params(subtask, state)
            except ParamResolutionError as exc:
                logger.warning("[Executor] subtask=%s param resolution failed: %s", subtask.id, exc)
                state.failures.append(Failure(
                    subtask_id=subtask.id,
                    tool=assignment.manifest.name,
                    error="param_resolution",
                    reason=str(exc),
                ))
                state.progress[subtask.id] = SubtaskStatus.FAILED
                state.append_step(
                    subtask_id=subtask.id,
                    action=f"build params for {assignment.manifest.name}",
                    observation=f"failed — {exc}",
                )
                continue

            cache_key = _cache_key(assignment.manifest.name, params)

            if cache_key in state.tool_cache:
                cached = state.tool_cache[cache_key]
                logger.info(
                    "[Executor] cache hit subtask=%s key=%s — reusa resultado (sem nova chamada)",
                    subtask.id, cache_key,
                )
                state.facts.append(Fact(
                    subtask_id=subtask.id,
                    tool=assignment.manifest.name,
                    output=cached,
                    provenance=_provenance(assignment.manifest),
                ))
                state.progress[subtask.id] = SubtaskStatus.COMPLETED
                state.append_step(
                    subtask_id=subtask.id,
                    action=f"call {assignment.manifest.name} (cached)",
                    observation="reused cached result — no external call, budget untouched",
                )
                continue  # não incrementa calls_used

            # ── Steps 5-8 — dispatch, Fact/Failure, progress/scratchpad, reward ──
            self._dispatch(subtask, assignment, params, cache_key, state)

        self._update_elapsed(state)   # valor final após a última subtask
        logger.info(
            "[Executor] done — %d fact(s), %d failure(s)",
            len(state.facts), len(state.failures),
        )

    # ------------------------------------------------------------------
    #   Step 2 — dependências
    # ------------------------------------------------------------------

    def _dependencies_satisfied(self, subtask: "Subtask", state: "AgentState") -> bool:
        """
        Garante que toda predecessora terminou em COMPLETED.

        O Planner já ordenou topologicamente, então isto normalmente passa —
        é uma rede de segurança. Uma dependência SKIPPED propaga: a subtask vira
        SKIPPED se for opcional, FAILED se for obrigatória. Qualquer outro estado
        não-COMPLETED (FAILED, PENDING, RUNNING) reprova a subtask.

        Retorna True se pode prosseguir; False se já registrou falha/skip.
        """
        for dep_id in subtask.depends_on:
            dep_status = state.progress.get(dep_id)
            if dep_status == SubtaskStatus.COMPLETED:
                continue

            if dep_status == SubtaskStatus.SKIPPED:
                if subtask.is_optional:
                    state.progress[subtask.id] = SubtaskStatus.SKIPPED
                    observation = f"skipped — optional, dependency {dep_id} was skipped"
                    logger.info("[Executor] subtask=%s skipped (dep %s skipped)", subtask.id, dep_id)
                else:
                    state.progress[subtask.id] = SubtaskStatus.FAILED
                    state.failures.append(Failure(
                        subtask_id=subtask.id,
                        tool=None,
                        error="dependency_skipped",
                        reason=f"required dependency {dep_id} was skipped",
                    ))
                    observation = f"failed — required dependency {dep_id} was skipped"
                    logger.warning("[Executor] subtask=%s failed (required dep %s skipped)", subtask.id, dep_id)
            else:
                shown = dep_status.value if dep_status else "pending"
                state.progress[subtask.id] = SubtaskStatus.FAILED
                state.failures.append(Failure(
                    subtask_id=subtask.id,
                    tool=None,
                    error="dependency_not_satisfied",
                    reason=f"dependency {dep_id} not completed (status: {shown})",
                ))
                observation = f"failed — dependency {dep_id} not completed (status: {shown})"
                logger.warning(
                    "[Executor] subtask=%s failed (dep %s status=%s)",
                    subtask.id, dep_id, shown,
                )

            state.append_step(
                subtask_id=subtask.id,
                action="dependency check",
                observation=observation,
            )
            return False

        return True

    # ------------------------------------------------------------------
    #   Step 4 — parâmetros (ReWOO: resolve placeholders de artefato)
    # ------------------------------------------------------------------

    def _build_params(self, subtask: "Subtask", state: "AgentState") -> dict[str, Any]:
        """
        ReWOO: params_template já vem do Decomposer com valores fixos e
        placeholders {{artifact:nome}}. Aqui cada placeholder é substituído pelo
        output do Fact da subtask que declara aquele output_artifact.

            { "data": "{{artifact:patient_data}}" }
              → state.get_artifact("patient_data")
              → { "data": {"name": "João Silva", "age": 45, ...} }

        Um placeholder isolado vira o objeto cru (preserva tipo); embutido numa
        string maior, é interpolado como texto. ReAct: template vazio → {}.

        Raises:
            ParamResolutionError: placeholder sem Fact correspondente.
        """
        return self._resolve(subtask.params_template, state)

    def _resolve(self, value: Any, state: "AgentState") -> Any:
        if isinstance(value, dict):
            return {k: self._resolve(v, state) for k, v in value.items()}
        if isinstance(value, list):
            return [self._resolve(v, state) for v in value]
        if isinstance(value, str):
            return self._resolve_str(value, state)
        return value

    def _resolve_str(self, text: str, state: "AgentState") -> Any:
        whole = _ARTIFACT_RE.fullmatch(text.strip())
        if whole:
            # valor é só o placeholder → devolve o objeto cru (dict/list/etc.)
            return self._artifact(whole.group(1).strip(), state)
        # placeholders embutidos numa string → interpola como texto
        def _sub(m: re.Match) -> str:
            val = self._artifact(m.group(1).strip(), state)
            return val if isinstance(val, str) else json.dumps(val, default=str, ensure_ascii=False)
        return _ARTIFACT_RE.sub(_sub, text)

    def _artifact(self, name: str, state: "AgentState") -> Any:
        """
        Resolve {{artifact:name}}.

        Precedência:
          1. output do Fact de uma subtask que declara output_artifact=name;
          2. se NENHUMA subtask produz `name`, cai para um input do objetivo de
             mesmo nome (objective.extracted_inputs) — o LLM às vezes referencia
             um valor de input como se fosse artifact.

        Erro só quando não há produtor nem input correspondente. Se há produtor
        mas ele ainda não tem Fact, é erro real (ordem/dependência) — não mascara
        com um input homônimo.
        """
        producer = next(
            (s for s in state.plan.subtasks if s.output_artifact == name), None
        )
        if producer is not None:
            fact = state.get_fact(producer.id)
            if fact is None:
                raise ParamResolutionError(
                    f"artifact '{name}' not available — producing subtask "
                    f"'{producer.id}' has no result"
                )
            return fact.output

        inputs = state.objective.extracted_inputs if state.objective else {}
        if name in inputs:
            return inputs[name]

        raise ParamResolutionError(
            f"no subtask produces artifact '{name}' and no objective input named '{name}'"
        )

    # ------------------------------------------------------------------
    #   Steps 5-8 — dispatch, Fact/Failure, progress/scratchpad, reward
    # ------------------------------------------------------------------

    def _dispatch(
        self,
        subtask:    "Subtask",
        assignment: "ResolverResult",
        params:     dict[str, Any],
        cache_key:  str,
        state:      "AgentState",
    ) -> None:
        """
        Step 5 chama o recurso pelo callable_by; em falha, tenta o próximo manifest
        em assignment.alternatives (mesmo GA, recurso alternativo). Step 6 registra
        Fact/Failure (append-only); Step 7 progress/scratchpad/tool_cache/calls_used;
        Step 8 fecha o reward UCB — sucesso = qualquer candidato deu Fact.
        """
        candidates = [assignment.manifest, *assignment.alternatives]
        succeeded  = False

        for i, manifest in enumerate(candidates):
            action = f"{manifest.name}({_short(params)})"
            label  = "primary" if i == 0 else f"alternative #{i}"

            try:
                result = self._call_resource(manifest, params, task=subtask.description)
            except Exception as exc:  # falha de um candidato não derruba o plano
                logger.warning(
                    "[Executor] subtask=%s call %s (%s) failed: %s",
                    subtask.id, manifest.name, label, exc,
                )
                state.budget.calls_used += 1
                state.failures.append(Failure(   # Step 6 — append-only
                    subtask_id=subtask.id,
                    tool=manifest.name,
                    error=type(exc).__name__,
                    reason=str(exc),
                ))
                state.append_step(
                    subtask_id=subtask.id, action=action,
                    observation=f"error ({label}): {exc}",
                )
                continue  # tenta a próxima alternativa

            # Step 6/7 — sucesso
            state.budget.calls_used += 1
            state.facts.append(Fact(
                subtask_id=subtask.id,
                tool=manifest.name,
                output=result,
                provenance=_provenance(manifest),
            ))
            state.progress[subtask.id]  = SubtaskStatus.COMPLETED
            state.tool_cache[cache_key] = result   # duplicata na mesma run → cache hit
            state.append_step(subtask_id=subtask.id, action=action, observation=_short(result))
            logger.info("[Executor] subtask=%s ✓ via %s (%s)", subtask.id, manifest.name, label)
            succeeded = True
            break

        if not succeeded:   # esgotou primary + alternatives
            state.progress[subtask.id] = SubtaskStatus.FAILED
            logger.warning("[Executor] subtask=%s FAILED — all %d candidate(s) exhausted",
                           subtask.id, len(candidates))

        # Update local-pool manifest counters so _find_in_pool can rank by history.
        # GA resources use update_final instead (Step 8 below).
        if not assignment.ga_url:
            if succeeded:
                assignment.manifest.success_count += 1
            else:
                assignment.manifest.failure_count += 1

        self._close_reward(assignment, success=succeeded)   # Step 8

    def _call_resource(self, manifest: "ResourceManifest", params: dict[str, Any], task: str) -> Any:
        """
        Step 5 — escolhe o cliente pelo callable_by/tipo:

          ga_proxy                    → GAClient.invoke (GA roda a tool MCP stdio)
          pa_direct + agent           → A2AClient.call  (agente A2A)
          pa_direct + mcp (local)     → LocalMCPSession  (client compartilhado, zero spawn)
          pa_direct + mcp (remoto)    → MCPClient        (MCP HTTP/SSE — PA chama direto)
        """
        if manifest.callable_by == "ga_proxy":
            from axon.pa.clients.ga_client import GAClient
            resp = GAClient(manifest.ga_url or "").invoke(
                resource_id=manifest.resource_id,
                params=params,
                tool=None,        # servidor single-tool: o GA infere
                task=task,
                pa_id=self._pa_id,
            )
            return resp.get("result")

        if manifest.type == ResourceType.agent:
            from axon.pa.clients.a2a_client import A2AClient
            # A2A é orientado a task em linguagem natural; params estruturados
            # ainda não são mapeados para a chamada (próximo incremento).
            return asyncio.run(A2AClient().call(manifest, task=task))

        # tools locais: usa a session compartilhada se disponível (zero subprocess spawn)
        if self._local_session is not None and self._local_session.owns(manifest):
            return self._call_mcp_via_session(manifest, params, task)

        return asyncio.run(self._call_mcp(manifest, params, task))

    def _call_mcp_via_session(
        self, manifest: "ResourceManifest", params: dict[str, Any], task: str
    ) -> Any:
        """
        MCP local — usa o client compartilhado da LocalMCPSession.

        Sem spawn de subprocess. Seleção de tool e parametrização idêntica
        ao _call_mcp, mas a chamada vai direto ao Client já conectado.
        """
        from axon.pa.clients.mcp_client import MCPClientError
        from axon.pa.parameterizer import conforms

        schemas = self._local_session.tool_schemas()
        tool    = _select_tool(manifest, list(schemas))
        if tool is None:
            raise MCPClientError(
                f"could not pick a tool for '{manifest.name}' among {list(schemas)} — "
                f"neither the resource name nor its capabilities "
                f"{manifest.capability_tags} match a tool name"
            )

        schema = schemas[tool]
        args   = params
        if self._parameterizer is not None and not conforms(params, schema):
            logger.info(
                "[Executor] params %s don't fit '%s' schema — re-parametrizing via LLM",
                sorted(params), tool,
            )
            args = self._parameterizer.bind(
                tool_name=tool, input_schema=schema, intent=task, available=params,
            )

        return self._local_session.call_tool_sync(tool, args)

    async def _call_mcp(self, manifest: "ResourceManifest", params: dict[str, Any], task: str) -> Any:
        """
        MCP pa_direct (stdio/HTTP/SSE). Um servidor MCP pode expor várias tools
        (as tools locais do PA compartilham um único servidor), então escolhe a
        tool por: nome do recurso → capability → única disponível.

        Se os params não conformam ao input schema da tool e há um Parameterizer,
        re-parametriza via LLM antes de chamar (bind-if-mismatch).
        """
        from axon.pa.clients.mcp_client import MCPClient, MCPClientError
        from axon.pa.parameterizer import conforms
        async with MCPClient(manifest) as client:
            schemas = await client.list_tool_schemas()
            tool    = _select_tool(manifest, list(schemas))
            if tool is None:
                raise MCPClientError(
                    f"could not pick a tool for '{manifest.name}' among {list(schemas)} — "
                    f"neither the resource name nor its capabilities "
                    f"{manifest.capability_tags} match a tool name"
                )
            schema = schemas[tool]
            args   = params
            if self._parameterizer is not None and not conforms(params, schema):
                logger.info(
                    "[Executor] params %s don't fit '%s' schema — re-parametrizing via LLM",
                    sorted(params), tool,
                )
                args = self._parameterizer.bind(
                    tool_name=tool, input_schema=schema, intent=task, available=params,
                )
            return await client.call_tool(tool, args)

    def _close_reward(self, assignment: "ResolverResult", success: bool) -> None:
        """
        Step 8 — fecha a fase 2 do reward UCB. Só para recursos vindos de GA
        (ga_url != ""); recursos do pool local não têm afinidade a atualizar.
        """
        if not assignment.ga_url or self._affinity is None:
            return
        self._affinity.update_final(assignment.ga_url, assignment.capability, success)
        if self._affinity_path is not None:
            self._affinity.save(self._affinity_path)

    def _update_elapsed(self, state: "AgentState") -> None:
        """Step 7 — tempo decorrido da run (created_at → agora), em ms."""
        now = datetime.now(timezone.utc)
        state.budget.elapsed_ms = (now - state.created_at).total_seconds() * 1000.0


# ---------------------------------------------------------------------------
#   helpers
# ---------------------------------------------------------------------------

def _budget_reason(budget: Any) -> str:
    """Descreve qual limite do Budget estourou (primeiro que bater)."""
    if budget.tokens_used >= budget.tokens_max:
        return f"budget exceeded: tokens_max reached ({budget.tokens_used}/{budget.tokens_max})"
    if budget.cost_usd >= budget.cost_max_usd:
        return f"budget exceeded: cost_max_usd reached ({budget.cost_usd:.4f}/{budget.cost_max_usd})"
    if budget.calls_used >= budget.calls_max:
        return f"budget exceeded: calls_max reached ({budget.calls_used}/{budget.calls_max})"
    if budget.elapsed_ms >= budget.timeout_ms:
        return f"budget exceeded: timeout_ms reached ({budget.elapsed_ms:.0f}/{budget.timeout_ms:.0f}ms)"
    return "budget exceeded"


def _short(value: Any, limit: int = 160) -> str:
    """Resumo de uma linha (params/result) para action/observation do scratchpad."""
    try:
        s = json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        s = str(value)
    s = " ".join(s.split())
    return s if len(s) <= limit else s[:limit] + "…"


def _cache_key(resource_name: str, params: dict[str, Any]) -> str:
    """
    Chave do tool_cache: nome do recurso + hash estável dos params.

    Estável (json sort_keys + sha1) em vez de hash() builtin, que é salgado por
    processo. O tool_cache vive na run, mas uma chave estável evita surpresas.
    """
    blob = json.dumps(params, sort_keys=True, default=str)
    digest = hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]
    return f"{resource_name}:{digest}"


def _select_tool(manifest: "ResourceManifest", tools: list[str]) -> str | None:
    """
    Escolhe qual tool MCP chamar quando o servidor expõe várias.

      1. manifest.tool explícito                 (ex.: calculator → "calculate")
      2. tool com nome == manifest.name          (ex.: web_search → web_search)
      3. tool com nome em capability_tags
      4. servidor de tool única                  → essa
      5. nada confiável                          → None (o caller falha explícito)
    """
    if manifest.tool and manifest.tool in tools:
        return manifest.tool
    if manifest.name in tools:
        return manifest.name
    for cap in manifest.capability_tags:
        if cap in tools:
            return cap
    if len(tools) == 1:
        return tools[0]
    return None


def _provenance(manifest: "ResourceManifest") -> Provenance:
    """
    Origem do Fact, para rastreabilidade — derivada do manifest que executou
    (pode ser uma alternativa, não necessariamente o primary).

    agente              → A2A
    tool do pool local  → LOCAL (resource_id "local-*", convenção do LocalResourcePool)
    demais MCP          → MCP (HTTP direto ou ga_proxy)

    Derivar do manifest, e não do Step do Resolver (assignment.ga_url), mantém
    a proveniência estável entre runs: um agente A2A vindo do ResourceCache
    (Step 1) é tão A2A quanto no run em que foi descoberto via GA (Step 2).
    """
    if manifest.type == ResourceType.agent:
        return Provenance.A2A
    if manifest.resource_id.startswith("local-") and not manifest.ga_url:
        return Provenance.LOCAL
    return Provenance.MCP
