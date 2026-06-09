"""
cli/pa/test.py — axon pa intent test

Roda o pipeline do PA e mostra o roadmap completo, etapa por etapa:

  1. IntentExtraction  query → Objective
  2. Decomposer        Objective → subtasks → Plan + DAG
  3. Resolver          Plan → recurso por subtask (local pool / Gateway Agent)
  4. Executor          executa cada subtask → Fact/Failure, scratchpad, budget

O Resolver mostra TODAS as suas decisões: pool local (cache hit), ranking UCB
dos gateways, broadcast, filtro de política e a atribuição final. O Executor
mostra a execução real (chamadas a recursos), o scratchpad e o consumo de budget,
e persiste o trace (replay com `axon pa inspect`). Use --dry-run para parar antes
do Executor (só planejamento, sem chamadas externas).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager

import typer

from axon.cli._print import console, ok, warn, info, step, divider, fatal

app = typer.Typer(help="Test PA pipeline steps.")


# ── captura de logs de uma etapa ────────────────────────────────────────────────

class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@contextmanager
def _capture(*logger_names: str):
    """Captura mensagens INFO dos loggers dados durante o bloco."""
    handler = _ListHandler()
    loggers = [logging.getLogger(n) for n in logger_names]
    saved   = [(lg, lg.level) for lg in loggers]
    for lg in loggers:
        lg.addHandler(handler)
        lg.setLevel(logging.INFO)
    try:
        yield handler.lines
    finally:
        for lg, lvl in saved:
            lg.removeHandler(handler)
            lg.setLevel(lvl)


@app.command("test")
def intent_test(
    query:   str  = typer.Option(..., "--query", "-q", help="Query to test"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show context injected into the LLM"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Stop after the Resolver — don't execute (no external calls)"),
) -> None:
    """
    Run the full PA pipeline (Intent → Decomposer → Resolver → Executor) and print each stage.
    """
    from axon.config import read_config, paths
    from axon.pa.agent import PrincipalAgent

    try:
        config = read_config()
    except FileNotFoundError:
        fatal('axon.config.json not found. Run "axon init" first.')

    p     = paths()
    agent = PrincipalAgent(
        config=config.pa,
        sessions_dir=p.pa_sessions,
        memory_path=p.pa_memory_bank,
    )

    with agent:
        _run_pipeline(agent, config, query, verbose, dry_run)


def _run_pipeline(agent, config, query, verbose, dry_run) -> None:
    from axon.pa.decomposer import Decomposer
    from axon.pa.models import AgentState
    from axon.pa.planner import Planner, PlanError
    from axon.pa.resolver import ResolverClarification, ResolverError

    console.print()
    console.print(f"  [bold]PA pipeline — roadmap[/bold]")
    console.print(f"  {step(f'query  [dim]{query}[/dim]')}")
    console.print(divider())

    # ── 1. IntentExtraction ───────────────────────────────────────────────
    console.print()
    console.print(f"  [bold cyan]1. IntentExtraction[/bold cyan]  [dim]query → Objective[/dim]")
    console.print(divider())

    try:
        intent, trace = agent._intent_extractor.extract(
            query,
            history=agent._history,
            memory=agent._memory,
            resources=agent._local_pool.get_capabilities(),
        )
        agent.last_trace = trace
    except Exception as exc:
        fatal(f"IntentExtractor error: {exc}")

    if verbose and agent.last_trace:
        from axon.cli.pa._trace import print_trace
        print_trace(agent.last_trace)

    if intent.clarification is not None:
        console.print()
        console.print(warn("[bold]needs clarification — cannot decompose[/bold]"))
        console.print()
        console.print(info(f"[dim]{intent.clarification.context}[/dim]"))
        for i, q in enumerate(intent.clarification.questions, 1):
            console.print(f"  [cyan]{i}.[/cyan] {q.question}")
            if q.options:
                console.print(f"     [dim]{'  /  '.join(q.options)}[/dim]")
        console.print()
        return

    console.print(f"  {ok('[bold]objective[/bold]')}")
    console.print(info(f"goal       [dim]{intent.goal}[/dim]"))
    console.print(info(f"success    [dim]{intent.success_definition}[/dim]"))
    for k, v in (intent.extracted_inputs or {}).items():
        console.print(info(f"input      [dim]{k}: {v}[/dim]"))
    for c in intent.constraints:
        console.print(info(f"constraint [dim][{c.type}] {c.value}[/dim]"))

    # ── 2. Decomposer + Planner ───────────────────────────────────────────
    console.print()
    console.print(f"  [bold cyan]2. Decomposer[/bold cyan]  [dim]Objective → subtasks → Plan + DAG[/dim]")
    console.print(divider())

    decomposer = Decomposer(config.pa)
    planner    = Planner()

    state = AgentState(
        raw_query=query,
        objective=intent,
        resource_pool=agent._local_pool.tools + agent._resource_cache.all(),
    )

    try:
        decomposer.decompose(state)
    except Exception as exc:
        fatal(f"Decomposer error: {exc}")

    try:
        planner.plan(state)
    except PlanError as exc:
        console.print()
        console.print(warn(f"[bold]PlanError[/bold]  [dim]{exc}[/dim]"))
        console.print()
        return

    _print_plan(state.plan)
    _print_dag(state.plan)

    # ── 3. Resolver ───────────────────────────────────────────────────────
    console.print()
    console.print(f"  [bold cyan]3. Resolver[/bold cyan]  [dim]Plan → recurso por subtask[/dim]")
    console.print(divider())

    gw = [g.url for g in config.pa.gateways]
    console.print(info(f"local pool  [dim]{len(state.resource_pool)} resources[/dim]"))
    console.print(info(f"gateways    [dim]{', '.join(gw) if gw else 'none connected'}[/dim]"))
    console.print()

    resolver_error = None
    resolver_clarification = None
    with _capture("axon.pa.resolver") as resolver_log:
        try:
            agent._resolver.resolve(state)
        except ResolverClarification as clar:
            resolver_clarification = clar
        except ResolverError as exc:
            resolver_error = exc

    # passos do Resolver (step1 local / step2 UCB+broadcast / step3 política)
    if resolver_log:
        console.print(f"  {step('resolver steps')}")
        for line in resolver_log:
            console.print(info(f"[dim]{line}[/dim]"))
        console.print()

    _print_assignments(state)
    _print_affinity(agent._affinity)

    if resolver_clarification is not None:
        clar = resolver_clarification.clarification
        console.print()
        console.print(warn("[bold]needs clarification — capability not available[/bold]"))
        console.print(info(f"[dim]{clar.context}[/dim]"))
        for i, q in enumerate(clar.questions, 1):
            console.print(f"  [cyan]{i}.[/cyan] {q.question}")
        console.print()
        console.print(info("[dim]fallback_strategy=ask_user — no execution[/dim]"))
        console.print()
        return

    if resolver_error is not None:
        console.print()
        console.print(warn(f"[bold]ResolverError[/bold]  [dim]{resolver_error}[/dim]"))
        console.print()
        console.print(info("[dim]nada resolvido — sem execução[/dim]"))
        console.print()
        return

    # ── 4. Executor ───────────────────────────────────────────────────────
    if dry_run:
        console.print()
        console.print(info("[dim]--dry-run — parando antes do Executor (sem chamadas externas)[/dim]"))
        console.print()
        return

    console.print()
    console.print(f"  [bold cyan]4. Executor[/bold cyan]  [dim]Plan → execução real (Fact/Failure + reward)[/dim]")
    console.print(divider())

    with _capture("axon.pa.executor") as exec_log:
        try:
            agent._executor.execute(state)
        except Exception as exc:
            fatal(f"Executor error: {exc}")

    if exec_log:
        console.print(f"  {step('executor steps')}")
        for line in exec_log:
            console.print(info(f"[dim]{line}[/dim]"))
        console.print()

    _print_execution(state)

    # ── 5. Response ───────────────────────────────────────────────────────
    console.print()
    console.print(f"  [bold cyan]5. Response[/bold cyan]  [dim]facts + contexto → resposta final[/dim]")
    console.print(divider())
    try:
        answer = agent._synthesizer.synthesize(state, agent._history)
    except Exception as exc:
        answer = f"[synthesizer error: {exc}]"
    console.print(f"  {ok('[bold]response[/bold]')}")
    for line in (answer or "(empty)").splitlines():
        console.print(info(line))

    agent._persist_trace(state)
    console.print()
    console.print(info(f"[dim]trace saved — replay:[/dim] [cyan]axon pa inspect --session {state.session_id}[/cyan]"))
    console.print()


# ── render helpers ──────────────────────────────────────────────────────────────

def _print_plan(plan) -> None:
    console.print(f"  {ok(f'[bold]plan[/bold]  [dim]{len(plan.subtasks)} subtask(s)[/dim]')}")
    console.print()
    for s in plan.subtasks:
        console.print(f"  [cyan]◆[/cyan] [bold]{s.id}[/bold]  [dim]{s.description}[/dim]")
        console.print(info(f"capability  [dim]{s.capability_required}[/dim]"))
        if s.output_artifact:
            console.print(info(f"output      [cyan]{s.output_artifact}[/cyan]"))
        if s.input_artifacts:
            console.print(info(f"inputs      [dim]{', '.join(s.input_artifacts)}[/dim]"))
        if s.depends_on:
            console.print(info(f"depends_on  [green]{', '.join(s.depends_on)}[/green]"))
        else:
            console.print(info("depends_on  [dim]none (root)[/dim]"))
        for k, v in (s.params_template or {}).items():
            console.print(info(f"param [{k}]  [dim]{v}[/dim]"))
        console.print(divider())


def _print_dag(plan) -> None:
    """Mostra o DAG: arestas de dependência + camadas topológicas."""
    subtasks = plan.subtasks
    if not subtasks:
        return

    # nível topológico de cada subtask (subtasks já vêm ordenadas)
    level: dict[str, int] = {}
    for s in subtasks:
        level[s.id] = 0 if not s.depends_on else 1 + max(level[d] for d in s.depends_on)

    by_level: dict[int, list[str]] = {}
    for s in subtasks:
        by_level.setdefault(level[s.id], []).append(s.id)

    console.print()
    console.print(f"  {ok('[bold]DAG[/bold]')}")

    # arestas
    edges = [f"{d} → {s.id}" for s in subtasks for d in s.depends_on]
    console.print(info(f"edges       [dim]{', '.join(edges) if edges else 'none (all roots)'}[/dim]"))

    # camadas — o que pode rodar em paralelo em cada passo
    layers = " │ ".join(
        f"L{lv}: {', '.join(by_level[lv])}"
        for lv in sorted(by_level)
    )
    console.print(info(f"layers      [dim]{layers}[/dim]"))


def _print_assignments(state) -> None:
    from rich.table import Table

    if not state.resource_assignments:
        console.print(info("[dim]no resources assigned[/dim]"))
        return

    table = Table(show_header=True, header_style="dim", box=None, pad_edge=False, padding=(0, 3, 0, 0))
    table.add_column("subtask")
    table.add_column("capability")
    table.add_column("resource")
    table.add_column("source")
    table.add_column("match")

    for s in state.plan.subtasks:
        rr = state.resource_assignments.get(s.id)
        if rr is None:
            table.add_row(s.id, s.capability_required, "[red]— unresolved[/red]", "", "")
            continue
        source = (
            f"[cyan]GA[/cyan] {rr.ga_url}  [dim]{rr.latency_ms:.0f}ms[/dim]"
            if rr.ga_url else "[dim]local pool[/dim]"
        )
        match = f"{rr.match_score:.2f}" if rr.ga_url else "[dim]—[/dim]"
        table.add_row(s.id, s.capability_required, f"[bold]{rr.manifest.name}[/bold]", source, match)

    console.print(f"  {ok('[bold]assignments[/bold]')}")
    console.print(table)


def _print_execution(state) -> None:
    """Resultado da execução: status/output por subtask, scratchpad e budget."""
    from rich.table import Table
    from axon.pa.executor import _short

    _style = {"completed": "green", "failed": "red", "skipped": "yellow", "pending": "dim"}

    table = Table(show_header=True, header_style="dim", box=None, pad_edge=False, padding=(0, 3, 0, 0))
    table.add_column("subtask")
    table.add_column("status")
    table.add_column("tool")
    table.add_column("output / error")

    for s in state.plan.subtasks:
        status = state.progress.get(s.id)
        label  = status.value if status else "pending"
        st     = _style.get(label, "white")
        fact   = state.get_fact(s.id)
        if fact is not None:
            tool, detail = fact.tool, _short(fact.output)
        else:
            fails  = [f for f in state.failures if f.subtask_id == s.id]
            tool   = (fails[-1].tool or "—") if fails else "—"
            detail = f"[red]{fails[-1].reason}[/red]" if fails else ""
        table.add_row(s.id, f"[{st}]{label}[/{st}]", tool, detail)

    console.print(f"  {ok('[bold]execution[/bold]')}")
    console.print(table)

    if state.scratchpad:
        console.print()
        console.print(f"  {step('scratchpad')}")
        for e in state.scratchpad:
            console.print(info(f"[dim]{e.step}. {e.action}[/dim]"))
            console.print(info(f"   [dim]→ {e.observation}[/dim]"))

    b = state.budget
    console.print()
    console.print(f"  {step('budget')}")
    console.print(info(
        f"[dim]tokens {b.tokens_used}/{b.tokens_max} · "
        f"calls {b.calls_used}/{b.calls_max} · elapsed {b.elapsed_ms / 1000:.1f}s[/dim]"
    ))


def _print_affinity(affinity) -> None:
    """Tabela UCB por (gateway, capability) após o resolve."""
    table = getattr(affinity, "_table", {})
    if not table:
        return
    console.print()
    console.print(f"  {step('gateway affinity (UCB)')}")
    for ga_url, caps in table.items():
        for cap, e in caps.items():
            console.print(info(
                f"[dim]{ga_url} [{cap}] queries={e.query_count} reward={e.reward_mean:.3f}[/dim]"
            ))
