from __future__ import annotations

from pathlib import Path

import typer

from axon.cli._print import console, ok, warn, fatal, info, step, divider

app = typer.Typer(help="Manage PA skill files.")

_SKILLS_DIR  = Path("src/axon/pa/skills")
_BASE_SKILL  = _SKILLS_DIR / "intent_extraction.md"
_DOMAINS_DIR = _SKILLS_DIR / "domains"

# Output contract — hardcoded aqui também para validação e reset
_OUTPUT_CONTRACT_MARKER = "Output rules (enforced by parser — do not change):"

_DOMAIN_TEMPLATE = """\
# {name} Domain

# Describe the context in which this domain operates.
# This file is appended to the base intent_extraction.md behavior
# before the output contract — do not include JSON schemas here.

## Available data sources
# List what the system can retrieve autonomously.
# Example: "Patient data is always available via health_search."

## Required inputs
# List what must always come from the user.
# Example: "Always confirm the patient name before executing."

## Compliance
# List actions that require human confirmation before execution.
# Example: "Prescription changes require clarification before proceeding."
"""

_BASE_DEFAULT = """\
You are the intent extraction engine of a multi-agent orchestration system.

Think step by step about what the user wants, what information is present,
what is missing, and whether the system can act safely without clarification.

Ask at most 3 clarifying questions. Prefer to proceed with reasonable assumptions
over asking unnecessary questions.
"""


# ── helpers ───────────────────────────────────────────────────────────────────

def _resolve_skills_dir() -> Path:
    """Tenta encontrar o diretório de skills a partir do cwd."""
    candidates = [
        Path("src/axon/pa/skills"),
        Path("axon/pa/skills"),
    ]
    for c in candidates:
        if c.exists():
            return c
    # fallback — usa o primeiro candidato mesmo que não exista ainda
    return candidates[0]


def _get_active_domain() -> str | None:
    try:
        from axon.config import read_config
        return read_config().pa.domain
    except Exception:
        return None


def _contract_intact(base_path: Path) -> bool:
    """Verifica se o OUTPUT_CONTRACT marker está presente no base skill."""
    if not base_path.exists():
        return False
    content = base_path.read_text(encoding="utf-8")
    return _OUTPUT_CONTRACT_MARKER in content


# ── commands ──────────────────────────────────────────────────────────────────

@app.command("list")
def skills_list() -> None:
    """List available skills and domains."""
    skills_dir  = _resolve_skills_dir()
    base_path   = skills_dir / "intent_extraction.md"
    domains_dir = skills_dir / "domains"
    active      = _get_active_domain()

    console.print()
    console.print("  [bold]SKILLS[/bold]")
    console.print()

    # base skill
    if base_path.exists():
        contract_ok = _contract_intact(base_path)
        contract    = "[green]✓[/green]" if contract_ok else "[red]✗ modified[/red]"
        console.print(f"  {step(f'base   [dim]{base_path}[/dim]  contract: {contract}')}")
    else:
        console.print(f"  {step(f'base   [red]not found[/red] — run: axon pa skills reset')}")

    console.print(divider())

    # domains
    if domains_dir.exists():
        domains = sorted(domains_dir.glob("*.md"))
    else:
        domains = []

    if domains:
        for d in domains:
            is_active = d.stem == active
            marker    = " [cyan]← active[/cyan]" if is_active else ""
            console.print(f"  {step(f'domain [dim]{d.stem}[/dim]{marker}')}")
    else:
        console.print(f"  {step('[dim]domain (none available)[/dim]')}")
        console.print(info("[dim]create with: axon pa skills new --domain <name>[/dim]"))

    if active and not any(d.stem == active for d in domains):
        console.print()
        console.print(warn(f"active domain '[bold]{active}[/bold]' not found in {domains_dir}"))
        console.print(info(f"[dim]create it: axon pa skills new --domain {active}[/dim]"))

    console.print()


@app.command("new")
def skills_new(
    domain: str = typer.Option(..., "--domain", "-d", help="Domain name (e.g. clinical, finance)"),
) -> None:
    """Create a new domain skill file from template."""
    skills_dir  = _resolve_skills_dir()
    domains_dir = skills_dir / "domains"
    domains_dir.mkdir(parents=True, exist_ok=True)

    path = domains_dir / f"{domain}.md"

    if path.exists():
        console.print()
        console.print(warn(f"[bold]{domain}.md[/bold] already exists at {path}"))
        console.print(info("[dim]edit it directly in your editor[/dim]"))
        console.print()
        raise typer.Exit(1)

    path.write_text(_DOMAIN_TEMPLATE.format(name=domain.capitalize()), encoding="utf-8")

    console.print()
    console.print(ok(f"[bold]{domain}.md[/bold] created"))
    console.print(info(f"[dim]{path}[/dim]"))
    console.print()
    console.print(info("[dim]edit the file, then activate with:[/dim]"))
    console.print(info(f"[dim]axon pa config --domain {domain}[/dim]"))
    console.print()


@app.command("show")
def skills_show(
    domain: str | None = typer.Option(None, "--domain", "-d", help="Domain to show. Omit to show base skill."),
) -> None:
    """Show the content of a skill file."""
    skills_dir = _resolve_skills_dir()

    if domain:
        path = skills_dir / "domains" / f"{domain}.md"
        label = f"domain: {domain}"
    else:
        path  = skills_dir / "intent_extraction.md"
        label = "base skill"

    if not path.exists():
        fatal(f"{label} not found at {path}")

    content = path.read_text(encoding="utf-8")

    console.print()
    console.print(f"  [bold]{label}[/bold]  [dim]{path}[/dim]")
    console.print()
    for line in content.splitlines():
        console.print(f"  [dim]│[/dim]  {line}")
    console.print()


@app.command("validate")
def skills_validate() -> None:
    """Verify that the base skill output contract is intact."""
    skills_dir = _resolve_skills_dir()
    base_path  = skills_dir / "intent_extraction.md"

    console.print()

    if not base_path.exists():
        console.print(warn(f"base skill not found at [dim]{base_path}[/dim]"))
        console.print(info("[dim]run: axon pa skills reset[/dim]"))
        console.print()
        raise typer.Exit(1)

    if _contract_intact(base_path):
        console.print(ok("[bold]output contract intact[/bold]"))
        console.print(info(f"[dim]{base_path}[/dim]"))
    else:
        console.print(warn("[bold]output contract missing or modified[/bold]"))
        console.print(info(f"[dim]{base_path}[/dim]"))
        console.print()
        console.print(info("[dim]the Axon parser expects a specific JSON schema in <output> tags.[/dim]"))
        console.print(info("[dim]modifying the output contract may cause parse failures.[/dim]"))
        console.print()
        console.print(info("[dim]to restore:[/dim]"))
        console.print(info("[dim]  axon pa skills reset[/dim]"))
        console.print(info("[dim]  axon pa skills reset --contract-only  (preserves your behavior edits)[/dim]"))
        raise typer.Exit(1)

    console.print()


@app.command("reset")
def skills_reset(
    contract_only: bool = typer.Option(
        False, "--contract-only",
        help="Restore only the output contract section, preserving behavior edits.",
    ),
) -> None:
    """Restore the base skill to its default."""
    skills_dir = _resolve_skills_dir()
    base_path  = skills_dir / "intent_extraction.md"
    skills_dir.mkdir(parents=True, exist_ok=True)

    if contract_only and base_path.exists():
        # preserva o behavior do operador, restaura só o contrato
        existing = base_path.read_text(encoding="utf-8")

        # separa behavior do contrato se o marker existir
        marker = "\n---\n"
        if marker in existing:
            behavior = existing.split(marker)[0].strip()
        else:
            behavior = existing.strip()

        from axon.pa.intent_extractor import _OUTPUT_CONTRACT
        new_content = f"{behavior}\n\n{_OUTPUT_CONTRACT}\n"
        base_path.write_text(new_content, encoding="utf-8")

        console.print()
        console.print(ok("[bold]output contract restored[/bold]"))
        console.print(info("[dim]behavior section preserved[/dim]"))

    else:
        base_path.write_text(_BASE_DEFAULT, encoding="utf-8")

        console.print()
        console.print(ok("[bold]base skill restored to default[/bold]"))

    console.print(info(f"[dim]{base_path}[/dim]"))
    console.print()
    console.print(info("[dim]NOTE: restart the PA for changes to take effect[/dim]"))
    console.print(info("[dim]  axon pa run --query '...'[/dim]"))
    console.print(info("[dim]  axon pa chat[/dim]"))
    console.print()