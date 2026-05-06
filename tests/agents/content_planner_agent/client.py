import asyncio
import uuid
import httpx
from a2a.client import create_client, ClientConfig
from a2a.types import SendMessageRequest, Message, Part, Role
from a2a.helpers import get_artifact_text, get_message_text

AGENT_URL = "http://localhost:4115"
TIMEOUT = httpx.Timeout(300.0)  # 5 minutos — modelos locais podem ser lentos


def build_request(text: str, context_id: str | None = None) -> SendMessageRequest:
    return SendMessageRequest(
        message=Message(
            role=Role.ROLE_USER,
            parts=[Part(text=text)],
            message_id=str(uuid.uuid4()),
            context_id=context_id or str(uuid.uuid4()),
        )
    )


def extract_response(stream_response) -> str:
    if stream_response.HasField("task"):
        task = stream_response.task
        parts = []
        for artifact in task.artifacts:
            text = get_artifact_text(artifact)
            if text:
                parts.append(text)
        return "\n".join(parts)

    if stream_response.HasField("artifact_update"):
        return get_artifact_text(stream_response.artifact_update.artifact)

    if stream_response.HasField("message"):
        return get_message_text(stream_response.message)

    return ""


async def chat():
    print(f"Conectando ao agente em {AGENT_URL}...")
    client = await create_client(
        AGENT_URL,
        client_config=ClientConfig(httpx_client=httpx.AsyncClient(timeout=TIMEOUT)),
        relative_card_path="/.well-known/agent-card.json",
    )
    print("Conectado. Digite sua mensagem (Ctrl+C para sair).\n")

    context_id = str(uuid.uuid4())

    while True:
        try:
            text = input("Você: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nEncerrando.")
            break

        if not text:
            continue

        request = build_request(text, context_id=context_id)

        print("Agente: ", end="", flush=True)
        async for response in client.send_message(request):
            output = extract_response(response)
            if output:
                print(output)
                break
        else:
            print("(sem resposta)")


asyncio.run(chat())
