"""cli/ga/config.py — axon ga config"""
from __future__ import annotations

import json
from typing import Optional

import typer

from axon.cli._print import console, ok, warn, fatal, line, step, divider

app = typer.Typer()


@app.callback(invoke_without_command=True)
def config(
    ctx: typer.Context,
    # ── identidade ────────────────────────────────────────────────────
    name:         Optional[str] = typer.Option(None, "--name",         help="Gateway display name"),
    description:  Optional[str] = typer.Option(None, "--description",  help="Gateway description"),
    organization: Optional[str] = typer.Option(None, "--organization", help="Organization that operates this gateway"),
    trust_level:  Optional[str] = typer.Option(None, "--trust-level",  help="Trust level: local | vendor | unknown"),
    # ── retrieval ─────────────────────────────────────────────────────
    retrieval:    Optional[str] = typer.Option(None, "--retrieval",       help="Retrieval strategy: keyword | embedding"),
    embed_model:  Optional[str] = typer.Option(None, "--embedding-model", help="Embedding model (e.g. nomic-embed-text)"),
    embed_host:   Optional[str] = typer.Option(None, "--embedding-host",  help="Ollama host for embeddings"),
    threshold:    Optional[float] = typer.Option(None, "--threshold",     help="Similarity threshold (0.0–1.0)"),
    top_k:        Optional[int]   = typer.Option(None, "--top-k",         help="Max results returned by search"),
) -> None:
    """
    Show or edit the active Gateway Agent configuration.

    Without arguments: shows current ga.json.
    With flags: edits the specified fields — takes effect immediately
    (GET /ga/card reads ga.json on every request, no restart needed).
    """
    from axon.ga.config import GAConfig

    ga = GAConfig.resolve()
    p  = ga.paths

    _any = any([
        name, description, organization, trust_level,
        retrieval, embed_model, embed_host,
        threshold is not None, top_k is not None,
    ])

    if not _any:
        _show(ga)
        return

    # ── validações ────────────────────────────────────────────────────
    if trust_level and trust_level not in ("local", "vendor", "unknown"):
        fatal(f"invalid trust-level '{trust_level}'. valid: local, vendor, unknown")

    if retrieval and retrieval not in ("keyword", "embedding"):
        fatal(f"invalid retrieval '{retrieval}'. valid: keyword, embedding")

    # ── lê ga.json atual ──────────────────────────────────────────────
    if p.ga_config.exists():
        current = json.loads(p.ga_config.read_text(encoding="utf-8"))
    else:
        current = {
            "name":               ga.name,
            "description":        "",
            "organization":       None,
            "trust_level":        "local",
            "port":               ga.port,
            "data_dir":           ga.data_dir,
            "version":            "0.1.0",
            "retrieval_strategy": ga.instance.retrieval_strategy,
            "embedding_model":    ga.instance.embedding_model,
            "embedding_host":     ga.instance.embedding_host,
            "embedding_threshold": ga.instance.embedding_threshold,
            "embedding_top_k":    ga.instance.embedding_top_k,
        }

    # ── aplica mudanças ───────────────────────────────────────────────
    changes: list[str] = []

    if name:
        current["name"] = name
        changes.append(f"name = {name}")

    if description:
        current["description"] = description
        changes.append(f"description = {description}")

    if organization:
        current["organization"] = organization
        changes.append(f"organization = {organization}")

    if trust_level:
        current["trust_level"] = trust_level
        changes.append(f"trust_level = {trust_level}")

    if retrieval:
        current["retrieval_strategy"] = retrieval
        changes.append(f"retrieval_strategy = {retrieval}")

    if embed_model:
        current["embedding_model"] = embed_model
        changes.append(f"embedding_model = {embed_model}")

    if embed_host:
        current["embedding_host"] = embed_host
        changes.append(f"embedding_host = {embed_host}")

    if threshold is not None:
        current["embedding_threshold"] = threshold
        changes.append(f"embedding_threshold = {threshold}")

    if top_k is not None:
        current["embedding_top_k"] = top_k
        changes.append(f"embedding_top_k = {top_k}")

    # ── persiste ──────────────────────────────────────────────────────
    p.ga_config.parent.mkdir(parents=True, exist_ok=True)
    p.ga_config.write_text(
        json.dumps(current, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    # ── output ────────────────────────────────────────────────────────
    console.print()
    console.print(f"  [dim]context: {ga.context}[/dim]")
    console.print()
    for change in changes:
        console.print(f"  {ok(f'[dim]{change}[/dim]')}")
    console.print()
    console.print(line("[dim]GET /ga/card reflects changes immediately — no restart needed[/dim]"))
    console.print()


def _show(ga: "GAConfig") -> None:  # type: ignore[name-defined]
    """Mostra o conteúdo atual do ga.json."""
    p = ga.paths

    if p.ga_config.exists():
        cfg = json.loads(p.ga_config.read_text(encoding="utf-8"))
    else:
        cfg = {}

    console.print()
    console.print(f"  [bold]GA config[/bold]  [dim]context: {ga.context}[/dim]")
    console.print(line(f"[dim]file: {p.ga_config}[/dim]"))
    console.print()

    console.print("  [dim]─── identity ──────────────────────────────────[/dim]")
    console.print(line(f"name          [cyan]{cfg.get('name', ga.name)}[/cyan]"))
    console.print(line(f"description   [dim]{cfg.get('description') or '(not set)'}[/dim]"))
    console.print(line(f"organization  [dim]{cfg.get('organization') or '(not set)'}[/dim]"))

    trust = cfg.get("trust_level", "local")
    trust_color = {
        "local":   "[green]local[/green]",
        "vendor":  "[cyan]vendor[/cyan]",
        "unknown": "[yellow]unknown[/yellow]",
    }.get(trust, trust)
    console.print(line(f"trust_level   {trust_color}"))
    console.print()

    console.print("  [dim]─── server ────────────────────────────────────[/dim]")
    console.print(line(f"port      [cyan]{cfg.get('port', ga.port)}[/cyan]"))
    console.print(line(f"data_dir  [dim]{cfg.get('data_dir', ga.data_dir)}[/dim]"))
    console.print(line(f"version   [dim]{cfg.get('version', '0.1.0')}[/dim]"))
    console.print()

    console.print("  [dim]─── retrieval ─────────────────────────────────[/dim]")
    console.print(line(f"strategy  [cyan]{cfg.get('retrieval_strategy', ga.instance.retrieval_strategy)}[/cyan]"))
    if cfg.get("retrieval_strategy") == "embedding" or ga.instance.retrieval_strategy == "embedding":
        console.print(line(f"model     [cyan]{cfg.get('embedding_model') or ga.instance.embedding_model or '(not set)'}[/cyan]"))
        console.print(line(f"host      [dim]{cfg.get('embedding_host', ga.instance.embedding_host)}[/dim]"))
        console.print(line(f"threshold [dim]{cfg.get('embedding_threshold', ga.instance.embedding_threshold)}[/dim]"))
        console.print(line(f"top_k     [dim]{cfg.get('embedding_top_k', ga.instance.embedding_top_k)}[/dim]"))
    console.print()

    console.print(line("[dim]edit with: axon ga config --name '...' --organization '...'[/dim]"))
    console.print()