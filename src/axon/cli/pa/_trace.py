"""
cli/pa/_trace.py 
imprime ExtractionTrace no terminal (modo --verbose)

ajuda a debug como o intentExtraction está funcionando por baixo dos panos 
"""
from __future__ import annotations

from axon.cli._print import console, divider


_SECTION_EMPTY = {
    "history":   "No previous conversation.",
    "memory":    "No user memory available.",
    "resources": "No resources available.",
}


def print_trace(trace: "ExtractionTrace") -> None:  # type: ignore[name-defined]
    """Imprime o contexto injetado e o resultado do intent extractor."""
    from axon.pa.models import Objective

    console.print()
    console.print("  [dim]─── context injected ─────────────────────────[/dim]")
    console.print()

    # history
    h = trace.history_str or _SECTION_EMPTY["history"]
    console.print("  [dim]history[/dim]")
    for line in h.splitlines():
        console.print(f"  [dim]│  {line}[/dim]")
    console.print()

    # memory
    m = trace.memory_str or _SECTION_EMPTY["memory"]
    console.print("  [dim]memory[/dim]")
    for line in m.splitlines():
        console.print(f"  [dim]│  {line}[/dim]")
    console.print()

    # resources
    r = trace.resources_str or _SECTION_EMPTY["resources"]
    console.print("  [dim]resources[/dim]")
    for line in r.splitlines():
        console.print(f"  [dim]│  {line}[/dim]")
    console.print()

    console.print("  [dim]─── objective ─────────────────────────────────[/dim]")
    console.print()

    obj = trace.objective
    if obj.clarification is not None:
        console.print(f"  [dim]status     [yellow]needs clarification[/yellow][/dim]")
        console.print(f"  [dim]goal       {obj.goal or '(unclear)'}[/dim]")
        console.print(f"  [dim]context    {obj.clarification.context}[/dim]")
        for i, q in enumerate(obj.clarification.questions, 1):
            console.print(f"  [dim]question {i}  {q.question}[/dim]")
    else:
        console.print(f"  [dim]status     [green]ready[/green][/dim]")
        console.print(f"  [dim]goal       {obj.goal}[/dim]")
        console.print(f"  [dim]success    {obj.success_definition}[/dim]")
        if obj.extracted_inputs:
            inputs = ", ".join(f"{k}={v}" for k, v in obj.extracted_inputs.items())
            console.print(f"  [dim]inputs     {inputs}[/dim]")
        if obj.capability_hints:
            console.print(f"  [dim]capabilities {', '.join(obj.capability_hints)}[/dim]")
        if obj.assumptions:
            for a in obj.assumptions:
                console.print(f"  [dim]assumption  {a}[/dim]")

    console.print()