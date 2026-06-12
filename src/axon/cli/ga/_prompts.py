"""
cli/ga/_prompts.py — Prompts interativos reutilizáveis para o GA.
"""
from __future__ import annotations

import typer

from axon.cli._print import console, ok, warn, line


def pick_retrieval_strategy(ollama_host: str = "http://localhost:11434") -> tuple[str, str | None]:
    """
    Prompt interativo para escolha da estratégia de retrieval.
    Usa setas via questionary se disponível, fallback para prompt de texto.

    Returns:
        (strategy, embedding_model) — ex: ("embedding", "nomic-embed-text")
    """
    try:
        import questionary
        return _pick_with_questionary(ollama_host)
    except ImportError:
        return _pick_with_typer(ollama_host)


def _pick_with_questionary(ollama_host: str) -> tuple[str, str | None]:
    import questionary

    _style = questionary.Style([
        ("selected",    "fg:cyan bold"),
        ("pointer",     "fg:cyan bold"),
        ("highlighted", "fg:cyan"),
        ("question",    "fg:white bold"),
    ])

    console.print()
    console.print("  [dim]─── retrieval strategy ──────────────────────────[/dim]")
    console.print()

    strategy = questionary.select(
        "Retrieval strategy:",
        choices=[
            questionary.Choice(
                title="keyword  — fast, no dependencies, good for small registries",
                value="keyword",
            ),
            questionary.Choice(
                title="embedding — semantic search via Ollama, better relevance",
                value="embedding",
            ),
        ],
        style=_style,
    ).ask()

    if strategy != "embedding":
        return "keyword", None

    # detectar modelos disponíveis
    console.print()
    console.print(line("[dim]scanning Ollama for embedding models...[/dim]"))

    from axon.ga.ollama_discover import list_embedding_models
    available = list_embedding_models(host=ollama_host)

    if not available:
        console.print()
        console.print(warn("no embedding models found in Ollama"))
        console.print(line("[dim]popular: nomic-embed-text, mxbai-embed-large, bge-m3[/dim]"))
        console.print(line("[dim]install: ollama pull nomic-embed-text[/dim]"))
        console.print()
        model = typer.prompt("  Embedding model name", default="nomic-embed-text")
        return "embedding", model

    console.print(ok(f"[dim]{len(available)} model(s) found[/dim]"))
    console.print()

    model = questionary.select(
        "Embedding model:",
        choices=available,
        style=_style,
    ).ask()

    return "embedding", model


def _pick_with_typer(ollama_host: str) -> tuple[str, str | None]:
    """Fallback sem questionary."""
    strategy = typer.prompt(
        "  Retrieval strategy (keyword/embedding)",
        default="keyword",
    )
    if strategy != "embedding":
        return "keyword", None

    model = typer.prompt("  Embedding model", default="nomic-embed-text")
    return "embedding", model