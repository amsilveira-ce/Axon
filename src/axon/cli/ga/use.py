"""cli/ga/use.py — axon ga use <context>"""
from __future__ import annotations

import typer

from axon.cli._print import console, ok, warn, fatal, info

app = typer.Typer(help="Switch the active Gateway Agent context.")


@app.callback(invoke_without_command=True)
def ga_use(
    context: str = typer.Argument(..., help="Gateway context name (e.g. ga-corp)"),
) -> None:
    """
    Switch the active Gateway Agent context.

    Subsequent commands (axon add agent, axon token generate,
    axon ga resource list, etc.) will operate on this gateway.
    """
    from axon.config import read_config, patch_config

    try:
        cfg = read_config()
    except FileNotFoundError:
        fatal('axon.config.json not found. Run "axon init" first.')

    if context not in cfg.gateways:
        console.print()
        console.print(warn(f"gateway context [bold]{context}[/bold] not found"))
        console.print()
        console.print(info("[dim]available contexts:[/dim]"))
        for name in cfg.gateways:
            marker = " [cyan]← current[/cyan]" if name == cfg.current_gateway else ""
            console.print(info(f"[dim]{name}[/dim]{marker}"))
        console.print()
        console.print(info(f"[dim]create with: axon ga init --name {context} --port <port>[/dim]"))
        console.print()
        raise typer.Exit(1)

    if context == cfg.current_gateway:
        console.print()
        console.print(info(f"[dim]already on context [bold]{context}[/bold][/dim]"))
        console.print()
        raise typer.Exit(0)

    patch_config(lambda c: c.model_copy(update={"current_gateway": context}))

    ga_cfg = cfg.gateways[context]
    console.print()
    console.print(ok(f"switched to [bold]{context}[/bold]"))
    console.print()
    console.print(info(f"[dim]name     {ga_cfg.name}[/dim]"))
    console.print(info(f"[dim]port     {ga_cfg.port}[/dim]"))
    console.print(info(f"[dim]data dir {ga_cfg.data_dir}[/dim]"))
    console.print()
    console.print(info("[dim]operations now target this gateway:[/dim]"))
    console.print(info("[dim]  axon add agent <url>[/dim]"))
    console.print(info("[dim]  axon token generate --name <name>[/dim]"))
    console.print(info("[dim]  axon ga resource list[/dim]"))
    console.print()