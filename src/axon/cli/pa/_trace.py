"""
cli/pa/_trace.py — verbose pipeline display for --verbose / -v

Prints each pipeline stage as a clear structured block to the console.
Logging is completely separate — this is purely for human-readable output.
"""
from __future__ import annotations

from axon.cli._print import console, err, ok
from axon.pa.executor import _short


# ── helpers ───────────────────────────────────────────────────────────────────

def _header(n: int, label: str) -> None:
    console.print()
    console.print(f"  [bold dim]── [{n}] {label} {'─' * max(0, 48 - len(label))}[/bold dim]")
    console.print()


def _row(label: str, value: str, *, indent: int = 4, style: str = "dim") -> None:
    pad = " " * indent
    if style:
        console.print(f"{pad}[{style}]{label:<14}[/{style}] {value}")
    else:
        console.print(f"{pad}{label:<14} {value}")


# ── stage 1 — intent extractor ────────────────────────────────────────────────

def print_trace(trace: "ExtractionTrace") -> None:  # type: ignore[name-defined]
    _header(1, "intent extractor")

    obj = trace.objective

    if obj.clarification is not None:
        _row("status", "[yellow]needs clarification[/yellow]", style="")
        _row("goal", obj.goal or "(unclear)")
        _row("context", obj.clarification.context)
        for i, q in enumerate(obj.clarification.questions, 1):
            _row(f"question {i}", q.question)
        return

    _row("status", "[green]ready[/green]", style="")
    _row("goal", obj.goal)
    _row("success", obj.success_definition or "(not set)")

    if obj.extracted_inputs:
        for k, v in obj.extracted_inputs.items():
            _row(f"input.{k}", str(v))

    if obj.constraints:
        for c in obj.constraints:
            _row("constraint", f"[{c.type}] {c.value}")

    if obj.assumptions:
        for a in obj.assumptions:
            _row("assumption", a)


# ── stage 2 — decomposer + planner ───────────────────────────────────────────

def print_plan(state: "AgentState") -> None:  # type: ignore[name-defined]
    _header(2, "decomposer + planner")

    subtasks = state.plan.subtasks
    console.print(f"    [dim]{len(subtasks)} subtask(s)[/dim]")

    for s in subtasks:
        console.print()
        console.print(f"    [bold][{s.id}][/bold] {s.description}")
        _row("capability", s.capability_required, indent=6)
        if s.depends_on:
            _row("depends_on", ", ".join(s.depends_on), indent=6)
        if s.input_artifacts:
            _row("inputs", ", ".join(s.input_artifacts), indent=6)
        if s.output_artifact:
            _row("output", s.output_artifact, indent=6)
        if s.params_template:
            _row("params", str(_short(s.params_template)), indent=6)


# ── stage 3 — resolver ────────────────────────────────────────────────────────

def print_assignments(state: "AgentState") -> None:  # type: ignore[name-defined]
    _header(3, "resolver")

    if not state.resource_assignments:
        console.print("    [dim](no assignments)[/dim]")
        return

    for sid, a in state.resource_assignments.items():
        via = f"GA {a.ga_url}" if a.ga_url else "local pool"
        score = f"score={a.match_score:.2f}"
        latency = f"  latency={a.latency_ms:.0f}ms" if a.ga_url else ""
        console.print(
            f"    [dim][{sid}][/dim] [bold]{a.manifest.name}[/bold]"
            f"  [dim]{via}  {score}{latency}[/dim]"
        )


# ── stage 4 — executor ────────────────────────────────────────────────────────

def print_execution(state: "AgentState") -> None:  # type: ignore[name-defined]
    _header(4, "executor")

    for f in state.facts:
        console.print(
            f"    {ok(f'[dim][{f.subtask_id}][/dim] [bold]{f.tool}[/bold]')}  "
            f"[dim]{_short(f.output)}[/dim]"
        )

    for fail in state.failures:
        tool = fail.tool or "-"
        console.print(
            f"    {err(f'[dim][{fail.subtask_id}][/dim] [bold]{tool}[/bold]')}  "
            f"[dim]{fail.reason}: {_short(fail.error)}[/dim]"
        )

    if not state.facts and not state.failures:
        console.print("    [dim](no results)[/dim]")

    b = state.budget
    console.print()
    console.print(
        f"    [dim]budget  tokens {b.tokens_used}/{b.tokens_max}"
        f"  ·  calls {b.calls_used}/{b.calls_max}"
        f"  ·  elapsed {b.elapsed_ms / 1000:.1f}s[/dim]"
    )


# ── entry point — prints all stages that are available ────────────────────────

def print_verbose(
    trace: "ExtractionTrace",                  # always available  # type: ignore[name-defined]
    state: "AgentState | None" = None,         # None if clarification was returned  # type: ignore[name-defined]
) -> None:
    console.print()
    console.print("  [bold dim]━━━ verbose pipeline ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold dim]")

    print_trace(trace)

    if state is None:
        console.print()
        return

    print_plan(state)
    print_assignments(state)
    print_execution(state)

    console.print()
    console.print("  [bold dim]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold dim]")
    console.print()
