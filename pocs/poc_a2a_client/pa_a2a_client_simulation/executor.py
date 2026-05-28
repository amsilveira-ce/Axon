"""
pa_agent/executor.py

PA executor — constrói um A2AClient a partir de um ResourceManifest.

O ResourceManifest é o único contrato de entrada. Nenhum outro modelo
intermediário é usado.

Fluxo:
  ResourceManifest
    → build_agent_card()      AgentCard mínimo para o ClientFactory
    → build_client_config()   comportamento do client (streaming, push)
    → create_client()         instancia o BaseClient com transporte correto
    → build_request()         monta o SendMessageRequest por chamada
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from uuid import uuid4

from a2a.client import (
    AuthInterceptor,
    ClientConfig,
    CredentialService,
    ClientCallContext,
    create_client,
)
from a2a.client.interceptors import ClientCallInterceptor
from a2a.types.a2a_pb2 import (
    AgentCard,
    AgentCapabilities,
    AgentInterface,
    Message,
    Role,
    SendMessageConfiguration,
    SendMessageRequest,
    StreamResponse,
    TaskPushNotificationConfig,
)

from axon.types import ResourceManifest, AuthScheme, A2ASkill
from pa_a2a_client_simulation.server import push_results

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
)
logger = logging.getLogger("pa_executor")

PA_PORT = int(os.getenv("PA_PORT", "8001"))
PA_WEBHOOK_URL = f"http://localhost:{PA_PORT}/webhook/task-complete"

_push_results: dict[str, dict] = {}


def _resolve_auth_token(manifest: ResourceManifest) -> str | None:
    if not manifest.auth or not manifest.auth.env_var:
        return None
    return os.getenv(manifest.auth.env_var)


# ──────────────────────────────────────────────────────────────
# CredentialService
#
# Fornece o token ao AuthInterceptor a partir do ResourceManifest.
#
# O token é resolvido pelo TAPA 2 antes de o manifesto ser emitido:
# recursos com requires_auth=True e token ausente (AXON_SECRET_X não
# configurado) são descartados na filtragem de política e nunca chegam
# ao executor. Se o manifesto chegou aqui com auth.scheme=bearer,
# auth.token está preenchido.
# ──────────────────────────────────────────────────────────────

class ManifestCredentialService(CredentialService):
    def __init__(self, manifest: ResourceManifest) -> None:
        self._manifest = manifest

    async def get_credentials(
        self,
        scheme_name: str,
        context: ClientCallContext | None,
    ) -> str | None:
        return _resolve_auth_token(self._manifest)


# ──────────────────────────────────────────────────────────────
# build_agent_card
#
# Traduz ResourceManifest → AgentCard mínimo que o ClientFactory
# precisa para instanciar o transporte correto.
#
# O ClientFactory lê exatamente três coisas do card:
#   1. supported_interfaces → URL + protocol_binding (qual transporte)
#   2. capabilities.streaming → send_message vs send_message_streaming
#   3. security_schemes → qual header de auth montar (AuthInterceptor)
#
# Todos os outros campos do AgentCard (name, description, skills, etc.)
# são para descoberta — o executor não precisa deles.
# ──────────────────────────────────────────────────────────────

def build_agent_card(manifest: ResourceManifest) -> AgentCard:
    card = AgentCard(
        # 1. onde e como conectar
        supported_interfaces=[
            AgentInterface(
                protocol_binding=manifest.protocol_binding.value,
                url=manifest.endpoint,
            )
        ],
        # 2. capacidades que afetam a estratégia de execução
        capabilities=AgentCapabilities(
            streaming=(
                manifest.a2a_capabilities.streaming
                if manifest.a2a_capabilities else False
            ),
        ),
    )

    # 3. security scheme — AuthInterceptor usa isso para saber
    #    qual header montar (Authorization: Bearer, X-Api-Key, etc.)
    #    O valor do token vem do ManifestCredentialService, não daqui.
    if manifest.auth and manifest.auth.scheme == AuthScheme.bearer:
        card.security_schemes["bearerAuth"].http_auth_security_scheme.scheme = "bearer"
        req = card.security_requirements.add()
        req.schemes["bearerAuth"].SetInParent()

    return card


# ──────────────────────────────────────────────────────────────
# build_client_config
#
# Configura o comportamento do client — não o transporte.
# O ClientConfig é criado uma vez por client.
#
# accepted_output_modes fica vazio aqui porque varia por skill —
# é preenchido dinamicamente em build_request via skill.outputModes.
# ──────────────────────────────────────────────────────────────

def build_client_config(manifest: ResourceManifest) -> ClientConfig:
    push_config = None
    if manifest.a2a_capabilities and manifest.a2a_capabilities.pushNotifications:
        push_config = TaskPushNotificationConfig(url=PA_WEBHOOK_URL)

    return ClientConfig(
        # streaming: o SDK usa send_message_streaming (SSE) somente se
        # ClientConfig.streaming AND card.capabilities.streaming forem True
        streaming=(
            manifest.a2a_capabilities.streaming
            if manifest.a2a_capabilities else False
        ),
        # push: injeta TaskPushNotificationConfig em todo request como default
        # — pode ser sobrescrito por request em build_request(push_url=...)
        push_notification_config=push_config,
    )


# ──────────────────────────────────────────────────────────────
# build_request
#
# Monta o SendMessageRequest para uma chamada específica.
#
# skill é opcional — quando presente, seus outputModes são adicionados
# ao SendMessageConfiguration do request (não ao ClientConfig) para
# que cada chamada possa especificar os formatos aceitos dinamicamente.
# ──────────────────────────────────────────────────────────────

def build_request(
    text: str,
    skill: A2ASkill | None = None,
    push_url: str | None = None,
) -> SendMessageRequest:
    msg = Message(
        message_id=uuid4().hex,
        context_id=uuid4().hex,
        role=Role.Value("ROLE_USER"),
    )
    part = msg.parts.add()
    part.text = text

    cfg = SendMessageConfiguration()

    # outputModes da skill selecionada — dinâmico por request
    if skill and skill.outputModes:
        cfg.accepted_output_modes.extend(skill.outputModes)

    # push_url por request — sobrescreve o default do ClientConfig
    if push_url:
        cfg.task_push_notification_config.url = push_url
        # Para push, a chamada deve retornar cedo com a task e deixar
        # a conclusão chegar pelo webhook.
        cfg.return_immediately = True

    return SendMessageRequest(message=msg, configuration=cfg)


# ──────────────────────────────────────────────────────────────
# build_a2a_client
#
# Junta as três peças e retorna um BaseClient pronto para uso.
#
# interceptors só é populado quando há autenticação —
# AuthScheme.none significa chamada direta sem header de auth.
#
# O client deve ser usado como async context manager para garantir
# que o httpx.AsyncClient interno seja fechado corretamente.
#
# Uso:
#   async with await build_a2a_client(manifest) as client:
#       async for resp in client.send_message(request):
#           ...
# ──────────────────────────────────────────────────────────────

async def build_a2a_client(manifest: ResourceManifest):
    card   = build_agent_card(manifest)
    config = build_client_config(manifest)

    interceptors: list[ClientCallInterceptor] = []
    if manifest.auth and manifest.auth.scheme != AuthScheme.none:
        interceptors.append(AuthInterceptor(ManifestCredentialService(manifest)))

    return await create_client(
        card,
        client_config=config,
        interceptors=interceptors,
    )


# ──────────────────────────────────────────────────────────────
# build_a2a_client
#
# Junta as três peças e retorna um BaseClient pronto para uso.
#
# interceptors só é populado quando há autenticação —
# AuthScheme.none significa chamada direta sem header de auth.
#
# O client deve ser usado como async context manager para garantir
# que o httpx.AsyncClient interno seja fechado corretamente.
#
# Uso:
#   async with await build_a2a_client(manifest) as client:
#       async for resp in client.send_message(request):
#           ...
# ──────────────────────────────────────────────────────────────

async def build_a2a_client(manifest: ResourceManifest):
    card   = build_agent_card(manifest)
    config = build_client_config(manifest)

    interceptors: list[ClientCallInterceptor] = []
    if manifest.auth and manifest.auth.scheme != AuthScheme.none:
        interceptors.append(AuthInterceptor(ManifestCredentialService(manifest)))

    return await create_client(
        card,
        client_config=config,
        interceptors=interceptors,
    )


# ──────────────────────────────────────────────────────────────
# extract_text
#
# Extrai o texto de um StreamResponse.
# O StreamResponse tem um oneof "payload" com quatro variantes:
#   task, message, status_update, artifact_update
# Para o executor, só task e message carregam texto útil.
# ──────────────────────────────────────────────────────────────

def extract_text(resp: StreamResponse) -> str | None:
    kind = resp.WhichOneof("payload")
    if not kind:
        return None

    payload = getattr(resp, kind)

    def part_texts(parts) -> list[str]:
        return [part.text for part in parts if part.HasField("text") and part.text]

    # task → status.message.parts + artifacts + histórico do agente
    if kind == "task":
        texts: list[str] = []
        if payload.status.HasField("message"):
            texts.extend(part_texts(payload.status.message.parts))

        for artifact in payload.artifacts:
            texts.extend(part_texts(artifact.parts))

        for history_item in payload.history:
            if history_item.role == Role.Value("ROLE_AGENT"):
                texts.extend(part_texts(history_item.parts))

        return "\n".join(texts) if texts else None

    # message direto → parts
    if kind == "message":
        texts = part_texts(payload.parts)
        return "\n".join(texts) if texts else None

    # status_update → status.message.parts
    if kind == "status_update" and payload.status.HasField("message"):
        texts = part_texts(payload.status.message.parts)
        return "\n".join(texts) if texts else None

    # artifact_update → artifact.parts
    if kind == "artifact_update":
        texts = part_texts(payload.artifact.parts)
        return "\n".join(texts) if texts else None

    return None


def _collect_part_texts(parts) -> list[str]:
    texts: list[str] = []
    for part in parts or []:
        text = None
        if isinstance(part, dict):
            text = part.get("text")
        else:
            text = getattr(part, "text", None)
        if text:
            texts.append(text)
    return texts


def _extract_text_from_push_payload(payload: dict) -> str | None:
    texts: list[str] = []
    root = payload.get("task", payload) if isinstance(payload, dict) else payload

    if isinstance(root, dict):
        message = root.get("message")
        if isinstance(message, dict):
            texts.extend(_collect_part_texts(message.get("parts")))

        status = root.get("status")
        if isinstance(status, dict):
            status_message = status.get("message")
            if isinstance(status_message, dict):
                texts.extend(_collect_part_texts(status_message.get("parts")))

        for artifact in root.get("artifacts", []):
            if isinstance(artifact, dict):
                texts.extend(_collect_part_texts(artifact.get("parts")))

        for history_item in root.get("history", []):
            if isinstance(history_item, dict):
                texts.extend(_collect_part_texts(history_item.get("parts")))

    if isinstance(payload, dict):
        artifact_update = payload.get("artifact_update")
        if isinstance(artifact_update, dict):
            artifact = artifact_update.get("artifact")
            if isinstance(artifact, dict):
                texts.extend(_collect_part_texts(artifact.get("parts")))

        status_update = payload.get("status_update")
        if isinstance(status_update, dict):
            status = status_update.get("status")
            if isinstance(status, dict):
                message = status.get("message")
                if isinstance(message, dict):
                    texts.extend(_collect_part_texts(message.get("parts")))

    result = "\n".join(texts).strip()
    return result or None


# ──────────────────────────────────────────────────────────────
# execute
#
# Ponto de entrada do executor — recebe o ResourceManifest,
# a subtask em texto, e a skill selecionada, e devolve o
# resultado completo como string.
#
# O PA usa o resultado para marcar a subtask como concluída
# e avançar no plano — portanto acumula todos os chunks antes
# de retornar, independente de streaming estar ativo.
#
# Streaming ativo significa que os chunks chegam incrementalmente
# via SSE, mas o PA ainda recebe tudo de uma vez no retorno.
# ──────────────────────────────────────────────────────────────

async def execute(
    manifest: ResourceManifest,
    prompt: str,
    skill: A2ASkill | None = None,
) -> str:
    logger.info(
        f"[execute] resource={manifest.resource_id} "
        f"endpoint={manifest.endpoint} "
        f"streaming={manifest.a2a_capabilities.streaming if manifest.a2a_capabilities else False}"
    )

    request = build_request(prompt, skill=skill)

    async with await build_a2a_client(manifest) as client:
        chunks: list[str] = []
        async for resp in client.send_message(request):
            text = extract_text(resp)
            if text:
                chunks.append(text)

    result = "".join(chunks)
    logger.info(f"[execute] concluído ({len(result)} chars)")
    return result


async def execute_with_push(
    manifest: ResourceManifest,
    prompt: str,
    skill: A2ASkill | None = None,
    timeout: float = 30.0,
) -> str:
    logger.info(
        f"[execute_with_push] resource={manifest.resource_id} "
        f"endpoint={manifest.endpoint}"
    )

    request = build_request(prompt, skill=skill, push_url=PA_WEBHOOK_URL)
    task_id: str | None = None
    fallback_chunks: list[str] = []

    async with await build_a2a_client(manifest) as client:
        async for resp in client.send_message(request):
            if resp.HasField("task") and resp.task.id and not task_id:
                task_id = resp.task.id

            text = extract_text(resp)
            if text:
                fallback_chunks.append(text)

    if task_id:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            payload = push_results.pop(task_id, None)
            if payload:
                pushed_text = _extract_text_from_push_payload(payload)
                if pushed_text:
                    logger.info(
                        f"[execute_with_push] push recebido ({len(pushed_text)} chars)"
                    )
                    return pushed_text
                return str(payload)
            await asyncio.sleep(0.1)

    if fallback_chunks:
        result = "".join(fallback_chunks)
        logger.info(
            f"[execute_with_push] sem push, usando resposta direta ({len(result)} chars)"
        )
        return result

    raise TimeoutError("Nenhum push recebido dentro do tempo limite.")
