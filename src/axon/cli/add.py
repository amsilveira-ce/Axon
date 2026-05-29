from __future__ import annotations

import secrets

import typer

from axon.cli._print import console, ok, info, warn, step, divider, fatal
from urllib.parse import urlparse

app = typer.Typer(help="Register a resource with the Gateway.")


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
    Register an A2A agent with the active Gateway.

    Requires a token pre-issued via 'axon token generate'.
    The token must be present in the agent card under:
      capabilities.extensions[*].params["token"]

    Operates on the active GA context (axon ga context to check,
    axon ga use <name> to switch).
    """
    from axon.ga.config import GAConfig
    from axon.ga.registry import add_resource, update_status
    from axon.ga.tokens import mark_used, read_store
    from axon.health import check_agent
    from axon.types import Resource, ResourceType, ResourceStatus
    from axon.validator import validate_agent

    _validate_url(url)

    # resolve GA ativo — todos os path-dependent calls usam ga.paths
    ga = GAConfig.resolve()

    console.print()
    console.print(info(f"[dim]context: {ga.context} ({ga.name})[/dim]"))
    console.print(f"\n  {step(f'Validating agent at [cyan]{url}[/cyan]')}")
    console.print(divider())

    result = validate_agent(url, ga.paths)

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

    card      = result.agent_card
    axon_meta = card.axon
    assert card is not None and axon_meta is not None

    console.print(f"  {step(f'agent card       [bold]{card.name}[/bold] v{card.version}')}")
    console.print(divider())
    console.print(f"  {step(f'axon token       registry=[cyan]{axon_meta.registry_id}[/cyan] · v{axon_meta.protocol_version} · [green]verified[/green]')}")
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
        add_resource(resource, ga.paths)
    except Exception as e:
        fatal(f"Could not write to registry: {e}")

    assert result.verified_token is not None
    try:
        mark_used(result.verified_token, resource.id, ga.paths)
    except Exception:
        console.print(warn("could not update token status"))

    # ping imediato pós-registro
    health = check_agent(resource)
    try:
        update_status(resource.id, health.status, ga.paths)
    except Exception:
        pass

    if health.status == ResourceStatus.online:
        console.print(f"  {step('health check     [green]online[/green] · fingerprint ok')}")
    elif health.status == ResourceStatus.validating:
        console.print(f"  {step('health check     [yellow]drift detected[/yellow] · agent card changed')}")
        for line in (health.error or "").split("\n"):
            console.print(f"  [dim]{line}[/dim]")
    else:
        console.print(f"  {step('health check     [red]offline[/red]')}")
        console.print(f"  [dim]{health.error}[/dim]")

    console.print(divider())
    console.print()

    console.print(f"  {ok(f'[bold]{resource.name}[/bold] registered')}\n")
    console.print(info(f"id          [dim]{resource.id}[/dim]"))
    console.print(info(f"type        [dim]agent (A2A)[/dim]"))
    console.print(info(f"skills      [dim]{', '.join(s.id for s in resource.skills) or '—'}[/dim]"))
    console.print(info(f"endpoint    [dim]{url}[/dim]"))
    console.print(info(f"fingerprint [dim]{resource.fingerprint}[/dim]"))
    console.print(info(f"context     [dim]{ga.context}[/dim]"))
    console.print(info(f"saved to    [dim]{ga.paths.registry}[/dim]"))

    status_display = {
        ResourceStatus.online:     "[green]online[/green]",
        ResourceStatus.validating: "[yellow]drift detected — re-register to update[/yellow]",
        ResourceStatus.offline:    "[red]offline — agent unreachable after registration[/red]",
    }.get(health.status, health.status.value)
    console.print(info(f"status      {status_display}"))
    console.print()

    # aviso de expiração do token
    store       = read_store(ga.paths)
    token_entry = next((t for t in store.tokens if t.used_by == resource.id), None)
    if token_entry and token_entry.expires_at:
        from datetime import datetime, timezone
        remaining = token_entry.expires_at - datetime.now(timezone.utc)
        hours     = int(remaining.total_seconds() / 3600)
        if hours < 24:
            console.print()
            console.print(warn(f"token expires in {hours}h — re-register before expiry to stay online"))

    # next steps
    console.print(f"  [dim]next steps[/dim]")
    if axon_meta.registry_id == "local":
        console.print(info("[dim]axon ga resource list[/dim]           view all registered resources"))
        console.print(info("[dim]axon ga resource ping[/dim]           verify resources are reachable"))
        console.print(info("[dim]axon pa gateway add <ga-url>[/dim]   connect this GA to a PA"))
    else:
        console.print(info(f"[dim]registry  {axon_meta.registry_id}[/dim]"))
        if axon_meta.registry_url:
            console.print(info(f"[dim]verify at {axon_meta.registry_url}[/dim]"))
    console.print()


# ── remove ────────────────────────────────────────────────────────────────────

remove_app = typer.Typer(help="Unregister a resource from the Gateway.")


@remove_app.callback(invoke_without_command=True)
def remove(
    name: str = typer.Argument(..., help="Resource name"),
) -> None:
    """Unregister a resource from the active Gateway."""
    from axon.ga.config import GAConfig
    from axon.ga.registry import remove_resource as _remove

    ga      = GAConfig.resolve()
    removed = _remove(name, ga.paths)

    if removed is None:
        fatal(f"Resource '{name}' not found in registry '{ga.context}'.")

    console.print()
    console.print(f"  {ok(f'[bold]{name}[/bold] removed from registry')}")
    console.print(info(f"type     [dim]{removed.type.value}[/dim]"))
    console.print(info(f"endpoint [dim]{removed.endpoint}[/dim]"))
    console.print(info(f"context  [dim]{ga.context}[/dim]"))
    console.print()