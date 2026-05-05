from __future__ import annotations

from rich.console import Console
import typer

console = Console()
err_console = Console(stderr=True)


def ok(text: str) -> str:
    return f"[green]◆[/green] {text}"
 
 
def info(text: str) -> str:
    return f"  [dim]│[/dim]  {text}"
 
 
def step(text: str) -> str:
    """A completed step in a sequence."""
    return f"[dim]◇[/dim] {text}"
 
 
def warn(text: str) -> str:
    return f"[yellow]▲[/yellow] {text}"
 
 
def err(text: str) -> str:
    return f"[red]■[/red] {text}"
 
 
def divider() -> str:
    return "[dim]│[/dim]"
 
 
def fatal(message: str) -> None:
    err_console.print(err(message))
    raise SystemExit(1)
