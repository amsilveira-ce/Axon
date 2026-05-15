from __future__ import annotations 
import typer
from axon.cli._print import console, ok, fatal, divider, step
 
app = typer.Typer(help="Run the Principal Agent.")
 

@app.callback(invoke_without_command=True)
def run(
    query: str = typer.Option(..., "--query", "-q", help="Query to send to the Principal Agent"),
) -> None:
    
    from axon.config import read_config
    from axon.pa.agent import PrincipalAgent
 
    try:
        # Iniciar o PA dependende do arquivo de configuração 
        config = read_config()
    except FileNotFoundError:
        fatal('axon.config.json not found. Run "axon init" first.')
 
    console.print()
    console.print(f"  {step(f'query  [dim]{query}[/dim]')}")
    console.print(divider())
 
    agent = PrincipalAgent(config.pa)
 
    try:
        response = agent.run(query)
    except Exception as exc:
        fatal(f"Agent error: {exc}")
 
    console.print()
    console.print(f"  {ok('[bold]response[/bold]')}")
    console.print()
    for line in response.splitlines():
        console.print(f"  [dim]│[/dim]  {line}")
    console.print()