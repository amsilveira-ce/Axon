import typer
from rich.table import Table
from rich import box
from datetime import timezone
from axon.cli._print import console, ok, info, warn, fatal, divider, step
from axon.tokens import generate, list_tokens, TokenVerificationError, revoke


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

@app.command("list")
def token_list(
    show_all: bool = typer.Option(False, "--all", help="Include used and revoked tokens"),
) -> None:
    """List registration tokens in the local store."""
    tokens = list_tokens()
 
    if not show_all:
        tokens = [t for t in tokens if t.status.value == "pending"]
 
    console.print()
 
    if not tokens:
        if show_all:
            console.print(f"  [dim]No tokens found in .axon/tokens.json[/dim]")
        else:
            console.print(f"  [dim]No pending tokens. Run 'axon token generate --name <name>'[/dim]")
        console.print()
        return
 
    table = Table(box=box.SIMPLE, show_header=True, header_style="dim", pad_edge=False)
    table.add_column("TOKEN",   style="cyan",    no_wrap=True)
    table.add_column("NAME",    style="default", no_wrap=True)
    table.add_column("STATUS",  style="default", no_wrap=True)
    table.add_column("USED BY", style="dim",     no_wrap=True)
    table.add_column("CREATED", style="dim",     no_wrap=True)
 
    status_colors = {
        "pending": "[yellow]pending[/yellow]",
        "used":    "[green]used[/green]",
        "revoked": "[red]revoked[/red]",
    }
 
    for t in tokens:
        short = t.token[:24] + "..."
        created = t.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
        status_str = status_colors.get(t.status.value, t.status.value)
        table.add_row(short, t.name, status_str, t.used_by or "—", created)
 
    console.print(table)
    console.print(info(f"[dim]{len(tokens)} token(s) · use --all to include used/revoked[/dim]"))
    console.print()

@app.command("revoke")
def token_revoke(
    token_value: str = typer.Argument(..., help="Token value to revoke (axon_tk_...)"),
) -> None:
    """
    Revoke a registration token.
 
    Revoked tokens are rejected in future registrations.
    Resources already registered with this token are not immediately affected
    — their status updates on the next 'axon ga resource ping'.
    """
    try:
        entry = revoke(token_value)
    except TokenVerificationError as e:
        fatal(str(e))
 
    console.print()
    console.print(f"  {ok(f'Token for [bold]{entry.name}[/bold] revoked')}")
    console.print(info(f"[dim]{entry.token[:24]}...[/dim]"))
    if entry.used_by:
        console.print(info(f"[dim]was used by resource {entry.used_by}[/dim]"))
        console.print(warn("run 'axon ga resource ping --all' to update resource status"))
    console.print()