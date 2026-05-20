from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
from collections.abc import Iterator
from typing import Any


# ---------------------------------------------------------------------------
#   Erros
# ---------------------------------------------------------------------------

class OllamaError(Exception):
    """Erro base do cliente Ollama."""


class OllamaConnectionError(OllamaError):
    """Servidor Ollama inacessível."""


class OllamaResponseError(OllamaError):
    """Servidor respondeu com erro HTTP ou JSON inesperado."""


class OllamaParseError(OllamaError):
    """Resposta recebida mas não parseável após retries."""


# ---------------------------------------------------------------------------
#   Cliente
# ---------------------------------------------------------------------------

class OllamaClient:
    """
    Cliente mínimo para a API Ollama (stdlib apenas — sem dependências extras).

    Suporta:
      - generate()          → resposta completa (str)
      - generate_stream()   → Iterator[str] chunks em tempo real
      - chat()              → multi-turn com histórico
      - is_available()      → bool

    Structured output:
      Passe format=<dict>  → JSON Schema — constrange o modelo ao schema (mais robusto)
      Passe format="json"  → JSON livre — modelo tenta produzir JSON válido
      Passe format=None    → texto livre (reasoning models: use este + think=False)

    Reasoning models (DeepSeek-R1, Qwen3):
      think=True  → inclui <think> block no output
      think=False → suprime <think>, retorna só a resposta final
    """

    def __init__(
        self,
        host:    str = "http://localhost:11434",
        model:   str = "llama3.2",
        timeout: int = 60,
    ) -> None:
        self.host    = host.rstrip("/")
        self.model   = model
        self.timeout = timeout

    # ------------------------------------------------------------------
    #   generate — ponto de entrada principal para o IntentExtractor
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt:      str,
        *,
        system:      str | None = None,
        temperature: float = 0.0,
        format:      str | dict | None = None,
        think:       bool | None = None,
        retries:     int = 2,
        retry_delay: float = 1.0,
    ) -> str:
        """
        /api/generate — prompt único, sem histórico.

        Args:
            prompt:      conteúdo do usuário
            system:      system prompt opcional
            temperature: 0.0 = determinístico
            format:      None | "json" | dict (JSON Schema do Pydantic)
                         dict é o mais robusto — constrange o modelo ao schema
            think:       True/False para reasoning models (DeepSeek-R1, Qwen3)
                         False suprime o <think> block do output
                         None = não passa o parâmetro (default do modelo)
            retries:     tentativas extras em caso de OllamaParseError
            retry_delay: segundos entre tentativas

        Returns:
            str — conteúdo bruto da resposta

        Raises:
            OllamaConnectionError: servidor inacessível
            OllamaResponseError:   resposta HTTP/JSON inesperada
            OllamaParseError:      falha persistente de parse após retries
        """
        last_exc: Exception | None = None

        for attempt in range(1 + retries):
            try:
                return self._generate_once(
                    prompt, system=system, temperature=temperature,
                    format=format, think=think,
                )
            except OllamaParseError as exc:
                last_exc = exc
                if attempt < retries:
                    time.sleep(retry_delay)

        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    #   chat — multi-turn com histórico
    # ------------------------------------------------------------------

    def chat(
        self,
        messages:    list[dict[str, str]],
        *,
        temperature: float = 0.0,
        format:      str | dict | None = None,
        think:       bool | None = None,
    ) -> str:
        """
        /api/chat — envia lista de mensagens e retorna conteúdo da resposta.

        Usado pelo _Summarizer e outros componentes que mantêm histórico de turnos.
        """
        payload: dict[str, Any] = {
            "model":    self.model,
            "messages": messages,
            "stream":   False,
            "options":  {"temperature": temperature},
        }
        if format is not None:
            payload["format"] = format
        if think is not None:
            payload["think"] = think

        body = self._post("/api/chat", payload)

        if "message" in body:
            return body["message"]["content"]
        raise OllamaResponseError(
            f"Unexpected /api/chat response shape: {list(body.keys())}"
        )

    # ------------------------------------------------------------------
    #   generate_stream — para UX em tempo real (resposta final ao usuário)
    # ------------------------------------------------------------------

    def generate_stream(
        self,
        prompt:      str,
        *,
        system:      str | None = None,
        temperature: float = 0.0,
        format:      str | dict | None = None,
        think:       bool | None = None,
    ) -> Iterator[str]:
        """
        /api/generate com stream=True — yield de chunks de texto.

        Uso recomendado: exibição da resposta final do PA ao usuário.
        NÃO usar para extração estruturada — use generate() para isso.
        """
        payload: dict[str, Any] = {
            "model":   self.model,
            "prompt":  prompt,
            "stream":  True,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system
        if format is not None:
            payload["format"] = format
        if think is not None:
            payload["think"] = think

        url  = f"{self.host}/api/generate"
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for line in resp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "response" in chunk:
                        yield chunk["response"]
                    if chunk.get("done"):
                        break
        except urllib.error.URLError as exc:
            raise OllamaConnectionError(
                f"Ollama unavailable at {self.host}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    #   helpers
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.host}/api/tags")
            with urllib.request.urlopen(req, timeout=5):
                return True
        except Exception:
            return False

    def _generate_once(
        self,
        prompt:      str,
        *,
        system:      str | None,
        temperature: float,
        format:      str | dict | None,
        think:       bool | None,
    ) -> str:
        payload: dict[str, Any] = {
            "model":   self.model,
            "prompt":  prompt,
            "stream":  False,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system
        if format is not None:
            payload["format"] = format
        if think is not None:
            payload["think"] = think

        body = self._post("/api/generate", payload)

        if "response" not in body:
            raise OllamaResponseError(
                f"Unexpected /api/generate response shape: {list(body.keys())}"
            )
        return body["response"]

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url  = f"{self.host}{path}"
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.URLError as exc:
            raise OllamaConnectionError(
                f"Ollama unavailable at {self.host}: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise OllamaResponseError(
                f"Invalid JSON from Ollama: {exc}"
            ) from exc