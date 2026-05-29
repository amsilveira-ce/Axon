from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

import typer

from axon.cli._print import console, ok, warn, fatal, info, step, divider

app = typer.Typer(help="Manage Gateway Agent connections.")

GATEWAY_CARD_PATH = "/ga/card"
TIMEOUT           = 8.0


# ── helpers ───────────────────────────────────────────────────────────────────

def _fetch_gateway_card(url: str) -> dict:
    import httpx
    card_url = url.rstrip("/") + GATEWAY_CARD_PATH
    try:
        resp = httpx.get(card_url, timeout=TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        raise RuntimeError(f"connection refused — is the Gateway Agent running at {url}?")
    except httpx.TimeoutException:
        raise RuntimeError(f"timeout after {TIMEOUT}s — Gateway Agent did not respond at {url}")
    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"HTTP {e.response.status_code} from {card_url}\n"
            f"This doesn't look like an Axon Gateway Agent."
        )
    except Exception as e:
        raise RuntimeError(f"unexpected error fetching gateway card: {e}")


def _parse_card(raw: dict):
    from axon.types import GatewayCard
    try:
        card = GatewayCard.model_validate(raw)
        return card, card.axon
    except Exception as e:
        raise RuntimeError(f"invalid gateway card schema: {e}")


# ── add ───────────────────────────────────────────────────────────────────────

@app.command("add")
def gateway_add(
    url: str = typer.Argument(..., help="Gateway Agent URL (e.g. http://ga.empresa.com/)"),
) -> None:
    """Connect the PA to a Gateway Agent."""
    from axon.config import read_config, patch_config, ConnectedGateway

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        fatal(f"Invalid URL: '{url}'. Expected format: http://host:port/")

    try:
        cfg = read_config()
    except FileNotFoundError:
        fatal('axon.config.json not found. Run "axon init" first.')

    url_clean = url.rstrip("/")

    if any(g.url.rstrip("/") == url_clean for g in cfg.pa.gateways):
        console.print()
        console.print(warn(f"gateway [bold]{url}[/bold] already connected"))
        console.print()
        raise typer.Exit(1)

    console.print()
    console.print(f"  {step(f'connecting to [cyan]{url}[/cyan]')}")
    console.print(divider())

    try:
        raw = _fetch_gateway_card(url)
    except RuntimeError as e:
        fatal(str(e))

    try:
        card, axon_meta = _parse_card(raw)
    except RuntimeError as e:
        fatal(str(e))

    console.print(f"  {step(f'gateway card  [bold]{card.name}[/bold] v{card.version}')}")
    console.print(divider())

    # avaliar extensão Axon
    if axon_meta is None:
        console.print()
        console.print(warn("[bold]Axon extension not found in gateway card[/bold]"))
        console.print(info("[dim]trust_level will be set to 'unknown'[/dim]"))
        console.print()
        if not typer.confirm("  Connect anyway?", default=False):
            console.print()
            console.print(info("[dim]Aborted.[/dim]"))
            console.print()
            raise typer.Exit(0)
        trust_level  = "unknown"
        organization = None
    else:
        trust_level  = axon_meta.trust_level
        organization = axon_meta.organization
        org_display  = organization or "—"
        console.print(
            f"  {step(f'axon extension  '
                      f'trust=[cyan]{trust_level}[/cyan]  '
                      f'resources=[cyan]{axon_meta.resources_count}[/cyan]  '
                      f'org=[dim]{org_display}[/dim]')}"
        )
        console.print(divider())

        if trust_level == "unknown":
            console.print()
            console.print(warn("[bold]trust_level is 'unknown'[/bold]"))
            console.print(info("[dim]Only connect to gateways you control or trust explicitly.[/dim]"))
            console.print()
            if not typer.confirm("  Connect anyway?", default=False):
                console.print()
                console.print(info("[dim]Aborted.[/dim]"))
                console.print()
                raise typer.Exit(0)

    # salva ConnectedGateway com card completo
    entry = ConnectedGateway(
        url=url_clean,
        name=card.name,
        version=card.version,
        trust_level=trust_level,
        organization=organization,
        last_seen=datetime.now(timezone.utc),
    )

    def _add(c):
        return c.model_copy(update={
            "pa": c.pa.model_copy(update={
                "gateways": c.pa.gateways + [entry]
            })
        })

    patch_config(_add)

    trust_color = {
        "local":   "[green]local[/green]",
        "vendor":  "[cyan]vendor[/cyan]",
        "unknown": "[yellow]unknown[/yellow]",
    }.get(trust_level, f"[dim]{trust_level}[/dim]")

    console.print()
    console.print(ok(f"[bold]{card.name}[/bold] connected"))
    console.print()
    console.print(info(f"url          [dim]{url_clean}[/dim]"))
    console.print(info(f"version      [dim]{card.version}[/dim]"))
    console.print(info(f"trust        {trust_color}"))
    if organization:
        console.print(info(f"org          [dim]{organization}[/dim]"))
    console.print()
    console.print(info("[dim]NOTE: restart the PA for the new gateway to be used[/dim]"))
    console.print()


# ── list ──────────────────────────────────────────────────────────────────────

@app.command("list")
def gateway_list() -> None:
    """List connected Gateway Agents with live status."""
    from axon.config import read_config, patch_config

    try:
        cfg = read_config()
    except FileNotFoundError:
        fatal('axon.config.json not found. Run "axon init" first.')

    gateways = cfg.pa.gateways
    console.print()

    if not gateways:
        console.print(info("[dim]no gateways connected[/dim]"))
        console.print(info("[dim]add with: axon pa gateway add <url>[/dim]"))
        console.print()
        return

    now     = datetime.now(timezone.utc)
    updated = list(gateways)
    online  = 0

    for i, g in enumerate(gateways):
        # ping ao vivo
        try:
            raw        = _fetch_gateway_card(g.url)
            card, meta = _parse_card(raw)
            resources  = meta.resources_count if meta else 0
            status     = "[green]✓[/green]"
            status_txt = "online"
            updated[i] = g.model_copy(update={"last_seen": now})
            online += 1
        except RuntimeError:
            status     = "[red]✗[/red]"
            status_txt = "offline"
            resources  = None

        # linha compacta: ✓  GA Corporativo    http://...   online
        name_col = f"[bold]{g.name}[/bold]"
        url_col  = f"[dim]{g.url}[/dim]"
        stat_col = f"[green]online[/green]" if status_txt == "online" else "[red]offline[/red]"
        res_col  = f"[dim]{resources} resources[/dim]" if resources is not None else "[dim]—[/dim]"

        console.print(f"  {status}  {name_col:<30} {url_col:<45} {stat_col}  {res_col}")

    console.print()
    console.print(info(f"[dim]{online}/{len(gateways)} online[/dim]"))
    console.print()

    # persiste last_seen atualizado
    patch_config(lambda c: c.model_copy(update={
        "pa": c.pa.model_copy(update={"gateways": updated})
    }))


# ── remove ────────────────────────────────────────────────────────────────────

@app.command("remove")
def gateway_remove(
    url: str = typer.Argument(..., help="Gateway URL to remove"),
) -> None:
    """Disconnect a Gateway Agent."""
    from axon.config import read_config, patch_config

    try:
        cfg = read_config()
    except FileNotFoundError:
        fatal('axon.config.json not found. Run "axon init" first.')

    url_clean = url.rstrip("/")
    target    = next((g for g in cfg.pa.gateways if g.url.rstrip("/") == url_clean), None)

    if not target:
        fatal(f"gateway '{url}' not found — run 'axon pa gateway list'")

    def _remove(c):
        return c.model_copy(update={
            "pa": c.pa.model_copy(update={
                "gateways": [g for g in c.pa.gateways if g.url.rstrip("/") != url_clean]
            })
        })

    patch_config(_remove)

    console.print()
    console.print(ok(f"[bold]{target.name}[/bold] disconnected"))
    console.print(info(f"[dim]{url_clean}[/dim]"))
    console.print()


# ── ping ──────────────────────────────────────────────────────────────────────

@app.command("ping")
def gateway_ping(
    url: str | None = typer.Argument(None, help="Gateway URL to ping. Omit to ping all."),
) -> None:
    """Check if Gateway Agents are reachable and update last_seen."""
    from axon.config import read_config, patch_config

    try:
        cfg = read_config()
    except FileNotFoundError:
        fatal('axon.config.json not found. Run "axon init" first.')

    targets = (
        [g for g in cfg.pa.gateways if g.url.rstrip("/") == url.rstrip("/")]
        if url else cfg.pa.gateways
    )

    if not targets:
        console.print()
        console.print(info("[dim]no gateways connected — add with: axon pa gateway add <url>[/dim]"))
        console.print()
        return

    now      = datetime.now(timezone.utc)
    updated  = list(cfg.pa.gateways)
    console.print()

    for target in targets:
        console.print(f"  {step(f'pinging [cyan]{target.url}[/cyan]')}")
        try:
            raw        = _fetch_gateway_card(target.url)
            card, meta = _parse_card(raw)
            trust      = meta.trust_level if meta else "unknown"
            count      = meta.resources_count if meta else 0

            # atualiza last_seen
            for i, g in enumerate(updated):
                if g.url == target.url:
                    updated[i] = g.model_copy(update={"last_seen": now})
                    break

            console.print(info(
                f"[green]online[/green]  [dim]{card.name} v{card.version} · "
                f"trust={trust} · {count} resources[/dim]"
            ))
        except RuntimeError as e:
            console.print(info(f"[red]offline[/red]  [dim]{e}[/dim]"))

        console.print(divider())

    # persiste last_seen atualizado
    patch_config(lambda c: c.model_copy(update={
        "pa": c.pa.model_copy(update={"gateways": updated})
    }))

    console.print()