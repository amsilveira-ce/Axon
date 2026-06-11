import typer
from rich.table import Table
from rich import box
from datetime import timezone
from axon.cli._print import console, ok, info, warn, fatal, divider, step
from axon.ga.tokens import generate, list_tokens, TokenVerificationError, revoke


app = typer.Typer(help="Create, inspect, and revoke Axon registration tokens.")

@app.command(
    "generate",
    short_help="Mint a single-use admission token for an agent or MCP resource.",
)
def token_generate(
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Label for this token — used to identify which agent or MCP tool it is intended for (e.g. 'tavily-search', 'my-agent'). Shown in 'axon token list' and audit logs; does not restrict which resource can consume it.",
    ),
    gateway: str | None = typer.Option(None, "--gateway", help="GA context to generate the token in (default: active context)"),
) -> None:
    """
    Create a single-use admission token that a resource must present when registering with the Gateway.

    \b
    Workflow:
      1. Run this command to mint a token labelled for the resource you're about to register.
      2. Pass the token via --token when running 'axon add agent' or 'axon add resource'.
         For A2A agents you can also embed it in the agent card under capabilities.extensions.
      3. The Gateway burns the token on first use — any second registration attempt is rejected.

    The --name flag is a human-readable label stored alongside the token so you can track
    which token belongs to which resource in 'axon token list'. It does not restrict which
    resource can consume the token.
    """
    from axon.ga.config import GAConfig
    ga = GAConfig.resolve(gateway)
    try:
        token = generate(name, ga.paths)
    except Exception as e:
        fatal(f"Could not generate token: {e}")

    console.print()
    console.print(info(f"[dim]context: {ga.context} ({ga.name})[/dim]"))
    console.print(f"\n  {ok(f'Token generated for [bold]{name}[/bold]')}\n")
    console.print(info(f"token   [cyan]{token.token}[/cyan]"))
    console.print(info(f"status  [dim]{token.status.value}[/dim]"))
    console.print(info(f"uses    [dim]{token.max_uses} (single-use)[/dim]"))
    console.print(info(f"saved   [dim]{ga.paths.tokens}[/dim]"))
    console.print()
    console.print(f"  [dim]Add to your agent card capabilities.extensions:[/dim]")
    console.print()
    console.print(f'  [dim]"capabilities": {{[/dim]')
    console.print(f'  [dim]  "extensions": [[/dim]')
    console.print(f'  [dim]    {{[/dim]')
    console.print(f'  [dim]      "uri": "https://axon-framework.dev/extensions/registry/v1",[/dim]')
    console.print(f'  [dim]      "params": {{[/dim]')
    console.print(f'  [dim]        "token": "[/dim][cyan]{token.token}[/cyan][dim]",[/dim]')
    console.print(f'  [dim]        "registry_id": "local",[/dim]')
    console.print(f'  [dim]        "protocol_version": "0.1"[/dim]')
    console.print(f'  [dim]      }}[/dim]')
    console.print(f'  [dim]    }}[/dim]')
    console.print(f'  [dim]  ][/dim]')
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
    console.print()

@app.command("list")
def token_list(
    show_all:      bool       = typer.Option(False, "--all",           help="Include used and revoked tokens"),
    all_contexts:  bool       = typer.Option(False, "--all-contexts",  help="List tokens from every registered GA context"),
    gateway:       str | None = typer.Option(None,  "--gateway",       help="GA context to list tokens from (default: active context)"),
) -> None:
    """List registration tokens in the local store."""
    from pathlib import Path
    from axon.ga.config import GAConfig, GAPaths

    status_colors = {
        "pending": "[yellow]pending[/yellow]",
        "used":    "[green]used[/green]",
        "revoked": "[red]revoked[/red]",
    }

    # ── collect (context_name, tokens) pairs ──────────────────────────────────
    if all_contexts:
        try:
            from axon.config import read_config
            cfg = read_config()
            contexts = list(cfg.gateways.items())
        except FileNotFoundError:
            ga = GAConfig.resolve()
            contexts = [(ga.context, ga.instance)]
        rows: list[tuple[str, object]] = []
        for ctx_name, instance in contexts:
            p = Path(instance.data_dir)
            ga_dir = p if p.is_absolute() else Path.cwd() / p
            tkns = list_tokens(GAPaths(ga_dir))
            if not show_all:
                tkns = [t for t in tkns if t.status.value == "pending"]
            for t in tkns:
                rows.append((ctx_name, t))

        console.print()
        if not rows:
            console.print(f"  [dim]No {'tokens' if show_all else 'pending tokens'} across any context.[/dim]")
            console.print()
            return

        table = Table(box=box.SIMPLE, show_header=True, header_style="dim", pad_edge=False)
        table.add_column("CONTEXT", style="dim",     no_wrap=True)
        table.add_column("TOKEN",   style="cyan",    no_wrap=True)
        table.add_column("NAME",    style="default", no_wrap=True)
        table.add_column("STATUS",  style="default", no_wrap=True)
        table.add_column("USED BY", style="dim",     no_wrap=True)
        table.add_column("CREATED", style="dim",     no_wrap=True)

        for ctx_name, t in rows:
            short   = t.token[:24] + "..."
            created = t.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
            table.add_row(ctx_name, short, t.name, status_colors.get(t.status.value, t.status.value), t.used_by or "—", created)

        console.print(table)
        console.print(info(f"[dim]{len(rows)} token(s) across {len(contexts)} context(s)[/dim]"))
        console.print()
        return

    # ── single context ─────────────────────────────────────────────────────────
    ga = GAConfig.resolve(gateway)
    tokens = list_tokens(ga.paths)

    if not show_all:
        tokens = [t for t in tokens if t.status.value == "pending"]

    console.print()
    console.print(info(f"[dim]context: {ga.context} ({ga.name})[/dim]"))
    console.print()

    if not tokens:
        if show_all:
            console.print(f"  [dim]No tokens found.[/dim]")
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

    for t in tokens:
        short   = t.token[:24] + "..."
        created = t.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
        table.add_row(short, t.name, status_colors.get(t.status.value, t.status.value), t.used_by or "—", created)

    console.print(table)
    console.print(info(f"[dim]{len(tokens)} token(s) · use --all to include used/revoked[/dim]"))
    console.print()

@app.command("revoke")
def token_revoke(
    token_value: str       = typer.Argument(..., help="Token value to revoke (axon_tk_...)"),
    gateway:     str | None = typer.Option(None, "--gateway", help="GA context to revoke the token in (default: active context)"),
) -> None:
    """
    Revoke a registration token.
 
    Revoked tokens are rejected in future registrations.
    Resources already registered with this token are not immediately affected
    — their status updates on the next 'axon ga resource ping'.
    """
    from axon.ga.config import GAConfig
    ga = GAConfig.resolve(gateway)
    try:
        entry = revoke(token_value, ga.paths)
    except TokenVerificationError as e:
        fatal(str(e))

    console.print()
    console.print(info(f"[dim]context: {ga.context} ({ga.name})[/dim]"))
    console.print(f"\n  {ok(f'Token for [bold]{entry.name}[/bold] revoked')}")
    console.print(info(f"[dim]{entry.token[:24]}...[/dim]"))
    if entry.used_by:
        console.print(info(f"[dim]was used by resource {entry.used_by}[/dim]"))
        console.print(warn("run 'axon ga resource ping --all' to update resource status"))
    console.print()
