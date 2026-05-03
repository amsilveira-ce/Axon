from __future__ import annotations

from rich.console import Console
import typer

console = Console()
err_console = Console(stderr=True)


def warn(text: str) -> str:
    return f"  [yellow]Warning:[/yellow] {text}"


def ok(text: str) -> str:
    return f"  [green]✓[/green]  {text}"


def fatal(text: str) -> None:
    err_console.print(f"  [red]Error:[/red] {text}")
    raise typer.Exit(code=1)
