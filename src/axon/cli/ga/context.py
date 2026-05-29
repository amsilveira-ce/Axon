"""cli/ga/context.py — axon ga context"""
from __future__ import annotations

import typer

from axon.cli._print import console, ok, info, fatal, divider

app = typer.Typer(help="Show the active Gateway Agent context.")


@app.callback(invoke_without_command=True)
def context() -> None:
    """Show the active Gateway Agent context."""
    import os
    from axon.config import read_config, _ENV_GA_CONTEXT
    from axon.ga.config import GAConfig

    try:
        cfg = read_config()
    except FileNotFoundError:
        fatal('axon.config.json not found. Run "axon init" first.')

    ga      = GAConfig.resolve()
    env_ctx = os.environ.get(_ENV_GA_CONTEXT)

    console.print()
    console.print(f"  {ok(f'[bold]{ga.context}[/bold]')}")
    console.print()
    console.print(info(f"[dim]name      {ga.name}[/dim]"))
    console.print(info(f"[dim]port      {ga.port}[/dim]"))
    console.print(info(f"[dim]data dir  {ga.data_dir}[/dim]"))

    # mostra fonte do contexto ativo
    if env_ctx:
        console.print()
        console.print(info(f"[dim]source    AXON_GA_CONTEXT={env_ctx}[/dim]"))
    else:
        console.print()
        console.print(info(f"[dim]source    axon.config.json → current_gateway[/dim]"))

    console.print()
    console.print(info("[dim]axon ga use <name>[/dim]    switch context"))
    console.print(info("[dim]axon ga list[/dim]          see all contexts"))
    console.print()