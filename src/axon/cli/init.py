import typer 
from axon.config import (
    AxonConfig, PAConfig, GAConfig, config_exists, write_config, OperationalMode, ReasoningMode
)
from axon.cli._print import console, warn, info, ok, fatal

app = typer.Typer()

@app.command()
def main():
   
    if config_exists():
        # Checamos se o arquivo de configuração já existe, caso existe printamos um alerta
        console.print(warn("axon.config.json already exists in this directory."))
        console.print(warn('Delete it first if you want to re-initialize.'))
        raise typer.Exit(1)
   
    console.print(f"\n  [bold]✦ AXON[/bold] — initializing project\n")

    pa = PAConfig()
    ga = GAConfig()

    # Porta do Principal Agent
    raw = typer.prompt("  PA control API port", default=str(pa.port))
    pa.port = int(raw)

    # Porta do Gateway Agent
    raw = typer.prompt("  GA port            ", default=str(ga.port))
    ga.port = int(raw)

    # Modo operacional default
    raw = typer.prompt( "  Default PA mode     [agent/copilot/no-llm]",default=pa.default_mode.value)

    if raw not in OperationalMode._value2member_map_:
        console.print(warn(f"Unknown mode '{raw}', using default: {pa.default_mode.value}"))
    else: 
        pa.default_mode = OperationalMode(raw)

    # Reasoning Mode 
    raw = typer.prompt("  Default reasoning   [react/rewoo/tot]",default=pa.default_reasoning_mode.value,)
    if raw not in ReasoningMode._value2member_map_:
        console.print(warn(f"Unknown reasoning mode '{raw}', using default: {pa.default_reasoning_mode.value}"))
    else:
        pa.default_reasoning_mode = ReasoningMode(raw)

    
    raw = typer.prompt("  Max PA iterations  ", default=str(pa.max_intractions))
    pa.max_intractions = int(raw)

    config = AxonConfig(pa=pa, ga=ga)

    try:
        write_config(config)
    except Exception as e:
        fatal(f"Could not write axon.config.json: {e}")
 
    console.print()
    console.print(f"  {ok('[bold]axon.config.json[/bold] created')}")
    console.print(info(f"PA control API  →  localhost:[cyan]{pa.port}[/cyan]"))
    console.print(info(f"Gateway Agent   →  localhost:[cyan]{ga.port}[/cyan]"))
    console.print(info(f"Default mode    →  [cyan]{pa.default_mode.value}[/cyan] · [cyan]{pa.default_reasoning_mode.value}[/cyan]"))
    console.print()
    console.print(info("Next steps:"))
    console.print(info("  [dim]axon run dev ga[/dim]           start the Gateway Agent + UI"))
    console.print(info("  [dim]axon run dev pa[/dim]           start the Principal Agent + UI"))
    console.print(info("  [dim]axon pa gateway add <url>[/dim]  connect a Gateway to the PA"))
    console.print()

if __name__ == "__main__":
    app()