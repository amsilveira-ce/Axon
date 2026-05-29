from __future__ import annotations

from typing import Optional

import typer

from axon.cli._print import console, ok, info, fatal, hint

app = typer.Typer(help="Show or edit the PA resource policy.")

_FALLBACKS = {"skip", "fail", "ask_user"}


def _parse_bool(s: str) -> bool:
    return s.lower() in ("true", "1", "yes", "on")


@app.callback(invoke_without_command=True)
def policy(ctx: typer.Context) -> None:
    """
    Show or edit the operator resource policy (axon.config.json).

    Without a subcommand: shows the current policy.
    Use 'set' to edit fields. A política é aplicada pelo Resolver ao escolher
    recursos vindos dos Gateway Agents.
    """
    from axon.config import read_config

    try:
        read_config()
    except FileNotFoundError:
        fatal("axon.config.json not found", hint("run", "axon init"))

    if ctx.invoked_subcommand is None:
        _show()


@app.command("set")
def policy_set(
    allow_paid:        Optional[str]   = typer.Option(None, "--allow-paid",         help="true | false — permitir recursos pagos"),
    max_cost_per_call: Optional[float] = typer.Option(None, "--max-cost-per-call",  help="USD máx por chamada (0 = sem limite)"),
    require_auth:      Optional[str]   = typer.Option(None, "--require-auth-setup", help="true | false — descartar recursos sem token"),
    match_threshold:   Optional[float] = typer.Option(None, "--match-threshold",    help="match mínimo 0..1 para aceitar um recurso do GA"),
    fallback:          Optional[str]   = typer.Option(None, "--fallback-strategy",  help="skip | fail | ask_user"),
) -> None:
    """Edit resource policy fields and save to axon.config.json."""
    from axon.config import patch_config

    if not any([
        allow_paid, max_cost_per_call is not None, require_auth,
        match_threshold is not None, fallback,
    ]):
        fatal("nothing to set", hint("example", "axon pa policy set --allow-paid true"))

    changes: list[str] = []

    def _apply(cfg):
        rp  = cfg.pa.resource_policy
        upd: dict = {}

        if allow_paid is not None:
            v = _parse_bool(allow_paid)
            upd["allow_paid"] = v
            changes.append(f"allow_paid = {v}")

        if max_cost_per_call is not None:
            v = None if max_cost_per_call <= 0 else max_cost_per_call
            upd["max_cost_per_call"] = v
            changes.append(f"max_cost_per_call = {v}")

        if require_auth is not None:
            v = _parse_bool(require_auth)
            upd["require_auth_setup"] = v
            changes.append(f"require_auth_setup = {v}")

        if match_threshold is not None:
            if not 0.0 <= match_threshold <= 1.0:
                fatal("--match-threshold must be between 0.0 and 1.0")
            upd["match_threshold"] = match_threshold
            changes.append(f"match_threshold = {match_threshold}")

        if fallback is not None:
            if fallback not in _FALLBACKS:
                fatal(
                    f"invalid --fallback-strategy '{fallback}'",
                    hint("valid values", ", ".join(sorted(_FALLBACKS))),
                )
            upd["fallback_strategy"] = fallback
            changes.append(f"fallback_strategy = {fallback}")

        return cfg.model_copy(update={
            "pa": cfg.pa.model_copy(update={"resource_policy": rp.model_copy(update=upd)})
        })

    patch_config(_apply)

    console.print()
    for c in changes:
        console.print(f"  {ok(f'[dim]{c}[/dim]')}")
    console.print()
    console.print(info("[dim]NOTE: restart the PA for changes to take effect[/dim]"))
    console.print()


# ── show ────────────────────────────────────────────────────────────────────────

def _show() -> None:
    from axon.config import read_config
    rp = read_config().pa.resource_policy

    max_cost = (
        "[dim]none[/dim]" if rp.max_cost_per_call is None
        else f"[cyan]${rp.max_cost_per_call:.4f}[/cyan]"
    )

    console.print()
    console.print("  [bold]PA resource policy[/bold]")
    console.print()
    console.print(info(f"allow_paid          [cyan]{rp.allow_paid}[/cyan]"))
    console.print(info(f"max_cost_per_call   {max_cost}"))
    console.print(info(f"require_auth_setup  [cyan]{rp.require_auth_setup}[/cyan]"))
    console.print(info(f"match_threshold     [cyan]{rp.match_threshold}[/cyan]"))
    console.print(info(f"fallback_strategy   [cyan]{rp.fallback_strategy}[/cyan]"))
    console.print()
