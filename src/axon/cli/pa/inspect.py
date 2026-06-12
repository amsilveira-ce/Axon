from __future__ import annotations

import logging

import typer

from axon.cli._print import console, fatal, ok, line, step, divider, hint, setup_logging

logger = logging.getLogger(__name__)

app = typer.Typer()

_STATUS_STYLE = {
    "completed": "green",
    "failed":    "red",
    "skipped":   "yellow",
    "running":   "cyan",
    "pending":   "dim",
}


def _short(value: object, limit: int = 90) -> str:
    import json
    try:
        s = json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        s = str(value)
    s = " ".join(s.split())
    return s if len(s) <= limit else s[:limit] + "…"


@app.callback(invoke_without_command=True)
def inspect(
    session: str | None = typer.Option(
        None, "--session", "-s", help="Session id to inspect (default: most recent run)"
    ),
    request: str | None = typer.Option(
        None, "--request", "-r", help="Specific request id within the session (default: latest)"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show extra logging."),
) -> None:
    """
    Render the objective, plan, facts and budget of a recorded run.

    Every 'axon pa run' persists its full AgentState as a trace. This
    command replays the most recent one — or a specific run via
    --session and --request — showing what the agent understood,
    planned, executed and spent.
    """
    setup_logging(verbose)

    from axon.config import read_config, paths
    from axon.pa.models import AgentState

    try:
        read_config()
    except FileNotFoundError:
        fatal('axon.config.json not found — run "axon init" first.')

    traces = paths().pa_traces
    if not traces.exists() or not any(traces.iterdir()):
        fatal(
            "no run traces found yet",
            hint("run one", 'axon pa run -q "..."'),
        )

    # ── resolve a sessão ──────────────────────────────────────────────────
    if session is None:
        # sessão da run mais recente (trace mais novo entre todas)
        all_traces = list(traces.glob("*/*.json"))
        if not all_traces:
            fatal("no run traces found yet", hint("run one", 'axon pa run -q "..."'))
        latest = max(all_traces, key=lambda p: p.stat().st_mtime)
        session = latest.parent.name

    session_dir = traces / session
    if not session_dir.exists():
        available = sorted(p.name for p in traces.iterdir() if p.is_dir())
        fatal(
            f"no trace for session '{session}'",
            hint("available", ", ".join(available) or "(none)"),
        )

    # ── resolve o request dentro da sessão ────────────────────────────────
    runs = sorted(session_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not runs:
        fatal(f"session '{session}' has no recorded runs")

    if request is not None:
        target = session_dir / f"{request}.json"
        if not target.exists():
            ids = ", ".join(p.stem for p in runs)
            fatal(f"no request '{request}' in session '{session}'", hint("available", ids))
    else:
        target = runs[-1]  # mais recente

    try:
        state = AgentState.model_validate_json(target.read_text(encoding="utf-8"))
    except Exception as exc:
        fatal(f"could not read trace {target}: {exc}")

    _render(state, session, len(runs))


def _render(state, session: str, run_count: int) -> None:
    console.print()
    console.print(f"  {ok('[bold]run trace[/bold]')}")
    console.print(line(f"[dim]session: {session}  ·  request: {state.request_id}  ·  {run_count} run(s) in session[/dim]"))
    console.print()

    # OBJECTIVE
    console.print(f"  {step('[bold]objective[/bold]')}")
    if state.objective is not None:
        console.print(line(f"goal:    {state.objective.goal}"))
        if state.objective.success_definition:
            console.print(line(f"success: {state.objective.success_definition}"))
    else:
        console.print(line("[dim](no objective)[/dim]"))
    console.print(divider())

    # PLAN
    console.print(f"  {step('[bold]plan[/bold]')}")
    subtasks = state.plan.subtasks if state.plan else []
    if subtasks:
        id_w  = max(len(s.id) for s in subtasks)
        cap_w = max(len(s.capability_required) for s in subtasks)
        for s in subtasks:
            status = state.progress.get(s.id)
            label  = status.value if status else "pending"
            style  = _STATUS_STYLE.get(label, "white")
            console.print(line(
                f"{s.id:<{id_w}}  {s.capability_required:<{cap_w}}  [{style}]{label.upper()}[/{style}]"
            ))
    else:
        console.print(line("[dim](no plan)[/dim]"))
    console.print(divider())

    # FACTS
    console.print(f"  {step('[bold]facts[/bold]')}")
    if state.facts:
        for f in state.facts:
            console.print(line(f"{f.subtask_id}  [cyan]{f.tool}[/cyan]  → {_short(f.output)}"))
    else:
        console.print(line("[dim](no facts)[/dim]"))
    console.print(divider())

    # FAILURES (só se houver)
    if state.failures:
        console.print(f"  {step('[bold red]FAILURES[/bold red]')}")
        for f in state.failures:
            tool = f.tool or "—"
            console.print(line(f"{f.subtask_id}  [red]{tool}[/red]  {f.error}: {f.reason}"))
        console.print(divider())

    # BUDGET
    b = state.budget
    console.print(f"  {step('[bold]budget[/bold]')}")
    console.print(line(f"tokens:  {b.tokens_used:,} / {b.tokens_max:,}"))
    console.print(line(f"calls:   {b.calls_used} / {b.calls_max}"))
    console.print(line(f"elapsed: {b.elapsed_ms / 1000:.1f}s"))
    console.print()
