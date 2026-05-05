from __future__ import annotations
 
import typer
 
from axon.cli import init, token

app = typer.Typer(
    name="axon",
    help="AXON — Distributed Agent Workflow Network CLI",
    add_completion=False,
    no_args_is_help=True,
)
 
app.add_typer(init.app, name="init", invoke_without_command=True)
app.add_typer(token.app, name="token", invoke_without_command=True)
 
if __name__ == "__main__":
    app()