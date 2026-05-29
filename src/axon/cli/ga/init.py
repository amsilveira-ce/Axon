"""cli/ga/init.py — axon ga init"""
from __future__ import annotations

import json
from pathlib import Path

import typer

from axon.cli._print import console, ok, warn, fatal, info, step, divider
from axon.cli.ga._prompts import pick_retrieval_strategy

app = typer.Typer(help="Initialize a new Gateway Agent instance.")


@app.callback(invoke_without_command=True)
def ga_init(
    name:     str = typer.Option(..., "--name", "-n", help="Context name (e.g. ga-corp)"),
    port:     int = typer.Option(5001, "--port", "-p", help="Port this GA will listen on"),
    data_dir: str | None = typer.Option(None, "--data-dir", help="Data directory (default: .axon/{name})"),
) -> None:
    """Initialize a new Gateway Agent instance."""
    from axon.config import read_config, patch_config, GAInstanceConfig, GAPaths

    try:
        cfg = read_config()
    except FileNotFoundError:
        fatal('axon.config.json not found. Run "axon init" first.')

    if name in cfg.gateways:
        console.print()
        console.print(warn(f"gateway context [bold]{name}[/bold] already exists"))
        console.print(info(f"[dim]axon ga use {name}[/dim]   to activate it"))
        console.print(info(f"[dim]axon ga list[/dim]          to see all contexts"))
        console.print()
        raise typer.Exit(1)

    effective_data_dir = data_dir or f".axon/ga/{name}"

    # cria estrutura de diretórios e arquivos
    cwd    = Path.cwd()
    ga_dir = Path(effective_data_dir)
    if not ga_dir.is_absolute():
        ga_dir = cwd / ga_dir

    p = GAPaths(ga_dir)
    p.makedirs()

    defaults = {
        p.registry:  {"version": "0.1.0", "resources": []},
        p.tokens:    {"version": "0.1.0", "tokens": []},
    }
    for path, content in defaults.items():
        if not path.exists():
            path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")

    # retrieval strategy
    ollama_host = typer.prompt("  Ollama host", default="http://localhost:11434")
    retrieval_strategy, embedding_model = pick_retrieval_strategy(ollama_host=ollama_host)

    # salva ga.json na instância
    ga_instance_cfg = {
        "name":               name,
        "port":               port,
        "data_dir":           effective_data_dir,
        "version":            "0.1.0",
        "retrieval_strategy": retrieval_strategy,
        "embedding_model":    embedding_model,
    }
    p.ga_config.write_text(json.dumps(ga_instance_cfg, indent=2) + "\n", encoding="utf-8")

    # registra no axon.config.json
    new_entry = GAInstanceConfig(
        name=name,
        port=port,
        data_dir=effective_data_dir,
        retrieval_strategy=retrieval_strategy,
        embedding_model=embedding_model,
    )

    def _add(c):
        new_gateways = dict(c.gateways)
        new_gateways[name] = new_entry
        return c.model_copy(update={"gateways": new_gateways})

    patch_config(_add)

    rel = ga_dir.relative_to(cwd) if ga_dir.is_relative_to(cwd) else ga_dir

    console.print()
    console.print(ok(f"[bold]{name}[/bold] initialized"))
    console.print()
    console.print(f"  [dim]name[/dim]      [cyan]{name}[/cyan]")
    console.print(f"  [dim]port[/dim]      [cyan]{port}[/cyan]")
    console.print(f"  [dim]data dir[/dim]  [cyan]{rel}[/cyan]")
    console.print(f"  [dim]retrieval[/dim] [cyan]{retrieval_strategy}[/cyan]", end="")
    if embedding_model:
        console.print(f"  [dim]model:[/dim] [cyan]{embedding_model}[/cyan]")
    else:
        console.print()
    console.print()
    console.print(f"  {step(f'[dim]{rel}/registry.json[/dim]')}")
    console.print(divider())
    console.print(f"  {step(f'[dim]{rel}/tokens.json[/dim]')}")
    console.print(divider())
    console.print(f"  {step(f'[dim]{rel}/traces/[/dim]')}")
    console.print()
    console.print(info("[dim]next steps[/dim]"))
    console.print(info(f"[dim]axon ga use {name}[/dim]           activate this context"))
    console.print(info(f"[dim]axon ga serve --context {name}[/dim]   start this gateway"))
    console.print()