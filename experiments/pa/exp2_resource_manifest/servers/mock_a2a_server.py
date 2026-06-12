"""
Mock A2A agent server — speaks the REAL A2A protocol.

Built with the same a2a SDK the PA's A2AClient uses, so the wire format
(JSON-RPC message/send, proto types) is correct by construction. The PA
will reach it through manifest.protocol_binding=JSONRPC + endpoint only.
"""
from __future__ import annotations

import threading
from uuid import uuid4

import uvicorn
from starlette.applications import Starlette

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    Message,
    Role,
)


class MockReviewExecutor(AgentExecutor):
    """Answers any task with a canned code-review verdict."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        query = context.get_user_input() or ""
        msg = Message(
            message_id=uuid4().hex,
            context_id=context.context_id or uuid4().hex,
            role=Role.Value("ROLE_AGENT"),
        )
        part      = msg.parts.add()
        part.text = (
            f"Code review complete for: '{query[:60]}'. "
            "No critical issues found. "
            "Suggestion: add type hints to public methods."
        )
        await event_queue.enqueue_event(msg)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        pass


def build_card(port: int) -> AgentCard:
    card = AgentCard(
        name="mock-code-review",
        description="Mock code review agent for testing",
        version="1.0.0",
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", url=f"http://127.0.0.1:{port}/")
        ],
        capabilities=AgentCapabilities(streaming=False),
    )
    return card


def start(port: int = 18081) -> uvicorn.Server:
    """Start the mock A2A server in a daemon thread; returns the server handle."""
    card    = build_card(port)
    handler = DefaultRequestHandler(
        agent_executor=MockReviewExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = create_jsonrpc_routes(handler, rpc_url="/") + create_agent_card_routes(card)
    app    = Starlette(routes=routes)

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    return server
