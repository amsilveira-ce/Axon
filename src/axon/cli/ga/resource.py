"""cli/ga/resource.py — axon ga resource list|ping|remove"""
from __future__ import annotations

import typer

from axon.cli._print import console, ok, warn, fatal, line, status, step, divider

app = typer.Typer(help="Manage resources in the active Gateway Agent.")


def _get_registry():
    """Lê o registry do GA ativo via ga_paths()."""
    import json
    from axon.config import ga_paths
    p = ga_paths()
    if not p.registry.exists():
        return []
    from axon.types import RegistryFile
    return RegistryFile.model_validate(
        json.loads(p.registry.read_text(encoding="utf-8"))
    ).resources


def _active_context() -> str:
    from axon.config import read_config, _ENV_GA_CONTEXT
    import os
    env = os.environ.get(_ENV_GA_CONTEXT)
    if env:
        return env
    try:
        return read_config().current_gateway
    except FileNotFoundError:
        return "default"


# ── list ──────────────────────────────────────────────────────────────────────

@app.command("list")
def resource_list() -> None:
    """
    List resources registered in the active gateway.

    Shows each resource with its lifecycle status (online, validating,
    drift, offline, failed), endpoint and capability tags. Status
    reflects the last health check — refresh with 'axon ga resource ping'.
    """
    ctx       = _active_context()
    resources = _get_registry()

    console.print()
    console.print(f"  [bold]resources[/bold]  [dim]context: {ctx}[/dim]")
    console.print()

    if not resources:
        console.print(line("[dim]no resources registered[/dim]"))
        console.print(line("[dim]register with: axon add agent <url>[/dim]"))
        console.print()
        return

    for r in resources:
        console.print(f"  {step(f'[bold]{r.name}[/bold]  {status(r.status)}')}")
        console.print(line(f"[dim]id          {r.id}[/dim]"))
        console.print(line(f"[dim]type        {r.type.value}[/dim]"))
        console.print(line(f"[dim]endpoint    {r.endpoint}[/dim]"))
        if r.skills:
            seen: list[str] = []
            for s in r.skills:
                for t in s.tags:
                    if t not in seen:
                        seen.append(t)
            if seen:
                console.print(line(f"[dim]tags        {', '.join(seen)}[/dim]"))
        console.print(divider())

    console.print()
    console.print(line(f"[dim]{len(resources)} resource(s)[/dim]"))
    console.print()


# ── ping ──────────────────────────────────────────────────────────────────────

@app.command("ping")
def resource_ping(
    name_or_id: str | None = typer.Argument(None, help="Resource name or ID. Omit to ping all."),
) -> None:
    """
    Check health of resources in the active gateway.

    For A2A agents this re-fetches the agent card and recomputes the
    HMAC fingerprint: reachable + same fingerprint → online; unreachable
    → offline; reachable but changed → drift (the agent is alive, but
    what it offers no longer matches what was registered — re-register
    to accept the new contract).

    MCP resources are not probed: the GA stores no credentials, so
    monitoring is not applicable by design.

    Status changes are persisted to the registry.
    """
    import json
    from axon.config import ga_paths
    from axon.health import check
    from axon.types import RegistryFile

    ctx = _active_context()
    p   = ga_paths()

    if not p.registry.exists():
        fatal(f"registry not found at {p.registry}")

    registry = RegistryFile.model_validate(
        json.loads(p.registry.read_text(encoding="utf-8"))
    )

    targets = (
        [r for r in registry.resources
         if r.name == name_or_id or r.id == name_or_id]
        if name_or_id else registry.resources
    )

    if not targets:
        fatal(f"resource '{name_or_id}' not found — run 'axon ga resource list'")

    console.print()
    console.print(f"  [bold]ping[/bold]  [dim]context: {ctx}[/dim]")
    console.print()

    updated = False
    for r in targets:
        result = check(r, p)
        label = "drift detected" if result.status.value == "drift" else None
        console.print(f"  {step(f'[bold]{r.name}[/bold]  {status(result.status, label)}')}")
        if result.error:
            console.print(line(f"[red]{result.error}[/red]"))

        # atualiza status no registry se mudou
        if result.status != r.status:
            r.status = result.status
            updated  = True

        console.print(divider())

    if updated:
        p.registry.write_text(
            registry.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )

    console.print()


# ── remove ────────────────────────────────────────────────────────────────────

@app.command("remove")
def resource_remove(
    name_or_id: str = typer.Argument(..., help="Resource name or ID"),
) -> None:
    """
    Remove a resource from the active gateway registry.

    The resource stops being offered to Principal Agents immediately.
    The admission token it consumed is not restored — mint a new one
    to re-register.
    """
    import json
    from axon.config import ga_paths
    from axon.types import RegistryFile

    ctx = _active_context()
    p   = ga_paths()

    if not p.registry.exists():
        fatal(f"registry not found at {p.registry}")

    registry = RegistryFile.model_validate(
        json.loads(p.registry.read_text(encoding="utf-8"))
    )

    target = next(
        (r for r in registry.resources
         if r.name == name_or_id or r.id == name_or_id),
        None,
    )

    if target is None:
        fatal(f"resource '{name_or_id}' not found in context '{ctx}'")

    registry.resources = [r for r in registry.resources if r.id != target.id]
    p.registry.write_text(
        registry.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )

    console.print()
    console.print(ok(f"[bold]{target.name}[/bold] removed from [dim]{ctx}[/dim]"))
    console.print(line(f"[dim]{target.id}[/dim]"))
    console.print()