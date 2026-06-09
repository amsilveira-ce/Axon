"""Interactive chat session with the Principal Agent.

Runs the full six-stage pipeline and displays each stage's result as it
completes — intent extraction, decomposition, resource resolution, and
execution — before printing the synthesized response.
"""

from __future__ import annotations

import time

import typer
from rich.markup import escape

from axon.cli._print import console, warn, fatal, setup_logging

app = typer.Typer(help="Interactive chat session with the Principal Agent.")

_MAX_CLARIFICATION_ROUNDS = 3


@app.callback(invoke_without_command=True)
def chat(
    session_id: str | None = typer.Option(None, "--session", "-s", help="Session ID to resume."),
    lang: str | None = typer.Option(None, "--lang", "-l", help="Respond in this language."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show extra pipeline detail."),
) -> None:
    """Start an interactive session with the Principal Agent."""
    setup_logging()

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

    with agent:
        _print_header(agent, lang, verbose)

        while True:
            try:
                raw_query = typer.prompt("  you")
            except (KeyboardInterrupt, EOFError):
                console.print()
                console.print(f"  [dim]goodbye  ·  session {agent.session_id}[/dim]")
                console.print()
                break

            if not raw_query.strip():
                continue

            console.print()
            query = _translate(raw_query, "English", agent) if lang else raw_query
            agent._history.add_message("user", query, llm_client=agent._llm_client)

            intent = _clarify(agent, query, lang, verbose)
            if intent is None:
                continue

            _run_pipeline(agent, query, intent, lang, verbose)


# ── clarification loop ────────────────────────────────────────────────────────


def _clarify(agent, query: str, lang, verbose):
    """Run intent extraction with clarification rounds.

    Returns an ``Objective`` when the intent is clear, or ``None`` when the
    maximum number of rounds is reached.
    """
    for round_n in range(1, _MAX_CLARIFICATION_ROUNDS + 1):
        with console.status("  [dim]extracting intent...[/dim]", spinner="dots"):
            try:
                intent = agent.extract_intent(query)
            except Exception as exc:
                fatal(f"Intent extraction failed: {escape(str(exc))}")

        if verbose and agent.last_trace:
            from axon.cli.pa._trace import print_trace
            print_trace(agent.last_trace)

        if intent.clarification is None:
            return intent

        if round_n == _MAX_CLARIFICATION_ROUNDS:
            console.print(f"  {warn('max clarification rounds — try a more specific query.')}")
            console.print()
            return None

        clar = intent.clarification
        ctx = _translate(clar.context, lang, agent) if lang else clar.context
        console.print(f"  [dim]{escape(ctx)}[/dim]")
        console.print()

        for i, q in enumerate(clar.questions, 1):
            question = _translate(q.question, lang, agent) if lang else q.question
            console.print(f"  [cyan]{i}.[/cyan] {escape(question)}")
            if q.options:
                console.print(f"     [dim]{escape('  /  '.join(q.options))}[/dim]")
        console.print()

        raw_answer = typer.prompt("  you")
        console.print()

        answer = _translate(raw_answer, "English", agent) if lang else raw_answer
        agent._history.add_message("assistant", clar.context, llm_client=agent._llm_client)
        agent._history.add_message("user", answer, llm_client=agent._llm_client)
        query = answer

    return None


# ── pipeline ──────────────────────────────────────────────────────────────────


def _run_pipeline(agent, raw_query: str, intent, lang, verbose) -> None:
    """Run stages 2–6 and print each stage's result as it completes."""
    from axon.pa.executor import _short
    from axon.pa.models import AgentState
    from axon.pa.planner import PlanError
    from axon.pa.resolver import ResolverClarification, ResolverError

    state = AgentState(
        raw_query=raw_query,
        objective=intent,
        session_id=agent.session_id,
    )
    state.resource_pool = agent._local_pool.tools + agent._resource_cache.all()
    agent.last_state = state

    console.print()
    console.rule("[dim]pipeline[/dim]", style="dim")
    console.print()

    # ── [1] intent extractor — already done, display the result ──────────
    _stage(1, "intent extractor")
    _print_kv("goal", escape(intent.goal))
    if intent.success_definition:
        _print_kv("success", escape(intent.success_definition))
    for c in intent.constraints:
        _print_kv("constraint", f"[dim][{c.type}][/dim] {escape(c.value)}")
    for k, v in (intent.extracted_inputs or {}).items():
        _print_kv("input", f"{escape(k)} = {escape(str(v))}")
    console.print()

    # ── [2] decomposer + planner ──────────────────────────────────────────
    _stage(2, "decomposer + planner")
    elapsed, exc = _timed(
        lambda: (agent._decomposer.decompose(state), agent._planner.plan(state)),
        "  [dim]planning...[/dim]",
    )
    n_subtasks = len(state.plan.subtasks)
    if exc is None and n_subtasks:
        console.print(f"  [green]✓[/green]  [dim]{n_subtasks} subtask(s)   {elapsed}ms[/dim]")
        for i, s in enumerate(state.plan.subtasks):
            branch = "└─" if i == n_subtasks - 1 else "├─"
            deps = f"  [dim]← {', '.join(s.depends_on)}[/dim]" if s.depends_on else ""
            optional = "  [dim](optional)[/dim]" if s.is_optional else ""
            console.print(
                f"    [dim]{branch}[/dim] [bold]{s.id}[/bold]  {escape(s.description)}"
                f"  [dim]{s.capability_required}[/dim]{deps}{optional}"
            )
    else:
        reason = escape(str(exc)) if exc else "no subtasks produced"
        console.print(f"  [red]✗[/red]  [dim]failed: {reason}[/dim]")
        return _end(agent, state, None, lang)
    console.print()

    # ── [3] resolver ──────────────────────────────────────────────────────
    _stage(3, "resolver")
    elapsed, exc = _timed(
        lambda: agent._resolver.resolve(state),
        "  [dim]resolving resources...[/dim]",
    )
    n_assigned = len(state.resource_assignments)
    if exc is None:
        console.print(
            f"  [green]✓[/green]  [dim]{n_assigned}/{n_subtasks} assigned   {elapsed}ms[/dim]"
        )
        for sid, a in state.resource_assignments.items():
            via = f"GA {escape(a.ga_url)}" if a.ga_url else "local pool"
            score_str = f"  score={a.match_score:.2f}" if a.ga_url else ""
            console.print(
                f"    [dim][{sid}][/dim]  [bold]{escape(a.manifest.name)}[/bold]"
                f"  [dim]{via}{score_str}[/dim]"
            )
            if verbose:
                if a.ga_url:
                    total = agent._affinity.total_queries(a.capability)
                    ucb = agent._affinity.ucb_score(a.ga_url, a.capability, total)
                    ucb_str = "∞" if ucb == float("inf") else f"{ucb:.3f}"
                    console.print(
                        f"      [dim]match={a.match_score:.2f}"
                        f"  latency={a.latency_ms:.0f}ms"
                        f"  ucb={ucb_str}"
                        f"  n={agent._affinity._entry(a.ga_url, a.capability).query_count}[/dim]"
                    )
                else:
                    m = a.manifest
                    console.print(
                        f"      [dim]local selection"
                        f"  success={m.success_count}"
                        f"  failure={m.failure_count}[/dim]"
                    )
    elif isinstance(exc, ResolverClarification):
        clar = exc.clarification
        ctx = _translate(clar.context, lang, agent) if lang else clar.context
        console.print(f"  [yellow]▲[/yellow]  needs clarification")
        console.print(f"    [dim]{escape(ctx)}[/dim]")
        for i, q in enumerate(clar.questions, 1):
            console.print(f"    [cyan]{i}.[/cyan] {escape(q.question)}")
        return _end(agent, state, None, lang)
    else:
        console.print(f"  [red]✗[/red]  [dim]failed: {escape(str(exc))}[/dim]")
        return _end(agent, state, None, lang)
    console.print()

    # ── [4] executor ──────────────────────────────────────────────────────
    _stage(4, "executor")
    elapsed, exc = _timed(
        lambda: agent._executor.execute(state),
        "  [dim]executing...[/dim]",
    )
    n_facts = len(state.facts)
    n_fail = len(state.failures)

    if exc is None:
        console.print(
            f"  [green]✓[/green]  [dim]{n_facts} fact(s) · {n_fail} failure(s)   {elapsed}ms[/dim]"
        )
    else:
        console.print(
            f"  [yellow]▲[/yellow]  [dim]interrupted   {elapsed}ms   {escape(str(exc))}[/dim]"
        )
    for f in state.facts:
        console.print(
            f"    [green]✓[/green] [dim][{f.subtask_id}][/dim]  [bold]{escape(f.tool)}[/bold]"
            f"  [dim]{escape(str(_short(f.output)))}[/dim]"
        )
    for fail in state.failures:
        console.print(
            f"    [red]✗[/red] [dim][{fail.subtask_id}][/dim]"
            f"  [bold]{escape(fail.tool or '—')}[/bold]"
            f"  [dim]{escape(fail.reason)}[/dim]"
        )

    agent._persist_trace(state)

    if verbose:
        _print_affinity(agent)

    # ── synthesize response ───────────────────────────────────────────────
    try:
        response_en = agent._synthesizer.synthesize(state, agent._history)
        if not response_en:
            response_en = agent._format_result(intent, state)
    except Exception:
        response_en = agent._format_result(intent, state)

    _end(agent, state, response_en, lang)


# ── display helpers ───────────────────────────────────────────────────────────


def _stage(n: int, label: str) -> None:
    """Print a numbered stage header."""
    console.print(f"  [bold dim][{n}][/bold dim] [bold]{label}[/bold]")


def _print_kv(label: str, value: str, indent: int = 6) -> None:
    """Print a key-value row with a fixed-width dim label column."""
    console.print(f"{'  ' * (indent // 2)}[dim]{label:<12}[/dim]  {value}")


def _timed(fn, status_msg: str) -> tuple[int, Exception | None]:
    """Run *fn* under a spinner. Returns ``(elapsed_ms, exception_or_None)``."""
    t0 = time.monotonic()
    with console.status(status_msg, spinner="dots"):
        try:
            fn()
            return int((time.monotonic() - t0) * 1000), None
        except Exception as exc:
            return int((time.monotonic() - t0) * 1000), exc


def _print_affinity(agent) -> None:
    """Print the UCB1 affinity table — shown in verbose mode after executor."""
    import math

    aff = getattr(agent, "_affinity", None)
    table = getattr(aff, "_table", {}) if aff else {}

    console.print()
    console.print("  [bold dim][affinity][/bold dim]")

    if not table:
        console.print("  [dim]  local pool only — no gateway queries, no UCB updates[/dim]")
        return

    for ga_url, caps in table.items():
        console.print(f"  [dim]  {escape(ga_url)}[/dim]")
        for cap, entry in caps.items():
            total = aff.total_queries(cap)
            ucb = aff.ucb_score(ga_url, cap, total)
            ucb_str = "∞" if ucb == float("inf") else f"{ucb:.3f}"
            console.print(
                f"    [dim]{cap:<22}"
                f"  n={entry.query_count}"
                f"  reward={entry.reward_mean:.3f}"
                f"  ucb={ucb_str}[/dim]"
            )


def _end(agent, state, response_en, lang) -> None:
    """Translate, print the final response block, persist session, and print footer."""
    if response_en:
        response = _translate(response_en, lang, agent) if lang else response_en
        agent._history.add_message("assistant", response_en, llm_client=agent._llm_client)
        agent._persist_session()

        console.print()
        console.rule("[dim]response[/dim]", style="dim")
        console.print()
        lines = response.splitlines()
        for i, line in enumerate(lines):
            prefix = "  [bold dim]axon[/bold dim]  " if i == 0 else "        "
            console.print(f"{prefix}[dim]│[/dim]  {escape(line)}")
        console.print()
    else:
        agent._persist_session()

    console.rule(style="dim")
    console.print(f"  [dim]session  {state.session_id}[/dim]")
    console.print()


def _print_header(agent, lang, verbose) -> None:
    console.print()
    console.print("  [bold]Axon[/bold]  [dim]PA  ·  ctrl+c to exit[/dim]")
    console.print(f"  [dim]session  {agent.session_id}[/dim]")
    if lang:
        console.print(f"  [dim]lang     {lang}[/dim]")
    if verbose:
        console.print(f"  [dim]verbose  on[/dim]")
    console.print()


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
