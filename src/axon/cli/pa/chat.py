from __future__ import annotations

import typer

from axon.cli._print import console, ok, info, warn, fatal, divider, step

app = typer.Typer(help="Chat interativo com o Principal Agent.")

_MAX_CLARIFICATION_ROUNDS = 3


@app.callback(invoke_without_command=True)
def chat(
    session_id: str | None = typer.Option(None, "--session", "-s", help="Session ID to resume."),
    lang:       str | None = typer.Option(None, "--lang", "-l", help="Respond in this language."),
) -> None:
    """Inicia uma sessão interativa com o Principal Agent."""
    from axon.config import read_config, paths
    from axon.pa.agent import PrincipalAgent

    try:
        config = read_config()
    except FileNotFoundError:
        fatal('axon.config.json not found. Run "axon init" first.')

    p = paths()

    agent = PrincipalAgent(
        config=config.pa,
        sessions_dir=p.pa_sessions,
        memory_path=p.pa_memory_bank,
        session_id=session_id,
    )

    console.print()
    console.print("  [bold]Axon[/bold] [dim]PA chat[/dim]  [dim]ctrl+c to exit[/dim]")
    console.print(info(f"[dim]session: {agent.session_id}[/dim]"))
    if lang:
        console.print(info(f"[dim]lang:    {lang}[/dim]"))
    console.print()

    # ── query inicial ──────────────────────────────────────────────────
    raw_query = typer.prompt("  you")
    console.print()

    query = _translate(raw_query, "English", agent) if lang else raw_query

    # registra a query inicial no histórico
    agent._history.add_message("user", query, llm_client=agent._llm_client)

    for round_n in range(1, _MAX_CLARIFICATION_ROUNDS + 1):

        console.print(f"  {step('extracting intent...')}")
        console.print(divider())

        try:
            intent = agent.extract_intent(query)
        except Exception as exc:
            fatal(f"Agent error: {exc}")

        # ── Objective → encerra ────────────────────────────────────────
        if intent.clarification is None:
            response_en = agent._format_objective(intent)
            agent._history.add_message("assistant", response_en, llm_client=agent._llm_client)
            agent._persist_session()

            response = _translate(response_en, lang, agent) if lang else response_en

            console.print()
            console.print(f"  {ok('[bold]objective identified[/bold]')}")
            console.print()
            for line in response.splitlines():
                console.print(f"  [dim]│[/dim]  {line}")
            console.print(info(f"[dim]session: {agent.session_id}[/dim]"))
            console.print()
            return

        # ── ClarificationNeeded → exibe perguntas ──────────────────────
        if round_n == _MAX_CLARIFICATION_ROUNDS:
            console.print()
            console.print(warn("max clarification rounds reached — try a more specific query."))
            console.print()
            raise typer.Exit(1)

        clar = intent.clarification
        context_display = _translate(clar.context, lang, agent) if lang else clar.context
        console.print()
        console.print(f"  [dim]{context_display}[/dim]")
        console.print()

        for i, q in enumerate(clar.questions, 1):
            question_display = _translate(q.question, lang, agent) if lang else q.question
            console.print(f"  [cyan]{i}.[/cyan] {question_display}")
            if q.options:
                console.print(f"     [dim]{'  /  '.join(q.options)}[/dim]")
        console.print()

        raw_answer = typer.prompt("  you")
        console.print()

        answer = _translate(raw_answer, "English", agent) if lang else raw_answer

        # registra a pergunta do assistente e a resposta do usuário no histórico
        # assim o extractor vê o contexto completo na próxima rodada
        agent._history.add_message("assistant", clar.context, llm_client=agent._llm_client)
        agent._history.add_message("user", answer, llm_client=agent._llm_client)

        # próxima rodada usa só a nova resposta como query —
        # o histórico já carrega o contexto completo
        query = answer


def _translate(text: str, target: str | None, agent) -> str:
    if not target or target == "English":
        return text
    try:
        return agent._llm_client.generate(
            f"Translate the following text to {target}. "
            f"Return only the translated text, no explanations.\n\n{text}",
            temperature=0.0,
            format=None,
        ).strip()
    except Exception:
        return text