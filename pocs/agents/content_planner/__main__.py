import logging
import os

import click
import uvicorn

# from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentExtension,
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
)
from starlette.applications import Starlette
from content_planner_agent import root_agent as content_planner_agent
from agent_executor import ADKAgentExecutor
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

'''Código original 
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MissingAPIKeyError(Exception):
    """Exception for missing API key."""


@click.command()
@click.option("--host", default="localhost")
@click.option("--port", default=10001)
def main(host, port):

    # Agent card (metadata)
    agent_card = AgentCard(
        name='Content Planner Agent',
        description=content_planner_agent.description,
        url=f'http://{host}:{port}',
        version="1.0.0",
        defaultInputModes=["text", "text/plain"],
        defaultOutputModes=["text", "text/plain"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="content_planner",
                name="Creates outlines for content",
                description="Creates outlines for content given a high-level description of the content",
                tags=["plan", "outline","content-creation"],
                examples=[
                    "Create an outline for a short, upbeat, and encouraging X post about learning Java",
                ],
            )
        ],
    )

    request_handler = DefaultRequestHandler(
        agent_executor=ADKAgentExecutor(
            agent=content_planner_agent,
        ),
        task_store=InMemoryTaskStore(),
    )

    server = A2AStarletteApplication(
        agent_card=agent_card, http_handler=request_handler
    )

    uvicorn.run(server.build(), host=host, port=port)
'''

def main():

    axon_extension = AgentExtension(
    uri="https://axon-framework.dev/extensions/registry/v1",
    description="Axon registry token for Gateway registration",
)
    axon_extension.params["token"] = os.getenv("AXON_TOKEN")
    axon_extension.params["registry_id"]     = "local"
    axon_extension.params["protocol_version"] = "0.1"

    skill = AgentSkill(
        id="content_planner",
        name="Creates outlines for content",
        description="Creates outlines for content given a high-level description of the content",
        tags=["plan", "outline", "content-creation"],
        examples=[
            "Create an outline for a short, upbeat, and encouraging X post about learning Java",
        ],
    )

    host = "localhost"
    port = 4115

    public_agent_card = AgentCard(
        name="Content Planner Agent",
        description=content_planner_agent.description,
        version="1.0.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=True, extensions=[axon_extension]),
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                url=f"http://{host}:{port}",
            )
        ],
        skills=[skill],
    )

    request_handler = DefaultRequestHandler(
        agent_executor=ADKAgentExecutor(
            agent=content_planner_agent,
        ),
        task_store=InMemoryTaskStore(),
        agent_card=public_agent_card,
    )

    routes = []
    routes.extend(create_agent_card_routes(public_agent_card))
    routes.extend(create_jsonrpc_routes(request_handler, "/"))

    app = Starlette(routes=routes)

    logger.info(f"Starting Content Planner Agent on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()