from __future__ import annotations

import logging

import typer

from axon.cli._print import console, ok, info, warn, fatal, divider, step, setup_logging

app = typer.Typer(help="Interactive chat with the Principal Agent.")

logger = logging.getLogger(__name__)

_MAX_CLARIFICATION_ROUNDS = 3


@app.callback(invoke_without_command=True)
def chat(
    session_id: str | None = typer.Option(None, "--session", "-s", help="Session ID to resume. Default: new session."),
    lang:       str | None = typer.Option(None, "--lang", "-l", help="Respond in this language. Default: English."),
    verbose:    bool       = typer.Option(False, "--verbose", "-v", help="Show detailed logs of each step."),
) -> None:
    """
    Start an interactive session with the Principal Agent.

    The agent extracts the intent from the query. If it needs clarification,
    it shows the questions and waits for an answer — up to 3 rounds.
    As soon as an Objective is produced, it shows the goal and exits.
    """
    setup_logging(verbose)

    from axon.config import read_config, paths
    from axon.pa.agent import PrincipalAgent

    logger.info("[PA chat] starting — session=%s lang=%s",
                session_id or "new", lang or "English")

    try:
        config = read_config()
    except FileNotFoundError:
        logger.info("[PA chat] axon.config.json not found in this directory")
        fatal('axon.config.json not found. Run "axon init" first.')

    p = paths()
    logger.info("[PA chat] config loaded — model=%s", config.pa.llm.model)

    agent = PrincipalAgent(
        config=config.pa,
        sessions_dir=p.pa_sessions,
        memory_path=p.pa_memory_bank,
        session_id=session_id,
    )
    logger.info("[PA chat] agent ready — session=%s", agent.session_id)

    console.print()
    console.print("  [bold]Axon[/bold] [dim]PA chat[/dim]  [dim]ctrl+c to exit[/dim]")
    console.print(info(f"[dim]session: {agent.session_id}[/dim]"))
    if lang:
        console.print(info(f"[dim]lang:    {lang}[/dim]"))
    console.print()

    # ── initial query ──────────────────────────────────────────────────
    raw_query = typer.prompt("  you")
    console.print()
    logger.info("[PA chat] query received (%d chars)", len(raw_query))

    # translate to English if needed
    query = _translate(raw_query, "English", agent) if lang else raw_query

    context = ""   # accumulates clarification answers across rounds

    for round_n in range(1, _MAX_CLARIFICATION_ROUNDS + 1):
        full_query = f"{query}\n\n{context}".strip() if context else query

        logger.info("[PA chat] round %d/%d — extracting intent",
                    round_n, _MAX_CLARIFICATION_ROUNDS)
        console.print(f"  {step('extracting intent...')}")
        console.print(divider())

        try:
            intent = agent.extract_intent(full_query)
        except Exception as exc:
            logger.info("[PA chat] intent extraction failed", exc_info=True)
            fatal(f"Agent error: {exc}")

        # ── Objective → finish ─────────────────────────────────────────
        if intent.clarification is None:
            logger.info("[PA chat] objective identified — session=%s", agent.session_id)
            response_en = agent._format_objective(intent)

            # record in history
            agent._history.add_message("user",      full_query,   summarizer=agent._summarizer)
            agent._history.add_message("assistant", response_en,  summarizer=agent._summarizer)
            agent._persist_session()
            logger.info("[PA chat] session persisted — session=%s", agent.session_id)

            # translate response if needed
            response = _translate(response_en, lang, agent) if lang else response_en

            console.print()
            console.print(f"  {ok('[bold]objective identified[/bold]')}")
            console.print()
            for line in response.splitlines():
                console.print(f"  [dim]│[/dim]  {line}")
            console.print(info(f"[dim]session: {agent.session_id}[/dim]"))
            console.print()
            return

        # ── ClarificationNeeded → show questions ───────────────────────
        if round_n == _MAX_CLARIFICATION_ROUNDS:
            logger.info("[PA chat] max clarification rounds (%d) reached",
                        _MAX_CLARIFICATION_ROUNDS)
            console.print()
            console.print(warn("max clarification rounds reached — try a more specific query."))
            console.print()
            raise typer.Exit(1)

        clar = intent.clarification
        logger.info("[PA chat] clarification needed — round %d, %d question(s)",
                    round_n, len(clar.questions))
        context_display = _translate(clar.context, lang, agent) if lang else clar.context
        console.print()
        console.print(f"  [dim]{context_display}[/dim]")
        console.print()

        for i, q in enumerate(clar.questions, 1):
            question_display = _translate(q.question, lang, agent) if lang else q.question
            console.print(f"  [cyan]{i}.[/cyan] {question_display}")
            if q.options:
                opts = "  /  ".join(q.options)
                console.print(f"     [dim]{opts}[/dim]")
        console.print()

        raw_answer = typer.prompt("  you")
        console.print()

        # translate the user's answer back to English
        answer = _translate(raw_answer, "English", agent) if lang else raw_answer
        context = f"{context}\nUser clarification (round {round_n}): {answer}".strip()


def _translate(text: str, target: str | None, agent) -> str:
    if not target or target == "English":
        return text
    logger.info("[PA chat] translating text → %s", target)
    try:
        translated = agent._llm_client.generate(
            f"Translate the following text to {target}. "
            f"Return only the translated text, no explanations.\n\n{text}",
            temperature=0.0,
            format=None,
        ).strip()
        logger.debug("[PA chat] translation → %s succeeded", target)
        return translated
    except Exception as exc:
        logger.info("[PA chat] translation to %s failed: %s — using original text",
                    target, exc)
        return text
