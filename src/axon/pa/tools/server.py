"""
pa/tools/server.py — FastMCP server com tools locais do PA.

Tools registradas:
  calculate     → eval seguro de expressões matemáticas
  web_search    → DuckDuckGo Instant Answer API (sem key)
  read_file     → lê PDF/TXT/CSV/MD do filesystem
  get_datetime  → datetime atual + cálculos de data

Transport: stdio
Comando:   python -m axon.pa.tools.server

Uso no axon.config.json (recurso MCP):
  {
    "command": ["python", "-m", "axon.pa.tools.server"],
    "type": "stdio"
  }
"""

from __future__ import annotations

from fastmcp import FastMCP

from axon.pa.tools.calculator   import safe_eval
from axon.pa.tools.datetime_tool import current_datetime, add_days, days_between
from axon.pa.tools.file_reader  import read_file
from axon.pa.tools.web_search   import web_search as _web_search

mcp = FastMCP(
    name="axon-pa-tools",
    instructions=(
        "Local tools for the Axon Principal Agent. "
        "Use calculate for math, web_search for live information, "
        "read_file to access local documents, and get_datetime for time-related tasks."
    ),
)


# ---------------------------------------------------------------------------
#   calculate
# ---------------------------------------------------------------------------

@mcp.tool
def calculate(expression: str) -> str:
    """
    Evaluate a mathematical expression safely.

    Supports: +, -, *, /, //, %, **, abs, round, sqrt, ceil, floor,
              log, sin, cos, tan, pi, e

    Args:
        expression: mathematical expression as a string, e.g. "2 ** 10 + sqrt(16)"

    Returns:
        The numeric result as a string.
    """
    try:
        result = safe_eval(expression)
        return str(result)
    except (ValueError, ZeroDivisionError) as exc:
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
#   web_search
# ---------------------------------------------------------------------------

@mcp.tool
def web_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Search the web using DuckDuckGo (no API key required).

    Args:
        query:       search query
        max_results: number of results to return (1-10, default 5)

    Returns:
        List of results, each with: title, snippet, url.
        Empty list if no results found.
    """
    try:
        return _web_search(query, max_results=max_results)
    except RuntimeError as exc:
        return [{"title": "Error", "snippet": str(exc), "url": ""}]


# ---------------------------------------------------------------------------
#   read_file
# ---------------------------------------------------------------------------

@mcp.tool
def read_file_tool(path: str, max_chars: int = 8000) -> dict:
    """
    Read the content of a local file.

    Supported formats: .txt, .md, .csv, .pdf

    Args:
        path:      absolute or relative path to the file
        max_chars: maximum characters to return (default 8000)

    Returns:
        Dict with: path, type, content, truncated (bool).
    """
    try:
        return read_file(path, max_chars=max_chars)
    except (FileNotFoundError, ValueError, ImportError) as exc:
        return {
            "path":      path,
            "type":      "error",
            "content":   str(exc),
            "truncated": False,
        }


# ---------------------------------------------------------------------------
#   get_datetime
# ---------------------------------------------------------------------------

@mcp.tool
def get_datetime(timezone: str = "UTC") -> dict:
    """
    Get the current date and time.

    Args:
        timezone: timezone string — "UTC" or offset like "UTC-3", "UTC+1"

    Returns:
        Dict with: iso, date, time, weekday, timezone.
    """
    return current_datetime(tz=timezone)


@mcp.tool
def add_days_to_date(date: str, days: int) -> str:
    """
    Add or subtract days from a date.

    Args:
        date: date in YYYY-MM-DD format, or "today"
        days: number of days to add (negative to subtract)

    Returns:
        Resulting date in YYYY-MM-DD format.
    """
    try:
        return add_days(date, days)
    except ValueError as exc:
        return f"Error: {exc}"


@mcp.tool
def days_between_dates(date_a: str, date_b: str) -> int:
    """
    Calculate the number of days between two dates.

    Args:
        date_a: start date in YYYY-MM-DD format
        date_b: end date in YYYY-MM-DD format

    Returns:
        Number of days (positive if date_b > date_a).
    """
    try:
        return days_between(date_a, date_b)
    except ValueError as exc:
        return -1


# ---------------------------------------------------------------------------
#   entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()