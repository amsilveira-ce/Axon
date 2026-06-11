from __future__ import annotations

import json
from pathlib import Path

import typer

from axon.config import (
    AxonConfig, PAConfig, GAInstanceConfig, ConnectedGateway,
    DEFAULT_LOCAL_TOOLS,
    config_exists, write_config,
    resolve_data_dir, AxonPaths, GAPaths,
)
from axon.cli._print import console, warn, ok, fatal, info, step, divider
from axon.cli.ga._prompts import pick_retrieval_strategy

app = typer.Typer()


def _bootstrap_files(p: AxonPaths, ga_dir: Path, ga_name: str) -> None:
    p.makedirs()

    gp = GAPaths(ga_dir)
    gp.makedirs()

    pa_defaults = {
        p.pa_resource_cache: {"version": "0.1.0", "resources": []},
        p.pa_memory_bank:    {"version": "0.1.0", "entries": []},
        p.pa_local_tools:    DEFAULT_LOCAL_TOOLS,
    }
    ga_json_default = {
        "name":               ga_name,
        "description":        "",
        "organization":       None,
        "trust_level":        "local",
        "port":               5000,
        "data_dir":           str(ga_dir),
        "version":            "0.1.0",
        "retrieval_strategy": "keyword",
        "embedding_model":    None,
    }
    ga_defaults = {
        gp.registry:  {"version": "0.1.0", "resources": []},
        gp.tokens:    {"version": "0.1.0", "tokens": []},
        gp.ga_config: ga_json_default,
    }

    for path, content in {**pa_defaults, **ga_defaults}.items():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(content, indent=2) + "\n",
                encoding="utf-8",
            )





@app.callback(invoke_without_command=True)
def init(
    yes:      bool = typer.Option(False, "--defaults", "-d", help="Use all default values without prompting"),
    data_dir: str  = typer.Option(".axon", "--data-dir", help="Directory for runtime data (default: .axon)"),
) -> None:
    """Initialize Axon in the current directory."""

    if config_exists():
        console.print()
        console.print(warn("[bold]Already initialized[/bold]"))
        console.print()
        console.print(info("[cyan]axon.config.json[/cyan] already exists."))
        console.print(info("To start over, run [bold]bash scripts/reset.sh[/bold]"))
        console.print()
        raise typer.Exit(1)

    console.print("\n  [bold]Axon[/bold] [dim]v0.1.0[/dim]\n")

    pa      = PAConfig()
    ga_port = 5000
    retrieval_strategy = "keyword"
    embedding_model    = None

    if not yes:
        raw = typer.prompt("  PA control API port", default=str(pa.port))
        pa  = pa.model_copy(update={"port": int(raw)})

        raw     = typer.prompt("  Gateway Agent port", default=str(ga_port))
        ga_port = int(raw)

        raw = typer.prompt("  Default reasoning mode (react/rewoo/tot)", default=pa.default_reasoning)
        if raw in ("react", "rewoo", "tot"):
            pa = pa.model_copy(update={"default_reasoning": raw})
        else:
            console.print(warn(f"Unknown mode '{raw}', using default: {pa.default_reasoning}"))

        raw = typer.prompt("  Max PA iterations", default=str(pa.max_iterations))
        pa  = pa.model_copy(update={"max_iterations": int(raw)})

        raw = typer.prompt(
            "  Resource cache size (max GA-discovered resources, 0 = unlimited)",
            default=str(pa.cache.max_size),
        )
        pa = pa.model_copy(update={"cache": pa.cache.model_copy(update={"max_size": int(raw)})})

        data_dir = typer.prompt("  Data directory", default=data_dir)

        # seleção interativa de retrieval
        ollama_host = typer.prompt("  Ollama host", default="http://localhost:11434")
        retrieval_strategy, embedding_model = pick_retrieval_strategy(ollama_host=ollama_host)

    # monta config
    ga_context = "axon_default"

    local_ga_entry = ConnectedGateway(
        url=f"http://localhost:{ga_port}",
        name=ga_context,
        version="0.1.0",
        trust_level="local",
        organization="local",
    )
    pa = pa.model_copy(update={"gateways": [local_ga_entry]})

    ga_instance = GAInstanceConfig(
        name=ga_context,
        port=ga_port,
        data_dir=f"{data_dir}/ga/{ga_context}",
        retrieval_strategy=retrieval_strategy,
        embedding_model=embedding_model,
    )

    config = AxonConfig(
        pa=pa,
        data_dir=data_dir,
        gateways={ga_context: ga_instance},
        current_gateway=ga_context,
    )

    try:
        write_config(config)
    except Exception as e:
        fatal(f"Could not write axon.config.json: {e}")

    cwd    = Path.cwd()
    p      = AxonPaths(resolve_data_dir(data_dir, cwd))
    ga_dir = Path(data_dir) / "ga" / ga_context
    if not ga_dir.is_absolute():
        ga_dir = cwd / ga_dir

    try:
        _bootstrap_files(p, ga_dir, ga_context)
    except Exception as e:
        fatal(f"Could not create data directory structure: {e}")

    rel = p.root.relative_to(cwd) if p.root.is_relative_to(cwd) else p.root

    console.print()
    console.print(ok("[bold]axon.config.json[/bold] created"))
    console.print()
    console.print(f"  [dim]PA[/dim]        localhost:[cyan]{pa.port}[/cyan]")
    console.print(f"  [dim]GA[/dim]        localhost:[cyan]{ga_port}[/cyan]")
    console.print(f"  [dim]reasoning[/dim]  [cyan]{pa.default_reasoning}[/cyan]")
    cache_display = f"{pa.cache.max_size} resources (LRU)" if pa.cache.max_size > 0 else "unlimited"
    console.print(f"  [dim]cache[/dim]      [cyan]{cache_display}[/cyan]")
    console.print(f"  [dim]retrieval[/dim]  [cyan]{retrieval_strategy}[/cyan]", end="")
    if embedding_model:
        console.print(f"  [dim]model:[/dim] [cyan]{embedding_model}[/cyan]")
    else:
        console.print()
    console.print(f"  [dim]data dir[/dim]  [cyan]{rel}[/cyan]")
    console.print()
    console.print(f"  {step(f'[dim]{rel}/ga/{ga_context}/registry.json[/dim]')}")
    console.print(divider())
    console.print(f"  {step(f'[dim]{rel}/ga/{ga_context}/tokens.json[/dim]')}")
    console.print(divider())
    console.print(f"  {step(f'[dim]{rel}/pa/sessions/[/dim]')}")
    console.print(divider())
    console.print(f"  {step(f'[dim]{rel}/pa/memory_bank.json[/dim]')}")
    console.print(divider())
    console.print(f"  {step(f'[dim]{rel}/pa/resource_cache.json[/dim]')}")
    console.print(divider())
    console.print(f"  {step(f'[dim]{rel}/pa/local_tools.json[/dim]  [dim]4 tools[/dim]')}")
    console.print()

    tools = DEFAULT_LOCAL_TOOLS.get("tools", [])
    console.print("  [dim]Local tools registered:[/dim]")
    for t in tools:
        console.print(info(f"[dim]{t['name']:<14} → {t['capability']}[/dim]"))
    console.print()
    console.print("  [dim]Next steps[/dim]")
    console.print(info("[dim]axon ga serve[/dim]                   start the Gateway Agent"))
    console.print(info("[dim]axon pa run --query '...'[/dim]"))
    console.print(info("[dim]axon pa chat[/dim]"))
    console.print(info("[dim]axon pa tools list[/dim]"))
    console.print()