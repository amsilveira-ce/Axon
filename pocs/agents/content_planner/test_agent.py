import asyncio
from uuid import uuid4

import httpx
from a2a.client import ClientConfig, create_client
from a2a.types import Message, Part, Role, SendMessageRequest

BASE_URL = "http://localhost:4115"
REQUEST_TIMEOUT = 120.0


def _collect_text(parts) -> list[str]:
    return [p.text for p in parts or [] if p.text]


async def ask(question: str) -> None:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as http:
        client = await create_client(
            BASE_URL,
            ClientConfig(streaming=False, httpx_client=http),
        )

        request = SendMessageRequest(
            message=Message(
                role=Role.ROLE_USER,
                parts=[Part(text=question)],
                message_id=uuid4().hex,
                context_id=uuid4().hex,
            )
        )

        texts: list[str] = []
        async for response in client.send_message(request):
            kind = response.WhichOneof("payload") if hasattr(response, "WhichOneof") else None
            if kind == "message":
                texts.extend(_collect_text(response.message.parts))
            elif kind == "task":
                task = response.task
                texts.extend(_collect_text(task.status.message.parts))
                for artifact in task.artifacts:
                    texts.extend(_collect_text(artifact.parts))
                for hist in task.history:
                    if hist.role == Role.ROLE_AGENT:
                        texts.extend(_collect_text(hist.parts))
            elif kind == "status_update":
                texts.extend(_collect_text(response.status_update.status.message.parts))
            elif kind == "artifact_update":
                texts.extend(_collect_text(response.artifact_update.artifact.parts))

    print("\n--- Response ---\n")
    if texts:
        for text in texts:
            print(text)
    else:
        print("(no text parts found)")


def main() -> None:
    question = input("Your question: ").strip()
    if not question:
        print("Empty question, exiting.")
        return
    asyncio.run(ask(question))


if __name__ == "__main__":
    main()
