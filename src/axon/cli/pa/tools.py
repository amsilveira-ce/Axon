from __future__ import annotations

import json
from pathlib import Path

import typer

from axon.cli._print import console, ok, warn, fatal, line, step, divider

app = typer.Typer(help="Manage local PA tools.")


def _read_tools(path: Path) -> dict:
    if not path.exists():
        fatal(f"local_tools.json not found at {path} — run 'axon init' first.")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_tools(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _get_path() -> Path:
    from axon.config import paths
    return paths().pa_local_tools


# ── list 

@app.command("list")
def tools_list() -> None:
    """
    List registered local tools and their status.

    Local tools live in .axon/pa/local_tools.json and are always the
    Resolver's first stop. Disabled tools stay registered but are
    hidden from the Resolver.
    """
    path  = _get_path()
    data  = _read_tools(path)
    tools = data.get("tools", [])

    console.print()
    console.print("  [bold]local tools[/bold]")
    console.print()

    if not tools:
        console.print(line("[dim]no tools registered[/dim]"))
        console.print(line("[dim]add with: axon pa tools add --name <name> --command '<cmd>' --capability <tag>[/dim]"))
        console.print()
        return

    for t in tools:
        enabled = t.get("enabled", True)
        status  = "[green]enabled[/green]" if enabled else "[dim]disabled[/dim]"
        cmd     = " ".join(t.get("command", []))
        # console.print(f"  {step(f'[bold]{t[\"name\"]}[/bold]  {status}')}")
        title = f"[bold]{t['name']}[/bold]  {status}"
        console.print(f"  {step(title)}")
        console.print(line(f"capability  [dim]{t.get('capability', '—')}[/dim]"))
        console.print(line(f"command     [dim]{cmd}[/dim]"))
        if t.get("description"):
            console.print(line(f"description [dim]{t['description']}[/dim]"))
        console.print(divider())

    enabled_count = sum(1 for t in tools if t.get("enabled", True))
    console.print()
    console.print(line(f"[dim]{enabled_count}/{len(tools)} enabled[/dim]"))
    console.print()




# ── validação 

def _validate_command(cmd_parts: list[str], transport: str) -> str | None:
    """
    Valida o comando antes de registrar a tool.
    Retorna mensagem de erro ou None se ok.
    """
    import subprocess, sys

    if transport == "http":
        # http: testa conectividade
        endpoint = cmd_parts[0] if cmd_parts else ""
        if not endpoint.startswith(("http://", "https://")):
            return f"invalid HTTP endpoint: {endpoint!r}\nexpected format: http://host:port/path"
        try:
            import httpx
            httpx.get(endpoint, timeout=5.0)
            return None
        except Exception as exc:
            return f"HTTP endpoint unreachable: {endpoint}\nReason: {exc}"

    # stdio: verifica se é módulo Python ou executável
    if not cmd_parts:
        return "Empty command"

    # caso: python -m <module>
    if cmd_parts[0] in ("python", "python3", sys.executable) and len(cmd_parts) >= 3 and cmd_parts[1] == "-m":
        module = cmd_parts[2]
        result = subprocess.run(
            [cmd_parts[0], "-c", f"import {module}"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return (
                f"Module not found: {module}\n"
                f"  {result.stderr.strip()}\n"
                f"Make sure the package is installed in the current environment."
            )
        return None

    # caso: executável direto
    import shutil
    exe = cmd_parts[0]
    if not shutil.which(exe):
        return (
            f"Executable not found: {exe!r}\n"
            f"Make sure it is installed and available in PATH."
        )
    return None

# ── add 

@app.command("add")
def tools_add(
    name:        str            = typer.Option(...,  "--name",        help="Tool name"),
    command:     str            = typer.Option(...,  "--command",     help="Command to run the tool (e.g. 'python -m my.tool')"),
    capability:  str            = typer.Option(...,  "--capability",  help="Capability tag (e.g. web_search)"),
    description: str | None     = typer.Option(None, "--description", "-d", help="What this tool does — used by the PA to decide when to invoke it."),
    transport:   str            = typer.Option("stdio", "--transport", help="Transport: stdio | http"),
) -> None:
    """
    Register a new local tool.

    Local tools are MCP servers the PA runs itself — no Gateway
    involved — and the Resolver always checks them first. The entry is
    saved to .axon/pa/local_tools.json and the command is spawned on
    demand.

      axon pa tools add --name weather --capability weather \\
        --command 'python -m my.weather' --description 'Local forecasts'

    Restart the PA for new tools to load.
    """
    import logging
    logger = logging.getLogger(__name__)

    # Temos um guia para o porque precisa do description
    if not description:
        console.print()
        console.print(warn("[bold]--description is required[/bold]"))
        console.print()
        console.print(line("The description tells the Principal Agent [bold]when and why[/bold] to use this tool."))
        console.print(line("Without it, the PA cannot decide which tool to invoke for a given task."))
        console.print()
        console.print(line("[dim]Example:[/dim]"))
        console.print(line("[dim]  axon pa tools add \\\\[/dim]"))
        console.print(line(f'[dim]    --name {name or "my_tool"} \\\\[/dim]'))
        console.print(line(f'[dim]    --command "{command or "python -m my.tool"}" \\\\[/dim]'))
        console.print(line(f'[dim]    --capability "{capability or "my_capability"}" \\\\[/dim]'))
        console.print(line('[dim]    --description "Fetches sales data and returns a structured report"[/dim]'))
        console.print()
        console.print(line('[dim]Tip: be specific - "searches patient records in HStory EHR"[/dim]'))
        console.print(line('[dim]is better than "searches records".[/dim]'))
        console.print()
        raise typer.Exit(1)

    path = _get_path()
    data = _read_tools(path)

    if any(t["name"] == name for t in data.get("tools", [])):
        console.print()
        console.print(warn(f"tool [bold]{name}[/bold] already registered — use 'axon pa tools remove {name}' first"))
        console.print()
        raise typer.Exit(1)

    # ── validação do comando ───────────────────────────────────────────
    cmd_parts = command.split()
    error = _validate_command(cmd_parts, transport)
    if error:
        logger.error("[pa tools add] command validation failed: %s", error)
        console.print()
        console.print(warn(f"[bold]{name}[/bold] not registered — command validation failed"))
        console.print()
        for ln in error.splitlines():
            console.print(line(f"[red]{ln}[/red]"))
        console.print()
        console.print(line(f"[dim]fix the issue and run:[/dim]"))
        console.print(line(f"[dim]  axon pa tools add --name {name} --command \"{command}\" --capability {capability}[/dim]"))
        console.print()
        raise typer.Exit(1)

    tool = {
        "name":        name,
        "capability":  capability,
        "description": description,
        "transport":   transport,
        "command":     cmd_parts,
        "enabled":     True,
    }

    data.setdefault("tools", []).append(tool)
    _write_tools(path, data)

    console.print()
    console.print(ok(f"[bold]{name}[/bold] registered"))
    console.print(line(f"capability [dim]{capability}[/dim]"))
    console.print(line(f"command    [dim]{command}[/dim]"))
    console.print()


# ── remove 

@app.command("remove")
def tools_remove(
    name: str = typer.Argument(..., help="Tool name to remove"),
) -> None:
    """Remove a local tool."""
    path  = _get_path()
    data  = _read_tools(path)
    tools = data.get("tools", [])

    before = len(tools)
    data["tools"] = [t for t in tools if t["name"] != name]

    if len(data["tools"]) == before:
        fatal(f"tool '{name}' not found")

    _write_tools(path, data)

    console.print()
    console.print(ok(f"[bold]{name}[/bold] removed"))
    console.print()


# ── enable / disable 

@app.command("enable")
def tools_enable(
    name: str = typer.Argument(..., help="Tool name to enable"),
) -> None:
    """Enable a disabled tool."""
    _set_enabled(name, True)


@app.command("disable")
def tools_disable(
    name: str = typer.Argument(..., help="Tool name to disable"),
) -> None:
    """Disable a tool without removing it."""
    _set_enabled(name, False)


def _set_enabled(name: str, enabled: bool) -> None:
    path  = _get_path()
    data  = _read_tools(path)
    found = False

    for t in data.get("tools", []):
        if t["name"] == name:
            t["enabled"] = enabled
            found = True
            break

    if not found:
        fatal(f"tool '{name}' not found")

    _write_tools(path, data)

    label = "[green]enabled[/green]" if enabled else "[dim]disabled[/dim]"
    console.print()
    console.print(ok(f"[bold]{name}[/bold] {label}"))
    console.print()
