from __future__ import annotations

import logging

import typer

from axon.cli._print import console, ok, fatal, divider, step, info, warn, err, setup_logging

logger = logging.getLogger(__name__)

_EPILOG = (
    "Examples:\n"
    '  axon pa run -q "Create a report about Q3 results"\n'
    '  axon pa run -q "Resumir as vendas do Q3" -l Portuguese'
)

app = typer.Typer(help="Run the Principal Agent.", epilog=_EPILOG)


def _guide_missing_query() -> None:
    """Print a friendly guide when --query is missing, then exit."""
    logger.info("[PA run] missing required option --query")
    console.print()
    console.print(f"  {err('missing required option [bold]--query[/bold]')}")
    console.print()
    console.print(info("[bold]axon pa run[/bold] sends a one-shot query to the Principal Agent."))
    console.print()
    console.print(info("[cyan]-q[/cyan], [cyan]--query[/cyan]  [dim]TEXT[/dim]  what to ask the agent  [red](required)[/red]"))
    console.print(info("[cyan]-l[/cyan], [cyan]--lang[/cyan]   [dim]TEXT[/dim]  reply in this language — e.g. Portuguese, Spanish"))
    console.print()
    console.print(info('[dim]$[/dim] axon pa run -q "Create a report about Q3 results"'))
    console.print(info('[dim]$[/dim] axon pa run -q "Resumir as vendas do Q3" -l Portuguese'))
    console.print()
    console.print(info("[dim]full help:[/dim]  axon pa run --help"))
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
        False, "--verbose", "-v", help="Show detailed logs of each step."
    ),
) -> None:
    """Send a one-shot query to the Principal Agent and print the response."""
    setup_logging(verbose)

    from axon.config import read_config
    from axon.pa.agent import PrincipalAgent

    logger.info("[PA run] invoked — lang=%s", lang or "English")

    # ── validate the query before anything else ─────────────────────────
    if query is None or not query.strip():
        _guide_missing_query()

    try:
        config = read_config()
    except FileNotFoundError:
        logger.info("[PA run] axon.config.json not found in this directory")
        fatal('axon.config.json not found in this directory — run "axon init" first.')

    logger.info("[PA run] config loaded — model=%s", config.pa.llm.model)

    lang_label = lang or "English (default)"
    console.print()
    console.print(f"  {step(f'query  [dim]{query}[/dim]')}")
    console.print(f"  {step(f'lang   [dim]{lang_label}[/dim]')}")
    console.print(divider())

    console.print(f"  {step('initializing principal agent...')}")
    logger.info("[PA run] initializing principal agent")
    agent = PrincipalAgent(config.pa)

    # translate the query to English if a language was given
    query_en = query
    if lang:
        console.print(f"  {step(f'translating query → English...')}")
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
            fatal(f"Translation error (query → English): {exc}")

    console.print(f"  {step('running principal agent...')}")
    logger.info("[PA run] running principal agent")
    try:
        response_en = agent.run(query_en)
    except Exception as exc:
        logger.info("[PA run] agent run failed", exc_info=True)
        fatal(f"Agent error while processing the query: {exc}")

    logger.info("[PA run] agent run finished — response length %d chars", len(response_en))

    # translate the response back if a language was given
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
            logger.info("[PA run] translation to %s failed: %s — showing English response",
                        lang, exc)
            console.print(f"  {warn(f'translation to {lang} failed ({exc}) — showing English response')}")
            response = response_en

    console.print()
    console.print(f"  {ok('[bold]response[/bold]')}")
    if lang:
        console.print(info(f"[dim]language: {lang}[/dim]"))
    console.print()
    for line in response.splitlines():
        console.print(f"  [dim]│[/dim]  {line}")
    console.print()
    logger.info("[PA run] completed")
