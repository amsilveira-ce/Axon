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


# ── mcp ─────────────────────────────────────────────────────────────────────

@app.command("mcp")
def add_mcp(
    name:        str        = typer.Argument(..., help="Resource name (e.g. tavily)"),
    http:        str | None = typer.Option(None, "--http",  help="MCP Streamable HTTP endpoint URL"),
    sse:         str | None = typer.Option(None, "--sse",   help="MCP SSE endpoint URL"),
    stdio:       str | None = typer.Option(None, "--stdio", help='MCP stdio command, ex: "npx -y resend-mcp"'),
    auth:        str        = typer.Option("none", "--auth",     help="Auth scheme: none|bearer|api_key|oauth"),
    location:    str        = typer.Option("header", "--location", help="api_key location: header|query|env"),
    header:      str | None = typer.Option(None, "--header",  help="Header name (location=header)"),
    param:       str | None = typer.Option(None, "--param",   help="Query param name (location=query)"),
    env_var:     str | None = typer.Option(None, "--env-var", help="Env var que guarda o segredo"),
    scope:       list[str]  = typer.Option(None, "--scope",   help="OAuth scope (repetível)"),
    tag:         list[str]  = typer.Option(None, "--tag",     help="Capability tag (repetível)"),
    token:       str | None = typer.Option(None, "--token",   help="Token de admissão Axon (axon_tk_...) — opcional"),
    description: str        = typer.Option("", "--description", help="Descrição do recurso"),
) -> None:
    """
    Register an MCP resource with the active Gateway.

    Validação = conexão viva: conecta de verdade via MCPClient e lista as tools
    (prova que o recurso existe, está no ar e o que faz). Diferente do A2A, o
    recurso não carrega axon_token — a autorização é apresentada pelo operador
    aqui (--token, opcional): verificado e consumido no registro.

    Transporte (exatamente um): --http | --sse | --stdio.
    """
    import shlex
    from axon.ga.config import GAConfig
    from axon.ga.registry import add_resource
    from axon.ga.tokens import verify_local, mark_used, TokenVerificationError
    from axon.types import (
        AuthConfig, AuthScheme, AuthLocation, A2ASkill,
        ProtocolBinding, Resource, ResourceManifest, ResourceStatus, ResourceType,
    )
    from axon.validator import validate_mcp

    # 1. transporte — exatamente um
    chosen = [(k, v) for k, v in (("http", http), ("sse", sse), ("stdio", stdio)) if v]
    if len(chosen) != 1:
        fatal('escolha exatamente um transporte: --http URL | --sse URL | --stdio "cmd"')
    kind, value = chosen[0]
    if kind == "http":
        binding, endpoint, command = ProtocolBinding.MCP_HTTP, value, None
    elif kind == "sse":
        binding, endpoint, command = ProtocolBinding.MCP_SSE, value, None
    else:
        binding, endpoint, command = ProtocolBinding.MCP_STDIO, None, shlex.split(value)

    # 2. auth
    try:
        scheme = AuthScheme(auth)
        loc    = AuthLocation(location)
    except ValueError as e:
        fatal(f"valor inválido para --auth/--location: {e}")
    auth_cfg = AuthConfig(
        scheme=scheme, location=loc,
        header=header, param=param, env_var=env_var,
        scopes=scope or [],
    )

    # 3. manifest de validação
    manifest = ResourceManifest(
        resource_id=f"res-{secrets.token_hex(3)}",
        name=name, type=ResourceType.mcp, protocol_binding=binding,
        description=description, capability_tags=tag or [],
        callable_by="pa_direct", endpoint=endpoint, command=command,
        auth=auth_cfg,
    )

    ga = GAConfig.resolve()
    console.print()
    console.print(info(f"[dim]context: {ga.context} ({ga.name})[/dim]"))
    console.print(f"\n  {step(f'Connecting to [cyan]{name}[/cyan] ([dim]{binding.value}[/dim])')}")
    console.print(divider())

    # 4. validação = conexão viva + tools
    result = validate_mcp(manifest)
    if not result.ok:
        console.print("  [red]■[/red] connect failed\n")
        for line in (result.error or "").split("\n"):
            console.print(f"  [dim]{line}[/dim]")
        console.print()
        raise typer.Exit(1)

    console.print(f"  {step(f'connected        [green]{len(result.tools)} tools[/green]')}")
    console.print(divider())
    console.print(f"  {step(f'fingerprint      [dim]{result.fingerprint}[/dim]')}")
    console.print(divider())

    # 5. token de admissão (opcional)
    if token:
        try:
            verify_local(token, ga.paths)
        except TokenVerificationError as e:
            console.print("  [red]■[/red] admission token rejected\n")
            console.print(f"  [dim]{e}[/dim]\n")
            raise typer.Exit(1)
        console.print(f"  {step('admission token  [green]verified[/green]')}")
        console.print(divider())

    # 6. persiste — skills carregam a descrição REAL de cada tool (matching)
    skills = [
        A2ASkill(
            id=s["name"],
            name=s["name"],
            description=s["description"] or s["name"],
            tags=tag or [],
        )
        for s in result.tool_specs
    ]

    # descrição do recurso p/ matching: usa --description, ou sintetiza uma boa
    # a partir do nome, tools e tags (alimenta keyword + embedding do retrieval).
    if not description:
        caps = ", ".join(tag) if tag else "—"
        description = (
            f"{name}: MCP resource ({binding.value}) providing "
            f"{len(result.tools)} tools ({', '.join(result.tools)}). "
            f"Capabilities: {caps}."
        )

    resource = Resource(
        id=manifest.resource_id, type=ResourceType.mcp, protocol_binding=binding,
        name=name, endpoint=endpoint, command=command, description=description,
        skills=skills, fingerprint=result.fingerprint or "",
        auth=auth_cfg, token_ref=token, status=ResourceStatus.online,
    )
    try:
        add_resource(resource, ga.paths)
    except Exception as e:
        fatal(f"Could not write to registry: {e}")

    if token:
        try:
            mark_used(token, resource.id, ga.paths)
        except Exception:
            console.print(warn("could not update token status"))

    auth_display = scheme.value + (f"/{loc.value}" if scheme == AuthScheme.api_key else "")
    tools_preview = ", ".join(result.tools[:8]) + (" …" if len(result.tools) > 8 else "")

    console.print()
    console.print(f"  {ok(f'[bold]{name}[/bold] registered')}\n")
    console.print(info(f"id          [dim]{resource.id}[/dim]"))
    console.print(info(f"type        [dim]mcp ({binding.value})[/dim]"))
    console.print(info(f"auth        [dim]{auth_display}[/dim]"))
    console.print(info(f"tools       [dim]{tools_preview or '—'}[/dim]"))
    if endpoint:
        console.print(info(f"endpoint    [dim]{endpoint}[/dim]"))
    if command:
        console.print(info(f"command     [dim]{' '.join(command)}[/dim]"))
    console.print(info(f"token_ref   [dim]{token or '—'}[/dim]"))
    console.print(info(f"context     [dim]{ga.context}[/dim]"))
    console.print(info(f"saved to    [dim]{ga.paths.registry}[/dim]"))
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