import typer
from axon.config import (
    AxonConfig, PAConfig, GAConfig, LLMConfig,
    config_exists, write_config, OperationalMode, ReasoningMode
)
from axon.cli._print import console, warn, ok, fatal

app = typer.Typer()

_SECTION = "[dim]  ─────────────────────────────────────[/dim]"


def _section(title: str) -> None:
    console.print()
    console.print(f"  [bold]{title}[/bold]")
    console.print(_SECTION)


def _prompt(label: str, default: str) -> str:
    return typer.prompt(f"  {label}", default=default)


def _pick_enum(label: str, mapping: dict, default: str, current) -> object:
    raw = _prompt(label, default)
    if raw not in mapping:
        console.print(f"  {warn(f'Unknown value [bold]{raw!r}[/bold], keeping default: [bold]{default}[/bold]')}")
        return current
    return mapping[raw]


@app.callback(invoke_without_command=True)
def init(
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept all defaults without prompting"),
) -> None:
    """Create axon.config.json in the current directory."""

    if config_exists():
        console.print()
        console.print(f"  {warn('[bold]Already initialized[/bold]')}")
        console.print()
        console.print("  [dim]│[/dim]  [cyan]axon.config.json[/cyan] already exists in this directory.")
        console.print("  [dim]│[/dim]  To start over, delete it and run [bold]axon init[/bold] again:")
        console.print()
        console.print("  [dim]$[/dim]  [bold]rm axon.config.json[/bold]")
        console.print()
        raise typer.Exit(1)

    console.print()
    console.print("  [bold]Axon[/bold] [dim]v0.1.0[/dim]")

    pa  = PAConfig()
    ga  = GAConfig()
    llm = LLMConfig()

    if not yes:
        # ── Principal Agent ───────────────────────────────
        _section("Principal Agent")

        raw = _prompt("Control API port", str(pa.port))
        pa.port = int(raw)

        pa.default_mode = _pick_enum(
            "Default mode  (agent / copilot / no-llm)",
            OperationalMode._value2member_map_,
            pa.default_mode.value,
            pa.default_mode,
        )

        pa.default_reasoning_mode = _pick_enum(
            "Reasoning mode  (react / rewoo / tot)",
            ReasoningMode._value2member_map_,
            pa.default_reasoning_mode.value,
            pa.default_reasoning_mode,
        )

        raw = _prompt("Max iterations", str(pa.max_iterations))
        pa.max_iterations = int(raw)

        # ── LLM ───────────────────────────────────────────
        _section("LLM")

        llm.host = _prompt("Provider host", llm.host)
        llm.model = _prompt("Model", llm.model)

        raw = _prompt("Request timeout (s)", str(llm.timeout))
        llm.timeout = int(raw)

        pa.llm = llm

        # ── Gateway Agent ──────────────────────────────────
        _section("Gateway Agent")

        raw = _prompt("Port", str(ga.port))
        ga.port = int(raw)

    config = AxonConfig(pa=pa, ga=ga)

    try:
        write_config(config)
    except Exception as e:
        fatal(f"Could not write axon.config.json: {e}")

    # ── Summary ────────────────────────────────────────────
    console.print()
    console.print(f"  {ok('[bold]axon.config.json[/bold] created')}")
    console.print()
    console.print(f"  [dim]PA[/dim]   localhost:[cyan]{pa.port}[/cyan]  [dim]·[/dim]  {pa.default_mode.value}  [dim]·[/dim]  {pa.default_reasoning_mode.value}  [dim]·[/dim]  max {pa.max_iterations} iterations")
    console.print(f"  [dim]LLM[/dim]  [cyan]{llm.model}[/cyan]  [dim]@[/dim]  {llm.host}  [dim](timeout {llm.timeout}s)[/dim]")
    console.print(f"  [dim]GA[/dim]   localhost:[cyan]{ga.port}[/cyan]")
    console.print()
    console.print("  [dim]Next steps[/dim]")
    console.print("  [dim]  axon pa run               [/dim] start the Principal Agent")
    console.print("  [dim]  axon add agent <url>      [/dim] register an agent in the Gateway")
    console.print("  [dim]  axon add mcp <name>       [/dim] register an MCP tool")
    console.print()
