import typer 
from axon.config import (
    AxonConfig, PAConfig, GAConfig, config_exists, write_config, OperationalMode, ReasoningMode
)
from axon.cli._print import console, warn, info, ok, fatal, answered, divider, question

app = typer.Typer()

@app.command()
def _prompt(label: str, default: str, hint: str = "") -> str:

    hint_str = f" [dim]({hint})[/dim]" if hint else ""


    # Imprime a linha de pergunta
    console.print(f"{question(label)}{hint_str}  [dim][{default}][/dim]")

    # Lê input sem mostrar default extra (show_default=False)
    value = typer.prompt("  ›", default=default, show_default=False, prompt_suffix=" ")
    resolved = value.strip() or default


    # Volta 2 linhas (pergunta + input) e reescreve como confirmada
    console.print(f"\x1b[2A\x1b[0J{answered(label, resolved)}")
    return resolved
 
 
@app.callback(invoke_without_command=True)
def init(
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept all defaults without prompting"),
) -> None:
    """Create axon.config.json in the current directory."""
 
    if config_exists():
        console.print(warn("axon.config.json already exists in this directory."))
        console.print(warn("Delete it first if you want to re-initialize."))
        raise typer.Exit(1)
 
    console.print(f"\n  [bold]✦ AXON[/bold] [dim]v0.1.0[/dim]\n")
    console.print(divider())
 
    pa = PAConfig()
    ga = GAConfig()
 
    if not yes:
 
        raw = _prompt("PA control API port", str(pa.port))
        pa.port = int(raw)
        console.print(divider())
 
        raw = _prompt("Gateway Agent port", str(ga.port))
        ga.port = int(raw)
        console.print(divider())
 
        raw = _prompt("Default PA mode", pa.default_mode.value, hint="agent / copilot / no-llm")
        if raw not in OperationalMode._value2member_map_:
            console.print(warn(f"Unknown mode '{raw}', using: {pa.default_mode.value}"))
        else:
            pa.default_mode = OperationalMode(raw)
        console.print(divider())
 
        raw = _prompt("Default reasoning mode", pa.default_reasoning_mode.value, hint="react / rewoo / tot")
        if raw not in ReasoningMode._value2member_map_:
            console.print(warn(f"Unknown reasoning '{raw}', using: {pa.default_reasoning_mode.value}"))
        else:
            pa.default_reasoning_mode = ReasoningMode(raw)
        console.print(divider())
 
        raw = _prompt("Max PA iterations", str(pa.max_iterations))
        pa.max_iterations = int(raw)
 
    else:
        console.print(answered("PA control API port",    str(pa.port)))
        console.print(divider())
        console.print(answered("Gateway Agent port",     str(ga.port)))
        console.print(divider())
        console.print(answered("Default PA mode",        pa.default_mode.value))
        console.print(divider())
        console.print(answered("Default reasoning mode", pa.default_reasoning_mode.value))
        console.print(divider())
        console.print(answered("Max PA iterations",      str(pa.max_iterations)))
 
    console.print(divider())
    console.print()
 
    config = AxonConfig(pa=pa, ga=ga)
 
    try:
        write_config(config)
    except Exception as e:
        fatal(f"Could not write axon.config.json: {e}")
 
    console.print(f"  {ok('[bold]axon.config.json[/bold] created')}\n")
    console.print(info(f"PA  [dim]→[/dim]  localhost:[cyan]{pa.port}[/cyan]"))
    console.print(info(f"GA  [dim]→[/dim]  localhost:[cyan]{ga.port}[/cyan]"))
    console.print(info(f"mode  [cyan]{pa.default_mode.value}[/cyan] [dim]·[/dim] [cyan]{pa.default_reasoning_mode.value}[/cyan]"))
    console.print()
    console.print(f"  [dim]Next steps[/dim]")
    console.print(info("[dim]axon run dev ga[/dim]              start the Gateway Agent + UI"))
    console.print(info("[dim]axon run dev pa[/dim]              start the Principal Agent + UI"))
    console.print(info("[dim]axon pa gateway add <url>[/dim]    connect a Gateway to the PA"))
    console.print()
