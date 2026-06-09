from __future__ import annotations

import logging
from typing import NoReturn

from rich.console import Console
from rich.logging import RichHandler
import typer

console = Console()
err_console = Console(stderr=True)

_logging_ready = False


def setup_logging(verbose: bool = False) -> None:
    """Configure logging output for CLI commands.

    Always routes WARNING+ through Rich. verbose only controls structured
    pipeline output printed via console — not the log level.
    """
    global _logging_ready
    logging.basicConfig(
        level=logging.WARNING,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(
            console=err_console,
            show_path=False,
            show_time=False,
            rich_tracebacks=True,
            markup=True,
        )],
        force=True,
    )
    _logging_ready = True


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


def hint(label: str, value: str, *, style: str = "cyan") -> str:
    """A labeled instruction line shown beneath an error or warning.

    `label` is the left-aligned cue ("create it", "run", "valid values");
    `value` is the detail. Use the default style="cyan" for runnable
    commands and values the user should type, style="dim" for paths and
    purely informational notes.
    """
    return f"    [dim]{label:<12}[/dim] [{style}]{value}[/{style}]"


def fatal(message: str, *hints: str) -> NoReturn:
    """Print an error message, optional instruction lines, and exit (status 1).

    Pass lines built with `hint()` to guide the user toward the fix:

        fatal("axon.config.json not found", hint("run", "axon init"))
    """
    err_console.print()
    err_console.print(err(message))
    if hints:
        err_console.print()
        for line in hints:
            err_console.print(line)
    err_console.print()
    raise SystemExit(1)
