import typer
import secrets
from axon.validator import validate_agent
from axon.types import Resource, ResourceType, ResourceStatus
from axon.registry import add_resource
from axon.tokens import mark_used
from axon.cli._print import console, ok, info, warn, step, divider, fatal
from urllib.parse import urlparse

app = typer.Typer(help="Register a resource with the Gateway.")

# Validar a URL - 
def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        fatal(f"Invalid URL: '{url}'. Expected format: http://host:port")


@app.command("agent")
def add_agent(
    url:  str        = typer.Argument(..., help="Agent endpoint URL (A2A)"),
    name: str | None = typer.Option(None, "--name", help="Override resource name"),
) -> None:
    """
    Register an A2A agent with the Gateway.
 
    Requires a token pre-issued via 'axon token generate'.
    The token must be present in the agent card under:
      capabilities.extensions[*].params["token"]
    """
    _validate_url(url)
 
    console.print(f"\n  {step(f'Validating agent at [cyan]{url}[/cyan]')}")
    console.print(divider())

    result = validate_agent(url)

    if not result.ok:
        step_labels = {
            "agent_card":    "agent card",
            "schema":        "schema validation",
            "axon_token":    "axon token",
            "axon_protocol": "axon protocol",
            "health":        "health check",
        }
        label = step_labels.get(result.step or "", result.step or "validation")
        console.print(f"  [red]■[/red] {label} failed\n")
        for line in (result.error or "").split("\n"):
            console.print(f"  [dim]{line}[/dim]")
        console.print()
        raise typer.Exit(1)

    card = result.agent_card
    assert card is not None
    axon_meta = card.axon
    assert axon_meta is not None

    console.print(f"  {step(f'agent card       [bold]{card.name}[/bold] v{card.version}')}")
    console.print(divider())
    console.print(f"  {step(f'axon token       registry=[cyan]{axon_meta.registry_id}[/cyan] · v{axon_meta.protocol_version} · [green]verified[/green]')}")
    console.print(divider())
    console.print(f"  {step('health check     [green]200 OK[/green]')}")
    console.print(divider())
    console.print(f"  {step(f'fingerprint      [dim]{result.fingerprint}[/dim]')}")
    console.print(divider())
    console.print()


    resource = Resource(
        id=f"res-{secrets.token_hex(3)}",
        type=ResourceType.agent,
        name=name or card.name,
        endpoint=url,
        description=card.description,
        skills=card.skills,
        fingerprint=result.fingerprint or "",
        token_ref=None,
        status=ResourceStatus.online,
    )
 
    try:
        add_resource(resource)
    except Exception as e:
        fatal(f"Could not write to registry: {e}")

     # Marca o token como usado após persistir o resource com sucesso
    assert result.verified_token is not None



    try:
        mark_used(result.verified_token, resource.id)
    except Exception:
        console.print(warn("could not update token status in .axon/tokens.json"))


    # Ping imediato pós-registro: GET agent card + fingerprint comparison
    health = check_agent(resource)
 
    console.print(f"  {ok(f'[bold]{resource.name}[/bold] registered')}\n")
    console.print(info(f"id          [dim]{resource.id}[/dim]"))
    console.print(info(f"type        [dim]agent (A2A)[/dim]"))
    console.print(info(f"skills      [dim]{', '.join(s.id for s in resource.skills) or '—'}[/dim]"))
    console.print(info(f"fingerprint [dim]{resource.fingerprint}[/dim]"))
    console.print(info(f"status      [green]online[/green]"))
    console.print(info(f"saved to    [dim].axon/registry.json[/dim]"))
    console.print()



# ─── axon remove 
 
remove_app = typer.Typer(help="Unregister a resource from the Gateway.")
 
 
@remove_app.callback(invoke_without_command=True)
def remove(
    name: str = typer.Argument(..., help="Resource name"),
) -> None:
    """Unregister a resource from the Gateway."""
    from axon.registry import remove_resource as _remove
 
    removed = _remove(name)
    if removed is None:
        fatal(f"Resource '{name}' not found in registry.")
 
    console.print()
    console.print(f"  {ok(f'[bold]{name}[/bold] removed from registry')}")
    console.print(info(f"type     [dim]{removed.type.value}[/dim]"))
    console.print(info(f"endpoint [dim]{removed.endpoint}[/dim]"))
    console.print()