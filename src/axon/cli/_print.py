
from __future__ import annotations
 
from rich.console import Console
import typer

console = Console()
err_console = Console(stderr=True)

def warn(text: str) -> str:
    return f"  [yellow]⚠[/yellow]  {text}"

def info(text: str) -> str:
    return f"  [cyan]ℹ[/cyan]  {text}"

def ok(text: str) -> str:
    return f"[green]{text}[/green]"

def fatal(text: str) -> None:
    err_console.print(f"[red]✖ {text}[/red]")
    raise typer.Exit(code=1)
 