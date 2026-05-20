from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Any, Iterator


class OllamaError(Exception):
    """Base para todos os erros do cliente Ollama."""

    def __init__(self, message: str, *, url: str | None = None) -> None:
        super().__init__(message)
        self.url = url


class OllamaConnectionError(OllamaError):
    """Servidor Ollama inacessível (rede, timeout, recusa de conexão)."""


class OllamaResponseError(OllamaError):
    """Resposta do Ollama inválida ou com formato inesperado."""

    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        status_code: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message, url=url)
        self.status_code = status_code
        self.body = body


class OllamaClient:
    """
    Cliente mínimo para a API Ollama.

    Usa apenas stdlib (urllib) — sem dependências extras.
    Compatível com qualquer componente do Axon (PA, GA).

    Uso:
        client = OllamaClient(host="http://localhost:11434", model="llama3.2")
        response = client.chat([{"role": "user", "content": "olá"}])
        print(response)          # str com o conteúdo da resposta
    """

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "llama3.2",
        timeout: int = 60,
    ) -> None:
        self.host    = host.rstrip("/")
        self.model   = model
        self.timeout = timeout

    # ------------------------------------------------------------------
    #   API pública
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        format: str | None = "json",   # None → texto livre
    ) -> str:
        """
        Envia uma lista de mensagens e retorna o conteúdo da resposta.

        Args:
            messages:    lista no formato [{"role": "...", "content": "..."}]
            temperature: 0.0 = determinístico (padrão para extração estruturada)
            format:      "json" força o modelo a responder JSON válido;
                         None retorna texto livre.

        Returns:
            str — conteúdo bruto da resposta (JSON string ou texto).

        Raises:
            OllamaError: servidor indisponível ou resposta inesperada.
        """
        payload: dict[str, Any] = {
            "model":    self.model,
            "messages": messages,
            "stream":   False,
            "options":  {"temperature": temperature},
        }
        if format == "json":
            payload["format"] = "json"

        return self._post("/api/chat", payload)

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        format: str | None = "json",
    ) -> str:
        """
        Endpoint /api/generate — útil para prompts sem histórico.
        """
        payload: dict[str, Any] = {
            "model":  self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system
        if format == "json":
            payload["format"] = "json"

        return self._post("/api/generate", payload)

    def generate_stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        format: str | None = None,
    ) -> Iterator[str]:
        """
        Versão streaming do /api/generate — yields cada chunk de texto
        conforme o modelo produz tokens.

        Uso:
            for chunk in client.generate_stream(prompt, system=sys):
                print(chunk, end="", flush=True)
        """
        payload: dict[str, Any] = {
            "model":  self.model,
            "prompt": prompt,
            "stream": True,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system
        if format == "json":
            payload["format"] = "json"

        yield from self._post_stream("/api/generate", payload, field="response")

    def is_available(self) -> bool:
        """Retorna True se o servidor Ollama está respondendo."""
        try:
            req = urllib.request.Request(f"{self.host}/api/tags")
            with urllib.request.urlopen(req, timeout=5):
                return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    #   Internals
    # ------------------------------------------------------------------

    def _post(self, path: str, payload: dict[str, Any]) -> str:
        url  = f"{self.host}{path}"
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raise OllamaResponseError(
                f"Ollama returned HTTP {exc.code} {exc.reason}",
                url=url,
                status_code=exc.code,
            ) from exc
        except urllib.error.URLError as exc:
            raise OllamaConnectionError(
                f"Ollama unreachable at {self.host}: {exc.reason}", url=url
            ) from exc
        except json.JSONDecodeError as exc:
            raise OllamaResponseError(
                f"Invalid JSON from Ollama: {exc}", url=url
            ) from exc

        # /api/chat  → body["message"]["content"]
        # /api/generate → body["response"]
        if "message" in body:
            return body["message"]["content"]
        if "response" in body:
            return body["response"]

        raise OllamaResponseError(
            f"Unexpected Ollama response shape: {list(body.keys())}", url=url
        )

    def _post_stream(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        field: str,
    ) -> Iterator[str]:
        url  = f"{self.host}{path}"
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for line in resp:
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line.decode())
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        raise OllamaResponseError(
                            f"Ollama stream error: {chunk['error']}", url=url
                        )
                    piece = chunk.get(field) or (
                        chunk.get("message", {}).get("content") if field == "message" else None
                    )
                    if piece:
                        yield piece
                    if chunk.get("done"):
                        break
        except urllib.error.HTTPError as exc:
            raise OllamaResponseError(
                f"Ollama returned HTTP {exc.code} {exc.reason}",
                url=url,
                status_code=exc.code,
            ) from exc
        except urllib.error.URLError as exc:
            raise OllamaConnectionError(
                f"Ollama unreachable at {self.host}: {exc.reason}", url=url
            ) from exc