import typer
from axon.config import (
    AxonConfig, PAConfig, GAConfig, config_exists, write_config, OperationalMode, ReasoningMode
)
from axon.cli._print import console, warn, ok, fatal

app = typer.Typer()


@app.callback(invoke_without_command=True)
def init(
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept all defaults without prompting"),
) -> None:
    """Create axon.config.json in the current directory."""

    if config_exists():
        console.print(warn("axon.config.json already exists — delete it to re-initialize."))
        raise typer.Exit(1)

    console.print("\n  [bold]Axon[/bold] [dim]v0.1.0[/dim]\n")

    pa = PAConfig()
    ga = GAConfig()

    if not yes:
        raw = typer.prompt("  PA control API port", default=str(pa.port))
        pa.port = int(raw)

        raw = typer.prompt("  Gateway Agent port", default=str(ga.port))
        ga.port = int(raw)

        raw = typer.prompt("  Default PA mode (agent/copilot/no-llm)", default=pa.default_mode.value)
        if raw not in OperationalMode._value2member_map_:
            console.print(warn(f"Unknown mode '{raw}', using default: {pa.default_mode.value}"))
        else:
            pa.default_mode = OperationalMode(raw)

        raw = typer.prompt("  Default reasoning mode (react/rewoo/tot)", default=pa.default_reasoning_mode.value)
        if raw not in ReasoningMode._value2member_map_:
            console.print(warn(f"Unknown reasoning '{raw}', using default: {pa.default_reasoning_mode.value}"))
        else:
            pa.default_reasoning_mode = ReasoningMode(raw)

        raw = typer.prompt("  Max PA iterations", default=str(pa.max_iterations))
        pa.max_iterations = int(raw)

    config = AxonConfig(pa=pa, ga=ga)

    try:
        write_config(config)
    except Exception as e:
        fatal(f"Could not write axon.config.json: {e}")

    console.print()
    console.print(ok("[bold]axon.config.json[/bold] created"))
    console.print()
    console.print(f"  [dim]PA[/dim]    localhost:[cyan]{pa.port}[/cyan]")
    console.print(f"  [dim]GA[/dim]    localhost:[cyan]{ga.port}[/cyan]")
    console.print(f"  [dim]mode[/dim]  [cyan]{pa.default_mode.value}[/cyan] [dim]·[/dim] [cyan]{pa.default_reasoning_mode.value}[/cyan]")
    console.print()
    console.print("  [dim]Next steps[/dim]")
    console.print("    [dim]axon run dev ga[/dim]              start the Gateway Agent + UI")
    console.print("    [dim]axon run dev pa[/dim]              start the Principal Agent + UI")
    console.print("    [dim]axon pa gateway add <url>[/dim]    connect a Gateway to the PA")
    console.print()
