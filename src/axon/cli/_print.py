
from __future__ import annotations
 
from rich.console import Console
import typer

console = Console()
err_console = Console(stderr=True)

# =======================
# Essenciais
# =======================
def warn(text: str) -> str:
    return f"  [yellow]⚠[/yellow]  {text}"

def info(text: str) -> str:
    return f"  [cyan]ℹ[/cyan]  {text}"

def ok(text: str) -> str:
    return f"[green]{text}[/green]"

def fatal(text: str) -> None:
    err_console.print(f"[red]✖ {text}[/red]")
    raise typer.Exit(code=1)
 

# =======================
# Estilização
# =======================

def question(text: str) -> str:
    """Prefix for an active question."""
    return f"[cyan]◆[/cyan] {text}"
 
 
def answered(label: str, value: str) -> str:
    """Replaces the question line after the user answers."""
    return f"[dim]◇[/dim] {label}  [cyan]{value}[/cyan]"

def divider() -> str:
    return "[dim]│[/dim]"
