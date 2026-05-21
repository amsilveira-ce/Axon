from __future__ import annotations

import json
from pathlib import Path

import typer

from axon.config import (
    AxonConfig, PAConfig, GAConfig,
    DEFAULT_LOCAL_TOOLS,
    config_exists, write_config,
    resolve_data_dir, AxonPaths,
)
from axon.cli._print import console, warn, ok, fatal, info, step, divider

app = typer.Typer()


def _bootstrap_files(p: AxonPaths) -> None:
    p.makedirs()

    defaults = {
        p.ga_registry:       {"version": "0.1.0", "resources": []},
        p.ga_tokens:         {"version": "0.1.0", "tokens": []},
        p.pa_resource_cache: {"version": "0.1.0", "resources": []},
        p.pa_memory_bank:    {"version": "0.1.0", "entries": []},
        p.pa_local_tools:    DEFAULT_LOCAL_TOOLS,
    }

    for path, content in defaults.items():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(content, indent=2) + "\n",
                encoding="utf-8",
            )


@app.callback(invoke_without_command=True)
def init(
    yes:      bool = typer.Option(False, "--defaults", "-d", help="Use all default values without prompting"),
    data_dir: str  = typer.Option(".axon", "--data-dir", help="Directory for runtime data (default: .axon)"),
) -> None:
    """Initialize Axon in the current directory."""

    if config_exists():
        console.print()
        console.print(warn("[bold]Already initialized[/bold]"))
        console.print()
        console.print(info("[cyan]axon.config.json[/cyan] already exists."))
        console.print(info("To start over, run [bold]bash scripts/reset.sh[/bold]"))
        console.print()
        raise typer.Exit(1)

    console.print("\n  [bold]Axon[/bold] [dim]v0.1.0[/dim]\n")

    pa = PAConfig()
    ga = GAConfig()

    if not yes:
        raw = typer.prompt("  PA control API port", default=str(pa.port))
        pa = pa.model_copy(update={"port": int(raw)})

        raw = typer.prompt("  Gateway Agent port", default=str(ga.port))
        ga = ga.model_copy(update={"port": int(raw)})

        raw = typer.prompt("  Default reasoning mode (react/rewoo/tot)", default=pa.default_reasoning)
        if raw in ("react", "rewoo", "tot"):
            pa = pa.model_copy(update={"default_reasoning": raw})
        else:
            console.print(warn(f"Unknown mode '{raw}', using default: {pa.default_reasoning}"))

        raw = typer.prompt("  Max PA iterations", default=str(pa.max_iterations))
        pa = pa.model_copy(update={"max_iterations": int(raw)})

        data_dir = typer.prompt("  Data directory", default=data_dir)

    config = AxonConfig(pa=pa, ga=ga, data_dir=data_dir)

    try:
        write_config(config)
    except Exception as e:
        fatal(f"Could not write axon.config.json: {e}")

    cwd = Path.cwd()
    p   = AxonPaths(resolve_data_dir(data_dir, cwd))

    try:
        _bootstrap_files(p)
    except Exception as e:
        fatal(f"Could not create data directory structure: {e}")

    rel = p.root.relative_to(cwd) if p.root.is_relative_to(cwd) else p.root

    console.print()
    console.print(ok("[bold]axon.config.json[/bold] created"))
    console.print()
    console.print(f"  [dim]PA[/dim]        localhost:[cyan]{pa.port}[/cyan]")
    console.print(f"  [dim]GA[/dim]        localhost:[cyan]{ga.port}[/cyan]")
    console.print(f"  [dim]reasoning[/dim]  [cyan]{pa.default_reasoning}[/cyan]")
    console.print(f"  [dim]data dir[/dim]  [cyan]{rel}[/cyan]")
    console.print()
    console.print(f"  {step(f'[dim]{rel}/ga/registry.json[/dim]')}")
    console.print(divider())
    console.print(f"  {step(f'[dim]{rel}/ga/tokens.json[/dim]')}")
    console.print(divider())
    console.print(f"  {step(f'[dim]{rel}/pa/sessions/[/dim]')}")
    console.print(divider())
    console.print(f"  {step(f'[dim]{rel}/pa/memory_bank.json[/dim]')}")
    console.print(divider())
    console.print(f"  {step(f'[dim]{rel}/pa/resource_cache.json[/dim]')}")
    console.print(divider())
    console.print(f"  {step(f'[dim]{rel}/pa/local_tools.json[/dim]  [dim]4 tools[/dim]')}")
    console.print()

    # lista tools registradas
    tools = DEFAULT_LOCAL_TOOLS.get("tools", [])
    console.print("  [dim]Local tools registered:[/dim]")
    for t in tools:
        console.print(info(f"[dim]{t['name']:<14} → {t['capability']}[/dim]"))
    console.print()
    console.print("  [dim]Next steps[/dim]")
    console.print(info("[dim]axon pa run --query '...'[/dim]"))
    console.print(info("[dim]axon pa chat[/dim]"))
    console.print(info("[dim]axon pa tools list[/dim]"))
    console.print()