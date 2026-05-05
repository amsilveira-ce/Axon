import typer
from rich.table import Table
from rich import box
from axon.cli._print import console, ok, info, warn, fatal, divider, step
from axon.tokens import generate


app = typer.Typer(help="Manage Axon registration tokens.")

@app.command("generate")
def token_generate(
    name: str = typer.Option(..., "--name", "-n", help="Name of the agent or MCP tool this token is for"),
) -> None:
    """
    Generate a registration token for an agent or MCP tool.
 
    The token must be added to the resource before running 'axon add agent'
    or 'axon add mcp'. Tokens are single-use by default.
    """
    try:
        token = generate(name)
    except Exception as e:
        fatal(f"Could not generate token: {e}")
 
    console.print(f"\n  {ok(f'Token generated for [bold]{name}[/bold]')}\n")
    console.print(info(f"token   [cyan]{token.token}[/cyan]"))
    console.print(info(f"status  [dim]{token.status.value}[/dim]"))
    console.print(info(f"uses    [dim]{token.max_uses} (single-use)[/dim]"))
    console.print()
    console.print(f"  [dim]Add to your agent card:[/dim]")
    console.print()
    console.print(f'  [dim]"metadata": {{[/dim]')
    console.print(f'  [dim]  "axon": {{[/dim]')
    console.print(f'  [dim]    "token": "[/dim][cyan]{token.token}[/cyan][dim]",[/dim]')
    console.print(f'  [dim]    "registry_id": "local",[/dim]')
    console.print(f'  [dim]    "protocol_version": "0.1"[/dim]')
    console.print(f'  [dim]  }}[/dim]')
    console.print(f'  [dim]}}[/dim]')
    console.print()
    console.print(f"  [dim]Or to your MCP manifest:[/dim]")
    console.print()
    console.print(f'  [dim]"axon": {{[/dim]')
    console.print(f'  [dim]  "token": "[/dim][cyan]{token.token}[/cyan][dim]",[/dim]')
    console.print(f'  [dim]  "registry_id": "local",[/dim]')
    console.print(f'  [dim]  "protocol_version": "0.1"[/dim]')
    console.print(f'  [dim]}}[/dim]')
    console.print()
    console.print(info("[dim]saved to .axon/tokens.json[/dim]"))
    console.print()
 