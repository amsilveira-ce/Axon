from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from axon.cli._print import console, ok, warn, fatal, info, divider, hint

app = typer.Typer(help="Show or edit Principal Agent configuration.")

_NONE_SENTINEL = "__none__"


@app.callback(invoke_without_command=True)
def config(
    ctx: typer.Context,
    # ── llm ──────────────────────────────────────────────────────────
    llm:         Optional[str]   = typer.Option(None, "--llm",         help="LLM model name (e.g. deepseek-r1:8b)"),
    temperature: Optional[float] = typer.Option(None, "--temperature", help="Sampling temperature (0.0–1.0)"),
    # ── reasoning ────────────────────────────────────────────────────
    reasoning:   Optional[str]   = typer.Option(None, "--reasoning-mode",   help="Reasoning mode: react | rewoo | tot"),
    iterations:  Optional[int]   = typer.Option(None, "--max-iterations",   help="Max planning/execution cycles"),
    # ── domain ───────────────────────────────────────────────────────
    domain:      Optional[str]   = typer.Option(None, "--domain",      help="Domain skill to activate (e.g. clinical). Use 'none' to deactivate."),
    # ── budget ───────────────────────────────────────────────────────
    budget_tokens:  Optional[int]   = typer.Option(None, "--budget-tokens",  help="Max tokens per run"),
    budget_cost:    Optional[float] = typer.Option(None, "--budget-cost",    help="Max cost in USD per run"),
    budget_calls:   Optional[int]   = typer.Option(None, "--budget-calls",   help="Max LLM calls per run"),
    budget_timeout: Optional[float] = typer.Option(None, "--budget-timeout", help="Max execution time in ms"),
    # ── conversation ─────────────────────────────────────────────────
    conv_messages: Optional[int] = typer.Option(None, "--conversation-max-messages", help="Max messages in conversation window"),
    conv_tokens:   Optional[int] = typer.Option(None, "--conversation-max-tokens",   help="Max tokens in conversation window"),
    conv_mode:     Optional[str] = typer.Option(None, "--conversation-window-mode",  help="Window mode: messages | tokens | both"),
    # ── cache ────────────────────────────────────────────────────────
    cache:          Optional[str] = typer.Option(None, "--cache",          help="Enable resource cache: true | false"),
    cache_max_size: Optional[int] = typer.Option(None, "--cache-max-size", help="Max cached resources"),
    # ── gateways ─────────────────────────────────────────────────────
    gateway_add:    Optional[str] = typer.Option(None, "--gateway-add",    help="Add a gateway URL"),
    gateway_remove: Optional[str] = typer.Option(None, "--gateway-remove", help="Remove a gateway URL"),
) -> None:
    """
    Show or edit Principal Agent configuration.

    Without arguments: shows current configuration.
    With flags: edits the specified fields and saves to axon.config.json.
    """
    from axon.config import read_config, patch_config

    try:
        read_config()
    except FileNotFoundError:
        fatal(
            "axon.config.json not found in this directory",
            hint("run", "axon init"),
        )

    # nenhuma flag passada → só mostra
    _any = any([
        llm, temperature is not None, reasoning, iterations is not None,
        domain, budget_tokens, budget_cost, budget_calls, budget_timeout,
        conv_messages, conv_tokens, conv_mode,
        cache, cache_max_size, gateway_add, gateway_remove,
    ])

    if not _any:
        _show()
        return

    # ── aplica mudanças ───────────────────────────────────────────────
    changes: list[str] = []

    def _apply(cfg):
        pa = cfg.pa

        if llm:
            pa = pa.model_copy(update={"llm": pa.llm.model_copy(update={"model": llm})})
            changes.append(f"llm.model = {llm}")

        if temperature is not None:
            pa = pa.model_copy(update={"llm": pa.llm.model_copy(update={"temperature": temperature})})
            changes.append(f"llm.temperature = {temperature}")

        if reasoning:
            valid = {"react", "rewoo", "tot"}
            if reasoning not in valid:
                fatal(
                    f"invalid reasoning mode '{reasoning}'",
                    hint("valid values", ", ".join(sorted(valid))),
                )
            pa = pa.model_copy(update={"default_reasoning": reasoning})
            changes.append(f"default_reasoning = {reasoning}")

        if iterations is not None:
            pa = pa.model_copy(update={"max_iterations": iterations})
            changes.append(f"max_iterations = {iterations}")

        if domain:
            if domain.lower() == "none":
                pa = pa.model_copy(update={
                    "intent_extractor": pa.intent_extractor.model_copy(update={"domain": None})
                })
                changes.append("intent_extractor.domain = none")
            else:
                _assert_domain_exists(domain)
                pa = pa.model_copy(update={
                    "intent_extractor": pa.intent_extractor.model_copy(update={"domain": domain})
                })
                changes.append(f"intent_extractor.domain = {domain}")

        if budget_tokens is not None:
            pa = pa.model_copy(update={"budget": pa.budget.model_copy(update={"tokens_max": budget_tokens})})
            changes.append(f"budget.tokens_max = {budget_tokens}")

        if budget_cost is not None:
            pa = pa.model_copy(update={"budget": pa.budget.model_copy(update={"cost_max_usd": budget_cost})})
            changes.append(f"budget.cost_max_usd = {budget_cost}")

        if budget_calls is not None:
            pa = pa.model_copy(update={"budget": pa.budget.model_copy(update={"calls_max": budget_calls})})
            changes.append(f"budget.calls_max = {budget_calls}")

        if budget_timeout is not None:
            pa = pa.model_copy(update={"budget": pa.budget.model_copy(update={"timeout_ms": budget_timeout})})
            changes.append(f"budget.timeout_ms = {budget_timeout}")

        if conv_messages is not None:
            pa = pa.model_copy(update={"conversation": pa.conversation.model_copy(update={"max_messages": conv_messages})})
            changes.append(f"conversation.max_messages = {conv_messages}")

        if conv_tokens is not None:
            pa = pa.model_copy(update={"conversation": pa.conversation.model_copy(update={"max_tokens": conv_tokens})})
            changes.append(f"conversation.max_tokens = {conv_tokens}")

        if conv_mode:
            valid = {"messages", "tokens", "both"}
            if conv_mode not in valid:
                fatal(
                    f"invalid window mode '{conv_mode}'",
                    hint("valid values", ", ".join(sorted(valid))),
                )
            pa = pa.model_copy(update={"conversation": pa.conversation.model_copy(update={"window_mode": conv_mode})})
            changes.append(f"conversation.window_mode = {conv_mode}")

        if cache:
            enabled = cache.lower() in ("true", "1", "yes")
            pa = pa.model_copy(update={"cache": pa.cache.model_copy(update={"enabled": enabled})})
            changes.append(f"cache.enabled = {enabled}")

        if cache_max_size is not None:
            pa = pa.model_copy(update={"cache": pa.cache.model_copy(update={"max_size": cache_max_size})})
            changes.append(f"cache.max_size = {cache_max_size}")

        if gateway_add:
            if gateway_add not in pa.gateways:
                pa = pa.model_copy(update={"gateways": pa.gateways + [gateway_add]})
                changes.append(f"gateways +{gateway_add}")
            else:
                changes.append(f"gateways {gateway_add} (already present)")

        if gateway_remove:
            if gateway_remove in pa.gateways:
                pa = pa.model_copy(update={"gateways": [g for g in pa.gateways if g != gateway_remove]})
                changes.append(f"gateways -{gateway_remove}")
            else:
                changes.append(f"gateways {gateway_remove} (not found)")

        return cfg.model_copy(update={"pa": pa})

    patch_config(_apply)

    # ── output ────────────────────────────────────────────────────────
    console.print()
    for change in changes:
        console.print(f"  {ok(f'[dim]{change}[/dim]')}")

    # nota de restart apenas para campos que afetam o IntentExtractor
    _needs_restart = any(
        k in change for k in ("llm.", "domain", "default_reasoning")
        for change in changes
    )
    if _needs_restart:
        console.print()
        console.print(info("[dim]NOTE: restart the PA for changes to take effect[/dim]"))
        console.print(info("[dim]  axon pa run --query '...'[/dim]"))
        console.print(info("[dim]  axon pa chat[/dim]"))

    console.print()


# ── show ──────────────────────────────────────────────────────────────────────

def _show() -> None:
    from axon.config import read_config
    cfg = read_config()
    pa  = cfg.pa

    domain_display = (
        f"[cyan]{pa.intent_extractor.domain}[/cyan]"
        if pa.intent_extractor.domain
        else "[dim]none (base only)[/dim]"
    )

    console.print()
    console.print("  [bold]PA configuration[/bold]")
    console.print()

    console.print("  [dim]─── model ──────────────────────────────────────[/dim]")
    console.print(info(f"llm.model        [cyan]{pa.llm.model}[/cyan]"))
    console.print(info(f"llm.temperature  [cyan]{pa.llm.temperature}[/cyan]"))
    console.print(info(f"llm.host         [dim]{pa.llm.host}[/dim]"))
    console.print(info(f"llm.timeout      [dim]{pa.llm.timeout}s[/dim]"))
    console.print()

    console.print("  [dim]─── reasoning ─────────────────────────────────[/dim]")
    console.print(info(f"default_reasoning  [cyan]{pa.default_reasoning}[/cyan]"))
    console.print(info(f"max_iterations     [cyan]{pa.max_iterations}[/cyan]"))
    console.print()

    console.print("  [dim]─── domain ────────────────────────────────────[/dim]")
    console.print(info(f"intent_extractor.domain  {domain_display}"))
    console.print()

    console.print("  [dim]─── budget ────────────────────────────────────[/dim]")
    console.print(info(f"budget.tokens_max   [cyan]{pa.budget.tokens_max:,}[/cyan]"))
    console.print(info(f"budget.cost_max_usd [cyan]${pa.budget.cost_max_usd:.2f}[/cyan]"))
    console.print(info(f"budget.calls_max    [cyan]{pa.budget.calls_max}[/cyan]"))
    console.print(info(f"budget.timeout_ms   [cyan]{pa.budget.timeout_ms:,.0f}ms[/cyan]"))
    console.print()

    max_tokens_display = (
        f"[cyan]{pa.conversation.max_tokens:,}[/cyan]"
        if pa.conversation.max_tokens is not None
        else "[dim]none[/dim]"
    )

    console.print("  [dim]─── conversa ──────────────────────────────────[/dim]")
    console.print(info(f"conversation.max_messages  [cyan]{pa.conversation.max_messages}[/cyan]"))
    console.print(info(f"conversation.max_tokens    {max_tokens_display}"))
    console.print(info(f"conversation.window_mode   [cyan]{pa.conversation.window_mode}[/cyan]"))
    console.print()

    console.print("  [dim]─── cache ─────────────────────────────────────[/dim]")
    console.print(info(f"cache.enabled   [cyan]{pa.cache.enabled}[/cyan]"))
    console.print(info(f"cache.max_size  [cyan]{pa.cache.max_size}[/cyan]"))
    console.print()

    console.print("  [dim]─── gateways ──────────────────────────────────[/dim]")
    if pa.gateways:
        for gw in pa.gateways:
            console.print(info(f"[dim]{gw}[/dim]"))
    else:
        console.print(info("[dim](none)[/dim]"))
    console.print()


# ── helpers ───────────────────────────────────────────────────────────────────

def _assert_domain_exists(domain: str) -> None:
    candidates = [
        Path("src/axon/pa/skills/domains") / f"{domain}.md",
        Path("axon/pa/skills/domains")     / f"{domain}.md",
    ]
    if not any(p.exists() for p in candidates):
        fatal(
            f"domain skill '{domain}' not found",
            hint("expected at", f"src/axon/pa/skills/domains/{domain}.md", style="dim"),
            hint("create it", f"axon pa skills new --domain {domain}"),
        )