"""
cli/_print.py — the CLI's visual contract.

Every command renders through these helpers. No command defines its own
glyphs, colors, or status vocabulary — this module is the single source of
the contract, mirrored on the web by the Axon design-system tokens.

semantic marks
    ◆  ok      green    (#34D399 on the web)   success
    ▲  warn    yellow   (#FBBF24)              caution
    ■  err     red      (#F87171)              error
    ◇  info    cyan     (cyan-300)             informational notice

structure
    │  line / divider   dim continuation column under a mark
    ◇  step             dim — a completed sub-item in a sequence

status (resource lifecycle, axon.types.ResourceStatus)
    online green · validating yellow · drift yellow · offline red ·
    failed red, slightly darker

Colors are rich named colors — the terminal theme decides the exact
rendering; the hex values are the design-system equivalents on the web.

Copy rules: lowercase, terse, declarative. Never emoji — the glyphs carry
the load. Address the user as "you", never "we".
"""
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


# ── semantic marks ────────────────────────────────────────────────────────────

def ok(text: str) -> str:
    """◆ success."""
    return f"[green]◆[/green] {text}"


def warn(text: str) -> str:
    """▲ caution."""
    return f"[yellow]▲[/yellow] {text}"


def err(text: str) -> str:
    """■ error."""
    return f"[red]■[/red] {text}"


def info(text: str) -> str:
    """◇ informational notice — a standalone fact, neither success nor caution."""
    return f"[cyan]◇[/cyan] {text}"


def mark(good: bool) -> str:
    """Compact table-cell mark: ◆ on success, ■ on failure. Never ✓/✗."""
    return "[green]◆[/green]" if good else "[red]■[/red]"


# ── structure ─────────────────────────────────────────────────────────────────

def line(text: str) -> str:
    """│ continuation — detail rendered under a semantic mark."""
    return f"  [dim]│[/dim]  {text}"


def step(text: str) -> str:
    """◇ dim — a completed sub-item in a sequence."""
    return f"[dim]◇[/dim] {text}"


def divider() -> str:
    return "[dim]│[/dim]"


# ── resource lifecycle ────────────────────────────────────────────────────────

_STATUS_STYLES = {
    "online":     "green",
    "validating": "yellow",
    "drift":      "yellow",
    "offline":    "red",
    "failed":     "red3",     # slightly darker than offline
}


def status(value: object, label: str | None = None) -> str:
    """A resource lifecycle status, colored per the contract.

    Accepts a ResourceStatus or its string value. `label` overrides the
    displayed text while keeping the status color ("drift detected").
    """
    v = getattr(value, "value", value)
    style = _STATUS_STYLES.get(str(v), "dim")
    return f"[{style}]{label or v}[/{style}]"


# ── guidance / exit ───────────────────────────────────────────────────────────

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
        for line_ in hints:
            err_console.print(line_)
    err_console.print()
    raise SystemExit(1)
