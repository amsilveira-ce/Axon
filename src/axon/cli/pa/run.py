from __future__ import annotations

import logging

import typer

from axon.cli._print import console, ok, fatal, divider, step, line, warn, err, setup_logging

logger = logging.getLogger(__name__)

_EPILOG = (
    "Examples:\n"
    '  axon pa run -q "Create a report about Q3 results"\n'
    '  axon pa run -q "Resumir as vendas do Q3" -l Portuguese\n'
    '  axon pa run -q "Analyze patient data" -v'
)

app = typer.Typer(epilog=_EPILOG)


def _guide_missing_query() -> None:
    """Print a friendly guide when --query is missing, then exit."""
    logger.info("[PA run] missing required option --query")
    console.print()
    console.print(f"  {err('missing required option [bold]--query[/bold]')}")
    console.print()
    console.print(line("[bold]axon pa run[/bold] sends a one-shot query to the Principal Agent."))
    console.print()
    console.print(line("[cyan]-q[/cyan], [cyan]--query[/cyan]   [dim]TEXT[/dim]  what to ask the agent  [red](required)[/red]"))
    console.print(line("[cyan]-l[/cyan], [cyan]--lang[/cyan]    [dim]TEXT[/dim]  reply in this language — e.g. Portuguese, Spanish"))
    console.print(line("[cyan]-v[/cyan], [cyan]--verbose[/cyan] [dim]FLAG[/dim]  show context injected into the LLM and extraction details"))
    console.print()
    console.print(line('[dim]$[/dim] axon pa run -q "Create a report about Q3 results"'))
    console.print(line('[dim]$[/dim] axon pa run -q "Resumir as vendas do Q3" -l Portuguese'))
    console.print(line('[dim]$[/dim] axon pa run -q "Analyze patient data" -v'))
    console.print()
    console.print(line("[dim]full help:[/dim]  axon pa run --help"))
    console.print()
    raise typer.Exit(2)


@app.callback(invoke_without_command=True)
def run(
    query: str | None = typer.Option(
        None, "--query", "-q", help="Query to send to the Principal Agent (required)"
    ),
    lang: str | None = typer.Option(
        None, "--lang", "-l", help="Respond in this language (e.g. Portuguese, Spanish). Default: English."
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show context injected into the LLM and extraction details."
    ),
) -> None:
    """
    Send a one-shot query to the Principal Agent and print the response.

    Runs the full pipeline: intent extraction → decomposition → planning
    → resource resolution (local tools first, then cached resources,
    then connected Gateway Agents) → execution → response synthesis.

    Use --lang to work in another language: the query is translated to
    English for the pipeline and the response translated back. Use
    --verbose to watch every stage. Each run is persisted as a trace —
    replay it with 'axon pa inspect'.
    """
    setup_logging(verbose)

    from axon.config import read_config, paths
    from axon.pa.agent import PrincipalAgent

    logger.info("[PA run] invoked — lang=%s verbose=%s", lang or "English", verbose)

    # ── validate the query before anything else ─────────────────────────
    if query is None or not query.strip():
        _guide_missing_query()

    try:
        config = read_config()
    except FileNotFoundError:
        logger.info("[PA run] axon.config.json not found in this directory")
        fatal('axon.config.json not found in this directory — run "axon init" first.')

    logger.info("[PA run] config loaded — model=%s", config.pa.llm.model)

    p = paths()
    lang_label = lang or "English (default)"
    console.print()
    console.print(f"  {step(f'query  [dim]{query}[/dim]')}")
    console.print(f"  {step(f'lang   [dim]{lang_label}[/dim]')}")
    console.print(divider())

    console.print(f"  {step('initializing principal agent...')}")
    logger.info("[PA run] initializing principal agent")
    agent = PrincipalAgent(
        config=config.pa,
        sessions_dir=p.pa_sessions,
        memory_path=p.pa_memory_bank,
    )

    with agent:
        # ── translate query → English ────────────────────────────────────────
        query_en = query
        if lang:
            console.print(f"  {step('translating query → English...')}")
            logger.info("[PA run] translating query → English")
            try:
                query_en = agent._llm_client.generate(
                    f"Translate the following text to English. "
                    f"Return only the translated text, no explanations.\n\n{query}",
                    temperature=0.0,
                    format=None,
                ).strip()
            except Exception as exc:
                logger.info("[PA run] translation (query → English) failed", exc_info=True)
                fatal(f"translation error (query → English): {exc}")

        console.print(f"  {step('running principal agent...')}")
        logger.info("[PA run] running principal agent")
        try:
            response_en = agent.run(query_en)
        except Exception as exc:
            logger.info("[PA run] agent run failed", exc_info=True)
            fatal(f"agent error while processing the query: {exc}")

        logger.info("[PA run] agent run finished — response length %d chars", len(response_en))

        # ── verbose: mostra o pipeline completo ─────────────────────────────
        if verbose:
            if agent.last_trace:
                try:
                    from axon.cli.pa._trace import print_verbose
                    print_verbose(agent.last_trace, agent.last_state)
                except Exception as exc:
                    from rich.markup import escape
                    console.print(f"  {warn(f'verbose display error: {escape(str(exc))}')}")
            else:
                console.print(f"  {warn('verbose: no trace available')}")

        # ── translate response → lang ────────────────────────────────────────
        response = response_en
        if lang:
            console.print(f"  {step(f'translating response → {lang}...')}")
            logger.info("[PA run] translating response → %s", lang)
            try:
                response = agent._llm_client.generate(
                    f"Translate the following text to {lang}. "
                    f"Return only the translated text, no explanations.\n\n{response_en}",
                    temperature=0.0,
                    format=None,
                ).strip()
            except Exception as exc:
                logger.info("[PA run] translation to %s failed: %s — showing English response", lang, exc)
                console.print(f"  {warn(f'translation to {lang} failed ({exc}) — showing English response')}")
                response = response_en

        # ── print response — clean block, session as footer ──────────────────
        console.print()
        console.print(f"  {ok('[bold]response[/bold]')}")
        if lang:
            console.print(line(f"[dim]language: {lang}[/dim]"))
        console.print()
        for ln in response.splitlines():
            console.print(line(ln))
        console.print()
        console.print(f"  [dim]session: {agent.session_id}[/dim]")
        console.print()

    logger.info("[PA run] completed")