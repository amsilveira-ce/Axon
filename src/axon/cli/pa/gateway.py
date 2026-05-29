from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

import typer

from axon.cli._print import console, ok, warn, fatal, info, step, divider, hint

app = typer.Typer(help="Manage Gateway Agent connections.")

GATEWAY_CARD_PATH = "/ga/card"
PA_CONNECT_PATH   = "/pa/connect"
RESOURCES_PATH    = "/ga/resources"
TIMEOUT           = 8.0

_FILTERS = ("eligible", "auth-missing", "paid")


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


# ── connect + resources helpers ─────────────────────────────────────────────────

def _build_pacard(cfg) -> dict:
    """PACard do PA a partir do config — identidade enviada ao GA no connect."""
    return {"name": "Axon Principal Agent", "version": cfg.version, "organization": None}


def _post_connect(url: str, card: dict) -> dict:
    """POST /pa/connect — anuncia o PA ao GA (passo 2)."""
    import httpx
    connect_url = url.rstrip("/") + PA_CONNECT_PATH
    resp = httpx.post(connect_url, json=card, timeout=TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


def _fetch_resources(url: str) -> list[dict]:
    """GET /ga/resources — lista os recursos do GA (passo 3)."""
    import httpx
    res_url = url.rstrip("/") + RESOURCES_PATH
    resp = httpx.get(res_url, timeout=TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    return resp.json().get("resources", [])


def _item_to_manifest(item: dict):
    """Reconstrói um ResourceManifest a partir de um item do /ga/resources."""
    from axon.types import (
        AuthConfig, ProtocolBinding, ResourceManifest, ResourcePolicy, ResourceType,
    )
    tags = sorted({t for s in item.get("skills", []) for t in s.get("tags", [])})
    return ResourceManifest(
        resource_id=item["id"], name=item["name"], type=ResourceType(item["type"]),
        protocol_binding=ProtocolBinding(item["protocol_binding"]),
        description=item.get("description", ""), capability_tags=tags,
        callable_by="pa_direct",
        endpoint=item.get("endpoint"), command=item.get("command"),
        auth=AuthConfig.model_validate(item.get("auth") or {}),
        policy=ResourcePolicy.model_validate(item.get("policy") or {}),
    )


def _eval_items(items: list[dict], policy):
    """Avalia cada item pela política do operador. Pula itens não conversíveis."""
    from axon.pa.policy import evaluate
    rows = []
    for item in items:
        try:
            manifest = _item_to_manifest(item)
        except Exception:
            continue
        rows.append(evaluate(manifest, policy))
    return rows


def _matches_filter(elig, filter_: str | None) -> bool:
    if filter_ is None:
        return True
    if filter_ == "eligible":
        return elig.eligible
    if filter_ == "auth-missing":
        return not elig.auth_ready
    if filter_ == "paid":
        return elig.is_paid
    return True


def _render_eligibility(rows, *, filter_: str | None = None) -> int:
    """Renderiza a tabela de elegibilidade. Retorna quantas linhas mostrou."""
    from rich.table import Table

    shown = [r for r in rows if _matches_filter(r, filter_)]
    if not shown:
        console.print(info("[dim](nenhum recurso para este filtro)[/dim]"))
        return 0

    table = Table(show_header=True, header_style="dim", box=None, pad_edge=False, padding=(0, 3, 0, 0))
    table.add_column("resource")
    table.add_column("pricing")
    table.add_column("auth")
    table.add_column("status")

    for r in shown:
        pricing = (
            "[yellow]pago[/yellow]"
            + (f" [dim]${r.cost_per_call:.4f}[/dim]" if r.cost_per_call is not None else "")
        ) if r.is_paid else "[dim]gratuito[/dim]"

        if r.auth_scheme == "none":
            auth_col = "[dim]no-auth[/dim]"
        else:
            mark     = "[green]✓[/green]" if r.auth_ready else "[red]✗[/red]"
            auth_col = f"{r.auth_scheme} {mark}"

        if r.eligible:
            status = "[green]✓ pronto[/green]"
            # política permite, mas o token falta → avisa (vai falhar na execução)
            if not r.auth_ready and r.auth_env_var:
                status += f" [dim](set {r.auth_env_var})[/dim]"
        else:
            status = "[red]✗[/red] " + " · ".join(r.reasons)
        table.add_row(f"[bold]{r.resource_name}[/bold]", pricing, auth_col, status)

    console.print(table)
    return len(shown)


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

    # passo 2 — anuncia o PA ao GA (registra a conexão)
    cfg2 = read_config()
    try:
        ack = _post_connect(url_clean, _build_pacard(cfg2))
        console.print(info(
            f"connection   [green]registered[/green] "
            f"[dim]({ack.get('resources_count', '?')} resources)[/dim]"
        ))
    except Exception as e:
        console.print(info(f"connection   [yellow]skipped[/yellow] [dim]({e})[/dim]"))

    # passo 3 — lista recursos do GA + elegibilidade pela política atual
    try:
        rows = _eval_items(_fetch_resources(url_clean), cfg2.pa.resource_policy)
    except Exception as e:
        rows = None
        console.print(info(f"resources    [yellow]unavailable[/yellow] [dim]({e})[/dim]"))

    if rows is not None:
        console.print()
        console.print("  [bold]RECURSOS[/bold]")
        console.print()
        _render_eligibility(rows)
        eligible = sum(1 for r in rows if r.eligible)
        console.print()
        console.print(info(
            f"[dim]{eligible}/{len(rows)} prontos — configure os tokens ausentes e revise política[/dim]"
        ))

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


# ── resources ───────────────────────────────────────────────────────────────────

@app.command("resources")
def gateway_resources(
    filter_: str | None = typer.Option(
        None, "--filter", help="eligible | auth-missing | paid"
    ),
    context: str | None = typer.Option(
        None, "--context", help="Filtra por um GA específico (nome ou url)"
    ),
) -> None:
    """
    List resources across connected Gateway Agents with policy eligibility.

    O status (✓ pronto / ✗ motivo) usa a mesma avaliação que o Resolver aplica
    ao escolher recursos — o que aparece como 'pronto' é o que o PA usaria.
    """
    from axon.config import read_config

    try:
        cfg = read_config()
    except FileNotFoundError:
        fatal('axon.config.json not found. Run "axon init" first.')

    if filter_ is not None and filter_ not in _FILTERS:
        fatal(
            f"invalid --filter '{filter_}'",
            hint("valid values", ", ".join(_FILTERS)),
        )

    gateways = cfg.pa.gateways
    if context:
        ctx = context.rstrip("/")
        gateways = [
            g for g in gateways
            if g.name == context or g.url.rstrip("/") == ctx or g.url.rstrip("/").endswith(ctx)
        ]

    console.print()
    if not gateways:
        console.print(info("[dim]no gateways connected — add with: axon pa gateway add <url>[/dim]"))
        console.print()
        return

    policy        = cfg.pa.resource_policy
    total_eligible = 0
    total_count    = 0

    for g in gateways:
        console.print(f"  [bold]{g.name}[/bold] [dim]{g.url}[/dim]")
        console.print(divider())
        try:
            rows = _eval_items(_fetch_resources(g.url), policy)
        except Exception as e:
            console.print(info(f"[red]offline[/red] [dim]{e}[/dim]"))
            console.print()
            continue

        _render_eligibility(rows, filter_=filter_)
        eligible = sum(1 for r in rows if r.eligible)
        total_eligible += eligible
        total_count    += len(rows)
        console.print()
        console.print(info(f"[dim]{eligible}/{len(rows)} prontos[/dim]"))
        console.print()

    if len(gateways) > 1:
        console.print(info(f"[dim]total: {total_eligible}/{total_count} prontos em {len(gateways)} gateways[/dim]"))
        console.print()