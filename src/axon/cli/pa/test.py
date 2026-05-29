"""
cli/pa/test.py — axon pa intent test

Roda IntentExtractor + Decomposer e mostra o resultado completo.
Útil para verificar se o pipeline está funcionando corretamente
antes de implementar o Executor.
"""

from __future__ import annotations

import typer

from axon.cli._print import console, ok, warn, info, step, divider, fatal

app = typer.Typer(help="Test PA pipeline steps.")


@app.command("test")
def intent_test(
    query:   str       = typer.Option(..., "--query", "-q", help="Query to test"),
    verbose: bool      = typer.Option(False, "--verbose", "-v", help="Show context injected into the LLM"),
) -> None:
    """
    Run IntentExtractor + Decomposer and print the full result.

    Shows: context injected → Objective → Plan (subtasks with params).
    """
    from axon.config import read_config, paths
    from axon.pa.agent import PrincipalAgent
    from axon.pa.decomposer import Decomposer

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

    console.print()
    console.print(f"  {step(f'query  [dim]{query}[/dim]')}")
    console.print(divider())

    # ── IntentExtractor ───────────────────────────────────────────────
    console.print(f"  {step('extracting intent...')}")

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

    # clarification?
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

    # Objective
    console.print()
    console.print(f"  {ok('[bold]objective[/bold]')}")
    console.print(info(f"goal       [dim]{intent.goal}[/dim]"))
    console.print(info(f"success    [dim]{intent.success_definition}[/dim]"))
    if intent.extracted_inputs:
        for k, v in intent.extracted_inputs.items():
            console.print(info(f"input      [dim]{k}: {v}[/dim]"))
    if intent.capability_hints:
        console.print(info(f"hints      [dim]{', '.join(intent.capability_hints)}[/dim]"))
    if intent.constraints:
        for c in intent.constraints:
            console.print(info(f"constraint [dim][{c.type}] {c.value}[/dim]"))

    # ── Decomposer ────────────────────────────────────────────────────
    console.print()
    console.print(f"  {step('decomposing into subtasks (ReWOO)...')}")
    console.print(divider())

    from axon.pa.models import AgentState

    decomposer = Decomposer(config.pa)

    try:
        state = AgentState(
            raw_query=query,
            objective=intent,
            resource_pool=agent._local_pool.tools + agent._resource_cache.all(),
        )
        decomposer.decompose(state)
        plan = state.plan
    except Exception as exc:
        fatal(f"Decomposer error: {exc}")

    console.print()
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
            console.print(info(f"depends_on  [dim]{', '.join(s.depends_on)}[/dim]"))
        if s.params_template:
            for k, v in s.params_template.items():
                console.print(info(f"param [{k}]  [dim]{v}[/dim]"))
        if s.is_optional:
            console.print(info("[dim]optional[/dim]"))
        console.print(divider())

    console.print()