from __future__ import annotations

import typer

from axon.cli._print import console, ok, info, warn, fatal, divider, step

app = typer.Typer(help="Interactive chat with the Principal Agent.")

_MAX_CLARIFICATION_ROUNDS = 3


@app.callback(invoke_without_command=True)
def chat() -> None:
    """
    Start an interactive session with the Principal Agent.

    The agent extracts intent from your query. If clarification is needed,
    it asks follow-up questions — up to 3 rounds. Once an Objective is
    produced, the goal is displayed and the session ends.
    """
    from axon.config import read_config
    from axon.pa.agent import PrincipalAgent
    from axon.pa.models import ClarificationNeeded, Objective

    try:
        config = read_config()
    except FileNotFoundError:
        fatal('axon.config.json not found. Run "axon init" first.')

    agent = PrincipalAgent(config.pa)

    console.print()
    console.print("  [bold]Axon[/bold] [dim]PA chat[/dim]  [dim]ctrl+c to exit[/dim]")
    console.print()

    query = typer.prompt("  you")
    console.print()

    context = ""

    for round_n in range(1, _MAX_CLARIFICATION_ROUNDS + 1):
        full_query = f"{query}\n\n{context}".strip() if context else query

        try:
            with console.status("  [dim]Understanding your request...[/dim]"):
                intent = agent.extract_intent(full_query)
        except Exception as exc:
            fatal(f"Agent error: {exc}")

        console.print(f"  {step('Understanding user request...')}")
        console.print(divider())

        if isinstance(intent, Objective):
            console.print()
            console.print(f"  {ok('[bold]Objective identified[/bold]')}")
            console.print()
            console.print(info(f"goal        [dim]{intent.goal}[/dim]"))
            console.print(info(f"success     [dim]{intent.success_definition}[/dim]"))
            if intent.constraints:
                console.print(info(f"constraints [dim]{', '.join(intent.constraints)}[/dim]"))
            console.print()
            return

        assert isinstance(intent, ClarificationNeeded)

        if round_n == _MAX_CLARIFICATION_ROUNDS:
            console.print()
            console.print(f"  {warn('Max clarification rounds reached — try a more specific query.')}")
            console.print()
            raise typer.Exit(1)

        console.print()
        console.print(f"  [dim]{intent.context}[/dim]")
        console.print()

        for i, q in enumerate(intent.questions, 1):
            console.print(f"  [cyan]{i}.[/cyan] {q.question}")
            if q.options:
                opts = "  /  ".join(q.options)
                console.print(f"     [dim]{opts}[/dim]")
        console.print()

        answer = typer.prompt("  you")
        console.print()

        context = f"{context}\nUser clarification (round {round_n}): {answer}".strip()