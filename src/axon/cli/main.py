from __future__ import annotations
 
import typer
 
from axon.cli import init, token, add
from axon.cli.pa  import run     as pa_run
from axon.cli.pa  import chat    as pa_chat
from axon.cli.pa  import skills  as pa_skills
from axon.cli.pa  import config  as pa_config
from axon.cli.pa  import tools   as pa_tools
from axon.cli.pa  import gateway as pa_gateway
from axon.cli.pa  import policy  as pa_policy
from axon.cli.pa  import test    as pa_test
from axon.cli.pa  import inspect as pa_inspect
from axon.cli.ga  import serve   as ga_serve
from axon.cli.ga  import init    as ga_init_cmd
from axon.cli.ga  import use     as ga_use
from axon.cli.ga  import list    as ga_list_cmd
from axon.cli.ga  import resource as ga_resource
from axon.cli.ga  import config  as ga_config
from axon.cli.ga  import context as ga_context
 
app = typer.Typer(
    name="axon",
    help="AXON — Distributed Agent Workflow Network CLI",
    add_completion=False,
    no_args_is_help=True,
)
 
app.add_typer(init.app,       name="init",   invoke_without_command=True)
app.add_typer(token.app,      name="token",  invoke_without_command=True)
app.add_typer(add.app,        name="add",    invoke_without_command=True)
app.add_typer(add.remove_app, name="remove", invoke_without_command=True)
 
# ── Principal Agent ───────────────────────────────────────────────────────────
pa_app = typer.Typer(help="Principal Agent commands.", no_args_is_help=True)
pa_app.add_typer(pa_run.app,     name="run",     invoke_without_command=True)
pa_app.add_typer(pa_chat.app,    name="chat",    invoke_without_command=True)
pa_app.add_typer(pa_skills.app,  name="skills",  invoke_without_command=True)
pa_app.add_typer(pa_config.app,  name="config",  invoke_without_command=True)
pa_app.add_typer(pa_tools.app,   name="tools",   invoke_without_command=True)
pa_app.add_typer(pa_gateway.app, name="gateway", invoke_without_command=True)
pa_app.add_typer(pa_policy.app,  name="policy",  invoke_without_command=True)
pa_app.add_typer(pa_test.app,    name="intent",  invoke_without_command=True)
pa_app.add_typer(pa_inspect.app, name="inspect", invoke_without_command=True)
app.add_typer(pa_app, name="pa")

# ── Gateway Agent ─────────────────────────────────────────────────────────────
ga_app = typer.Typer(help="Gateway Agent commands.", no_args_is_help=True)
ga_app.add_typer(ga_serve.app,    name="serve",    invoke_without_command=True)
ga_app.add_typer(ga_init_cmd.app, name="init",     invoke_without_command=True)
ga_app.add_typer(ga_use.app,      name="use",      invoke_without_command=True)
ga_app.add_typer(ga_list_cmd.app, name="list",     invoke_without_command=True)
ga_app.add_typer(ga_resource.app, name="resource", invoke_without_command=True)
ga_app.add_typer(ga_config.app,   name="config",   invoke_without_command=True)
ga_app.add_typer(ga_context.app,  name="context",  invoke_without_command=True)
app.add_typer(ga_app, name="ga")

if __name__ == "__main__":
    app()