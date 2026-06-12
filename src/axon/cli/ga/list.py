"""cli/ga/list.py — axon ga list"""
from __future__ import annotations

import typer

from axon.cli._print import console, ok, warn, fatal, line, step, divider

app = typer.Typer()


@app.callback(invoke_without_command=True)
def ga_list() -> None:
    """
    List all configured Gateway Agent instances.

    Shows every context from axon.config.json with its port and data
    directory, marking the active one. Switch with 'axon ga use <name>'.
    """
    from axon.config import read_config

    try:
        cfg = read_config()
    except FileNotFoundError:
        fatal('axon.config.json not found. Run "axon init" first.')

    console.print()
    console.print("  [bold]gateway contexts[/bold]")
    console.print()

    for name, ga_cfg in cfg.gateways.items():
        is_active = name == cfg.current_gateway
        marker    = " [cyan]← active[/cyan]" if is_active else ""
        console.print(f"  {step(f'[bold]{name}[/bold]{marker}')}")
        console.print(line(f"[dim]name     {ga_cfg.name}[/dim]"))
        console.print(line(f"[dim]port     {ga_cfg.port}[/dim]"))
        console.print(line(f"[dim]data dir {ga_cfg.data_dir}[/dim]"))
        console.print(divider())

    console.print()
    console.print(line(f"[dim]{len(cfg.gateways)} context(s) · active: {cfg.current_gateway}[/dim]"))
    console.print()
    console.print(line("[dim]axon ga use <name>[/dim]              switch active context"))
    console.print(line("[dim]axon ga init --name <n> --port <p>[/dim]  add new context"))
    console.print()