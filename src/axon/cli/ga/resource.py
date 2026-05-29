"""cli/ga/resource.py — axon ga resource list|ping|remove"""
from __future__ import annotations

import typer

from axon.cli._print import console, ok, warn, fatal, info, step, divider

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
    """List resources registered in the active gateway."""
    ctx       = _active_context()
    resources = _get_registry()

    console.print()
    console.print(f"  [bold]RESOURCES[/bold]  [dim]context: {ctx}[/dim]")
    console.print()

    if not resources:
        console.print(info("[dim]no resources registered[/dim]"))
        console.print(info("[dim]register with: axon add agent <url>[/dim]"))
        console.print()
        return

    for r in resources:
        status_color = {
            "online":     "[green]online[/green]",
            "offline":    "[red]offline[/red]",
            "validating": "[yellow]drift[/yellow]",
            "failed":     "[red]failed[/red]",
        }.get(r.status.value, f"[dim]{r.status.value}[/dim]")

        console.print(f"  {step(f'[bold]{r.name}[/bold]  {status_color}')}")
        console.print(info(f"[dim]id          {r.id}[/dim]"))
        console.print(info(f"[dim]type        {r.type.value}[/dim]"))
        console.print(info(f"[dim]endpoint    {r.endpoint}[/dim]"))
        if r.skills:
            tags = ", ".join(t for s in r.skills for t in s.tags)
            if tags:
                console.print(info(f"[dim]tags        {tags}[/dim]"))
        console.print(divider())

    console.print()
    console.print(info(f"[dim]{len(resources)} resource(s)[/dim]"))
    console.print()


# ── ping ──────────────────────────────────────────────────────────────────────

@app.command("ping")
def resource_ping(
    name_or_id: str | None = typer.Argument(None, help="Resource name or ID. Omit to ping all."),
) -> None:
    """Check health of resources in the active gateway."""
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
    console.print(f"  [bold]PING[/bold]  [dim]context: {ctx}[/dim]")
    console.print()

    updated = False
    for r in targets:
        result = check(r)
        status_color = {
            "online":     "[green]online[/green]",
            "offline":    "[red]offline[/red]",
            "validating": "[yellow]drift detected[/yellow]",
        }.get(result.status.value, result.status.value)

        console.print(f"  {step(f'[bold]{r.name}[/bold]  {status_color}')}")
        if result.error:
            console.print(info(f"[red]{result.error}[/red]"))

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
    """Remove a resource from the active gateway registry."""
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
    console.print(info(f"[dim]{target.id}[/dim]"))
    console.print()