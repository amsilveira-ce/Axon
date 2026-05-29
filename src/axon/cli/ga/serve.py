"""cli/ga/serve.py"""
from __future__ import annotations

import typer

from axon.cli._print import console, ok, fatal, info, step, divider

app = typer.Typer(help="Start a Gateway Agent instance.")


@app.callback(invoke_without_command=True)
def serve(
    context: str | None = typer.Option(None, "--context", "-c", help="GA context to serve (default: current_gateway)"),
    host:    str        = typer.Option("0.0.0.0", "--host", help="Host to bind"),
    port:    int | None = typer.Option(None, "--port", "-p", help="Port override"),
    reload:  bool       = typer.Option(False, "--reload", help="Auto-reload on code changes (dev mode)"),
) -> None:
    """Start the Gateway Agent HTTP server."""
    import os
    import uvicorn
    from axon.config import _ENV_GA_CONTEXT
    from axon.ga.config import GAConfig

    # resolve o contexto antes de qualquer coisa
    ga  = GAConfig.resolve(context=context)
    ctx = ga.context

    # injeta no ambiente do processo atual — subprocessos de reload herdam
    os.environ[_ENV_GA_CONTEXT] = ctx

    effective_port = port or ga.port

    console.print()
    console.print(f"  {step(f'[bold]Axon[/bold] Gateway Agent [cyan]{ctx}[/cyan]')}")
    console.print(divider())
    console.print(info(f"context    [cyan]{ctx}[/cyan]"))
    console.print(info(f"name       [dim]{ga.name}[/dim]"))
    console.print(info(f"host       [cyan]{host}:{effective_port}[/cyan]"))
    console.print(info(f"card       [dim]http://{host}:{effective_port}/ga/card[/dim]"))
    console.print(info(f"docs       [dim]http://{host}:{effective_port}/docs[/dim]"))
    console.print(info(f"registry   [dim]{ga.paths.registry}[/dim]"))
    console.print(info(f"retrieval  [dim]{ga.instance.retrieval_strategy}[/dim]", ))
    if ga.instance.retrieval_strategy == "embedding" and ga.instance.embedding_model:
        console.print(info(f"embed model [dim]{ga.instance.embedding_model}[/dim]"))
    if reload:
        console.print(info("[yellow]reload    on — AXON_GA_CONTEXT inherited by workers[/yellow]"))
    console.print()
    console.print(ok("Gateway Agent starting..."))
    console.print()

    uvicorn.run(
        "axon.ga.server:app",
        host=host,
        port=effective_port,
        reload=reload,
        log_level="info",
    )