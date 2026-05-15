from __future__ import annotations

import typer

from axon.cli import init, token, add
from axon.cli.pa import run as pa_run
from axon.cli.pa import chat as pa_chat

app = typer.Typer(
    name="axon",
    help="AXON — Distributed Agent Workflow Network CLI",
    add_completion=False,
    no_args_is_help=True,
)

app.add_typer(init.app,    name="init",  invoke_without_command=True)
app.add_typer(token.app,   name="token", invoke_without_command=True)
app.add_typer(add.app,     name="add",   invoke_without_command=True)

# Principal Agent
pa_app = typer.Typer(help="Principal Agent commands.", no_args_is_help=True)
pa_app.add_typer(pa_run.app,  name="run",  invoke_without_command=True)
pa_app.add_typer(pa_chat.app, name="chat", invoke_without_command=True)
app.add_typer(pa_app, name="pa")

if __name__ == "__main__":
    app()