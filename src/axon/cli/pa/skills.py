from __future__ import annotations

from pathlib import Path

import typer

from axon.cli._print import console, ok, warn, fatal, line, mark, step, divider

app = typer.Typer(help="Manage PA skill files.")

_SKILLS_DIR  = Path("src/axon/pa/skills")
_BASE_SKILL  = _SKILLS_DIR / "intent_extraction.md"
_DOMAINS_DIR = _SKILLS_DIR / "domains"

# O output contract é hardcoded em axon.pa.intent_extractor (_OUTPUT_CONTRACT)
# e anexado ao behavior em runtime — o .md carrega só o behavior. Estes marcadores
# detectam um contrato colado indevidamente no .md (duplicaria o prompt).
_CONTRACT_MARKERS = (
    "Output rules (enforced by parser — do not change):",
    "<output>",
)

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


def _behavior_clean(base_path: Path) -> bool:
    """True quando o .md é behavior-only — sem um output contract embutido.

    O contrato real é hardcoded no IntentExtractor e anexado em runtime;
    um contrato colado no .md apareceria duplicado no prompt.
    """
    if not base_path.exists():
        return False
    content = base_path.read_text(encoding="utf-8")
    return not any(m in content for m in _CONTRACT_MARKERS)


# ── commands ──────────────────────────────────────────────────────────────────

@app.command("list")
def skills_list() -> None:
    """
    List available skills and domains.

    Shows the base intent-extraction skill (behavior-only — the output
    contract is enforced at runtime) and the domain files under
    skills/domains/, marking the active one.
    """
    skills_dir  = _resolve_skills_dir()
    base_path   = skills_dir / "intent_extraction.md"
    domains_dir = skills_dir / "domains"
    active      = _get_active_domain()

    console.print()
    console.print("  [bold]skills[/bold]")
    console.print()

    # base skill
    if base_path.exists():
        clean    = _behavior_clean(base_path)
        contract = (
            f"{mark(True)} [dim]enforced at runtime[/dim]" if clean
            else f"{mark(False)} [red]output block embedded in .md[/red]"
        )
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
        console.print(line("[dim]create with: axon pa skills new --domain <name>[/dim]"))

    if active and not any(d.stem == active for d in domains):
        console.print()
        console.print(warn(f"active domain '[bold]{active}[/bold]' not found in {domains_dir}"))
        console.print(line(f"[dim]create it: axon pa skills new --domain {active}[/dim]"))

    console.print()


@app.command("new")
def skills_new(
    domain: str = typer.Option(..., "--domain", "-d", help="Domain name (e.g. clinical, finance)"),
) -> None:
    """
    Create a new domain skill file from template.

    A domain file adds the context your field requires to intent
    extraction — available data sources, required inputs, compliance
    rules. It is appended to the base behavior at runtime; activate it
    with 'axon pa config --domain <name>'.
    """
    skills_dir  = _resolve_skills_dir()
    domains_dir = skills_dir / "domains"
    domains_dir.mkdir(parents=True, exist_ok=True)

    path = domains_dir / f"{domain}.md"

    if path.exists():
        console.print()
        console.print(warn(f"[bold]{domain}.md[/bold] already exists at {path}"))
        console.print(line("[dim]edit it directly in your editor[/dim]"))
        console.print()
        raise typer.Exit(1)

    path.write_text(_DOMAIN_TEMPLATE.format(name=domain.capitalize()), encoding="utf-8")

    console.print()
    console.print(ok(f"[bold]{domain}.md[/bold] created"))
    console.print(line(f"[dim]{path}[/dim]"))
    console.print()
    console.print(line("[dim]edit the file, then activate with:[/dim]"))
    console.print(line(f"[dim]axon pa config --domain {domain}[/dim]"))
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
    for ln in content.splitlines():
        console.print(line(ln))
    console.print()


@app.command("validate")
def skills_validate() -> None:
    """Verify that the base skill is behavior-only (no embedded output contract)."""
    skills_dir = _resolve_skills_dir()
    base_path  = skills_dir / "intent_extraction.md"

    console.print()

    if not base_path.exists():
        console.print(warn(f"base skill not found at [dim]{base_path}[/dim]"))
        console.print(line("[dim]run: axon pa skills reset[/dim]"))
        console.print()
        raise typer.Exit(1)

    if _behavior_clean(base_path):
        console.print(ok("[bold]base skill is behavior-only[/bold] — output contract enforced at runtime"))
        console.print(line(f"[dim]{base_path}[/dim]"))
    else:
        console.print(warn("[bold]output block embedded in the behavior file[/bold]"))
        console.print(line(f"[dim]{base_path}[/dim]"))
        console.print()
        console.print(line("[dim]the output contract is hardcoded and appended at runtime —[/dim]"))
        console.print(line("[dim]an <output> block in the .md would appear twice in the prompt.[/dim]"))
        console.print()
        console.print(line("[dim]remove the block from the file, or restore the default:[/dim]"))
        console.print(line("[dim]  axon pa skills reset[/dim]"))
        raise typer.Exit(1)

    console.print()


@app.command("reset")
def skills_reset() -> None:
    """Restore the base skill to its default (behavior-only)."""
    skills_dir = _resolve_skills_dir()
    base_path  = skills_dir / "intent_extraction.md"
    skills_dir.mkdir(parents=True, exist_ok=True)

    base_path.write_text(_BASE_DEFAULT, encoding="utf-8")

    console.print()
    console.print(ok("[bold]base skill restored to default[/bold]"))
    console.print(line(f"[dim]{base_path}[/dim]"))
    console.print()
    console.print(line("[dim]note: restart the PA for changes to take effect[/dim]"))
    console.print(line("[dim]  axon pa run --query '...'[/dim]"))
    console.print(line("[dim]  axon pa chat[/dim]"))
    console.print()