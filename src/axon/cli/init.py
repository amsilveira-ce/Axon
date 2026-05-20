from __future__ import annotations

import json
from pathlib import Path

import typer

from axon.config import (
    AxonConfig, PAConfig, GAConfig,
    config_exists, write_config,
    resolve_data_dir, AxonPaths,
)
from axon.types import OperationalMode, ReasoningMode
from axon.cli._print import console, warn, ok, fatal, info, step, divider

app = typer.Typer()


def _bootstrap_files(p: AxonPaths) -> None:
    """
    Cria diretórios e arquivos JSON iniciais (idempotente).
    Separado de AxonPaths.makedirs() porque init também escreve
    os arquivos vazios com estrutura válida.
    """
    p.makedirs()

    if not p.ga_registry.exists():
        p.ga_registry.write_text(
            json.dumps({"version": "0.1.0", "resources": []}, indent=2) + "\n",
            encoding="utf-8",
        )

    if not p.ga_tokens.exists():
        p.ga_tokens.write_text(
            json.dumps({"version": "0.1.0", "tokens": []}, indent=2) + "\n",
            encoding="utf-8",
        )

    if not p.pa_resource_cache.exists():
        p.pa_resource_cache.write_text(
            json.dumps({"version": "0.1.0", "resources": []}, indent=2) + "\n",
            encoding="utf-8",
        )

    if not p.pa_memory_bank.exists():
        p.pa_memory_bank.write_text(
            json.dumps({"version": "0.1.0", "entries": []}, indent=2) + "\n",
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
        console.print(info("[cyan]axon.config.json[/cyan] already exists in this directory."))
        console.print(info("To start over, delete the file and run [bold]axon init[/bold] again."))
        console.print()
        raise typer.Exit(1)

    console.print("\n  [bold]Axon[/bold] [dim]v0.1.0[/dim]\n")

    pa = PAConfig()
    ga = GAConfig()

    if not yes:
        raw = typer.prompt("  PA control API port", default=str(pa.port))
        pa.port = int(raw)

        raw = typer.prompt("  Gateway Agent port", default=str(ga.port))
        ga.port = int(raw)

        raw = typer.prompt(
            "  Default PA mode (agent/copilot/no-llm)",
            default=pa.default_mode.value,
        )
        if raw not in OperationalMode._value2member_map_:
            console.print(warn(f"Unknown mode '{raw}', using default: {pa.default_mode.value}"))
        else:
            pa.default_mode = OperationalMode(raw)

        raw = typer.prompt(
            "  Default reasoning mode (react/rewoo/tot)",
            default=pa.default_reasoning_mode.value,
        )
        if raw not in ReasoningMode._value2member_map_:
            console.print(warn(f"Unknown reasoning '{raw}', using default: {pa.default_reasoning_mode.value}"))
        else:
            pa.default_reasoning_mode = ReasoningMode(raw)

        raw = typer.prompt("  Max PA iterations", default=str(pa.max_iterations))
        pa.max_iterations = int(raw)

        data_dir = typer.prompt("  Data directory", default=data_dir)

    config = AxonConfig(pa=pa, ga=ga, data_dir=data_dir)

    # ── escreve axon.config.json ─────────────────────────
    try:
        write_config(config)
    except Exception as e:
        fatal(f"Could not write axon.config.json: {e}")

    # ── cria estrutura data_dir/ ─────────────────────────
    cwd   = Path.cwd()
    p     = AxonPaths(resolve_data_dir(data_dir, cwd))

    try:
        _bootstrap_files(p)
    except Exception as e:
        fatal(f"Could not create data directory structure: {e}")

    # ── output ───────────────────────────────────────────
    rel = p.root.relative_to(cwd) if p.root.is_relative_to(cwd) else p.root

    console.print()
    console.print(ok("[bold]axon.config.json[/bold] created"))
    console.print()
    console.print(f"  [dim]PA[/dim]       localhost:[cyan]{pa.port}[/cyan]")
    console.print(f"  [dim]GA[/dim]       localhost:[cyan]{ga.port}[/cyan]")
    console.print(f"  [dim]mode[/dim]     [cyan]{pa.default_mode.value}[/cyan] [dim]·[/dim] [cyan]{pa.default_reasoning_mode.value}[/cyan]")
    console.print(f"  [dim]data dir[/dim] [cyan]{rel}[/cyan]")
    console.print()
    console.print(f"  {step(f'[dim]{rel}/ga/registry.json[/dim]')}")
    console.print(divider())
    console.print(f"  {step(f'[dim]{rel}/ga/tokens.json[/dim]')}")
    console.print(divider())
    console.print(f"  {step(f'[dim]{rel}/ga/traces/[/dim]')}")
    console.print(divider())
    console.print(f"  {step(f'[dim]{rel}/pa/sessions/[/dim]')}")
    console.print(divider())
    console.print(f"  {step(f'[dim]{rel}/pa/resource_cache.json[/dim]')}")
    console.print(divider())
    console.print(f"  {step(f'[dim]{rel}/pa/memory_bank.json[/dim]')}")
    console.print(divider())
    console.print(f"  {step(f'[dim]{rel}/pa/traces/[/dim]')}")
    console.print()
    console.print("  [dim]Next steps[/dim]")
    console.print(info("[dim]axon ga serve[/dim]                 start the Gateway Agent"))
    console.print(info("[dim]axon pa run --query '...'[/dim]     one-shot query"))
    console.print(info("[dim]axon pa chat[/dim]                  interactive session"))
    console.print(info("[dim]axon pa gateway add <url>[/dim]     connect a Gateway to the PA"))
    console.print()