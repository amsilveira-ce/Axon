"""
pa/clients/a2a_client.py — A2AClient

Chama agentes A2A a partir de um ResourceManifest.

O ResourceManifest é o único contrato de entrada — o mesmo objeto
que o GA entrega ao PA após descoberta e filtragem de política.

Fluxo por chamada:
  ResourceManifest
    → _build_agent_card()      AgentCard mínimo para o SDK
    → _build_client_config()   comportamento: streaming, push
    → _build_a2a_client()      create_client() + AuthInterceptor
    → _build_request()         SendMessageRequest com prompt e skill
    → call() / call_with_push()

Auth:
  ManifestCredentialService lê o token via TokenResolver (env var).
  O token nunca é armazenado no manifest — só o esquema e a env var.

Push notifications:
  call_with_push() requer um WebhookServer rodando no PA.
  Ver pa/clients/a2a_webhook.py.
"""

from __future__ import annotations

import asyncio
import logging
import os
from uuid import uuid4
from typing import Any

from a2a.client import (
    AuthInterceptor,
    ClientCallContext,
    ClientConfig,
    CredentialService,
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

from axon.token_resolver import TokenResolver
from axon.types import A2ASkill, AuthScheme, ResourceManifest

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT     = 60.0
_DEFAULT_PUSH_TIMEOUT = 30.0


# ── ManifestCredentialService ─────────────────────────────────────────────────

class ManifestCredentialService(CredentialService):
    """
    Fornece o token de autenticação ao AuthInterceptor do SDK.

    Usa o TokenResolver para ler o token da variável de ambiente —
    o manifest carrega auth.scheme e auth.env_var, nunca o token em si.
    """

    def __init__(self, manifest: ResourceManifest) -> None:
        self._manifest  = manifest
        self._resolver  = TokenResolver()

    async def get_credentials(
        self,
        scheme_name: str,
        context: ClientCallContext | None,
    ) -> str | None:
        return self._resolver.resolve(self._manifest)


# ── A2AClient ─────────────────────────────────────────────────────────────────

class A2AClient:
    """
    Cliente A2A do PA — traduz ResourceManifest em chamadas A2A reais.

    Uso simples:
        client = A2AClient()
        result = await client.call(manifest, task="analyze patient João")

    Com push notifications:
        async with WebhookServer() as webhook:
            client = A2AClient(pa_webhook_url=webhook.url)
            result = await client.call_with_push(manifest, task="...")
    """

    def __init__(
        self,
        pa_webhook_url: str | None = None,
        timeout:        float      = _DEFAULT_TIMEOUT,
    ) -> None:
        self._webhook_url = pa_webhook_url or self._default_webhook_url()
        self._timeout     = timeout
        self._resolver    = TokenResolver()

    @staticmethod
    def _default_webhook_url() -> str:
        port = int(os.getenv("PA_PORT", "8001"))
        return f"http://localhost:{port}/webhook/task-complete"

    # ------------------------------------------------------------------
    #   Builders — traduzem ResourceManifest para tipos do SDK
    # ------------------------------------------------------------------

    def _build_agent_card(self, manifest: ResourceManifest) -> AgentCard:
        """
        Monta o AgentCard mínimo que o ClientFactory precisa.

        O SDK lê três coisas do card:
          1. supported_interfaces → URL + protocol_binding (transporte)
          2. capabilities.streaming → send_message vs send_message_streaming
          3. security_schemes → esquema de auth para o AuthInterceptor
        """
        card = AgentCard(
            supported_interfaces=[
                AgentInterface(
                    protocol_binding=manifest.protocol_binding.value,
                    url=manifest.endpoint,
                )
            ],
            capabilities=AgentCapabilities(
                streaming=(
                    manifest.a2a_capabilities.streaming
                    if manifest.a2a_capabilities else False
                ),
            ),
        )

        # security scheme — o valor do token vem do ManifestCredentialService
        if manifest.auth and manifest.auth.scheme == AuthScheme.bearer:
            card.security_schemes["bearerAuth"].http_auth_security_scheme.scheme = "bearer"
            req = card.security_requirements.add()
            req.schemes["bearerAuth"].SetInParent()

        return card

    def _build_client_config(self, manifest: ResourceManifest) -> ClientConfig:
        """
        Configura o comportamento do client — não o transporte.

        push_notification_config é o default para todos os requests deste
        client — pode ser sobrescrito por request em _build_request().
        """
        push_config = None
        if manifest.a2a_capabilities and manifest.a2a_capabilities.pushNotifications:
            push_config = TaskPushNotificationConfig(url=self._webhook_url)

        return ClientConfig(
            streaming=(
                manifest.a2a_capabilities.streaming
                if manifest.a2a_capabilities else False
            ),
            push_notification_config=push_config,
        )

    def _build_request(
        self,
        text:     str,
        skill:    A2ASkill | None = None,
        push_url: str | None      = None,
    ) -> SendMessageRequest:
        """
        Monta o SendMessageRequest para uma chamada específica.

        skill.outputModes é dinâmico por request — varia conforme a skill
        selecionada pelo Resolver para a subtask atual.
        """
        msg  = Message(
            message_id=uuid4().hex,
            context_id=uuid4().hex,
            role=Role.Value("ROLE_USER"),
        )
        part      = msg.parts.add()
        part.text = text

        cfg = SendMessageConfiguration()

        if skill and skill.outputModes:
            cfg.accepted_output_modes.extend(skill.outputModes)

        if push_url:
            cfg.task_push_notification_config.url = push_url
            cfg.return_immediately = True

        return SendMessageRequest(message=msg, configuration=cfg)

    async def _build_a2a_client(self, manifest: ResourceManifest):
        """
        Instancia o BaseClient do SDK com transporte e auth configurados.

        Deve ser usado como async context manager — garante que o
        httpx.AsyncClient interno é fechado corretamente.
        """
        card   = self._build_agent_card(manifest)
        config = self._build_client_config(manifest)

        interceptors: list[ClientCallInterceptor] = []
        if manifest.auth and manifest.auth.scheme != AuthScheme.none:
            interceptors.append(
                AuthInterceptor(ManifestCredentialService(manifest))
            )

        return await create_client(
            card,
            client_config=config,
            interceptors=interceptors,
        )

    # ------------------------------------------------------------------
    #   Extração de texto das respostas A2A
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(resp: StreamResponse) -> str | None:
        """
        Extrai texto de um StreamResponse (oneof payload).

        Variantes tratadas:
          task          → status.message.parts + artifacts + history (ROLE_AGENT)
          message       → parts
          status_update → status.message.parts
          artifact_update → artifact.parts
        """
        kind = resp.WhichOneof("payload")
        if not kind:
            return None

        payload = getattr(resp, kind)

        def part_texts(parts) -> list[str]:
            return [p.text for p in parts if p.HasField("text") and p.text]

        if kind == "task":
            texts: list[str] = []
            if payload.status.HasField("message"):
                texts.extend(part_texts(payload.status.message.parts))
            for artifact in payload.artifacts:
                texts.extend(part_texts(artifact.parts))
            for item in payload.history:
                if item.role == Role.Value("ROLE_AGENT"):
                    texts.extend(part_texts(item.parts))
            return "\n".join(texts) if texts else None

        if kind == "message":
            texts = part_texts(payload.parts)
            return "\n".join(texts) if texts else None

        if kind == "status_update" and payload.status.HasField("message"):
            texts = part_texts(payload.status.message.parts)
            return "\n".join(texts) if texts else None

        if kind == "artifact_update":
            texts = part_texts(payload.artifact.parts)
            return "\n".join(texts) if texts else None

        return None

    @staticmethod
    def _extract_text_from_push_payload(payload: dict) -> str | None:
        """Extrai texto de um payload de push notification (JSON dict)."""

        def collect(parts) -> list[str]:
            texts = []
            for p in parts or []:
                text = p.get("text") if isinstance(p, dict) else getattr(p, "text", None)
                if text:
                    texts.append(text)
            return texts

        texts: list[str] = []
        root = payload.get("task", payload) if isinstance(payload, dict) else payload

        if isinstance(root, dict):
            if msg := root.get("message"):
                texts.extend(collect(msg.get("parts") if isinstance(msg, dict) else []))

            if status := root.get("status"):
                if smsg := status.get("message") if isinstance(status, dict) else None:
                    texts.extend(collect(smsg.get("parts") if isinstance(smsg, dict) else []))

            for artifact in root.get("artifacts", []):
                if isinstance(artifact, dict):
                    texts.extend(collect(artifact.get("parts")))

            for item in root.get("history", []):
                if isinstance(item, dict):
                    texts.extend(collect(item.get("parts")))

        result = "\n".join(texts).strip()
        return result or None

    # ------------------------------------------------------------------
    #   API pública
    # ------------------------------------------------------------------

    async def call(
        self,
        manifest: ResourceManifest,
        task:     str,
        skill:    A2ASkill | None = None,
    ) -> str:
        """
        Chama um agente A2A e retorna o resultado completo.

        Suporta sync e streaming — o PA sempre recebe o resultado
        completo independente do modo, pois precisa marcar a subtask
        como concluída antes de avançar no plano.

        Args:
            manifest: ResourceManifest com endpoint, auth e capabilities
            task:     descrição da tarefa em linguagem natural
            skill:    skill selecionada para esta chamada (opcional)

        Returns:
            resultado completo como str
        """
        logger.info(
            "[A2AClient] call resource=%s endpoint=%s streaming=%s",
            manifest.resource_id,
            manifest.endpoint,
            manifest.a2a_capabilities.streaming if manifest.a2a_capabilities else False,
        )

        request = self._build_request(task, skill=skill)
        chunks: list[str] = []

        async with await self._build_a2a_client(manifest) as client:
            async for resp in client.send_message(request):
                text = self._extract_text(resp)
                if text:
                    chunks.append(text)

        result = "".join(chunks)
        logger.info("[A2AClient] completed (%d chars)", len(result))
        return result

    async def call_with_push(
        self,
        manifest:      ResourceManifest,
        task:          str,
        skill:         A2ASkill | None = None,
        push_results:  dict[str, dict] | None = None,
        timeout:       float = _DEFAULT_PUSH_TIMEOUT,
    ) -> str:
        """
        Chama um agente A2A com push notification.

        O agente processa a task assincronamente e faz POST no webhook
        do PA quando conclui. O executor aguarda o payload de push
        ou usa a resposta direta como fallback se o timeout esgotar.

        Args:
            manifest:     ResourceManifest com pushNotifications=True
            task:         descrição da tarefa
            skill:        skill selecionada (opcional)
            push_results: dict compartilhado com o WebhookServer
                          (importado de pa/clients/a2a_webhook.py)
            timeout:      tempo máximo de espera pelo push (default 30s)
        """
        if push_results is None:
            from axon.pa.clients.a2a_webhook import push_results as _pr
            push_results = _pr

        logger.info(
            "[A2AClient] call_with_push resource=%s webhook=%s",
            manifest.resource_id,
            self._webhook_url,
        )

        request = self._build_request(task, skill=skill, push_url=self._webhook_url)
        task_id: str | None = None
        fallback_chunks: list[str] = []

        async with await self._build_a2a_client(manifest) as client:
            async for resp in client.send_message(request):
                if resp.HasField("task") and resp.task.id and not task_id:
                    task_id = resp.task.id
                text = self._extract_text(resp)
                if text:
                    fallback_chunks.append(text)

        if task_id:
            deadline = asyncio.get_running_loop().time() + timeout
            while asyncio.get_running_loop().time() < deadline:
                payload = push_results.pop(task_id, None)
                if payload:
                    pushed_text = self._extract_text_from_push_payload(payload)
                    if pushed_text:
                        logger.info("[A2AClient] push received (%d chars)", len(pushed_text))
                        return pushed_text
                    return str(payload)
                await asyncio.sleep(0.1)

        if fallback_chunks:
            result = "".join(fallback_chunks)
            logger.info("[A2AClient] push timeout — using direct response (%d chars)", len(result))
            return result

        raise TimeoutError(f"No push received for task '{task_id}' within {timeout}s")