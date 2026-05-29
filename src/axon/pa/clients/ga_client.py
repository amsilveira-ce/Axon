"""
pa/clients/ga_client.py — GAClient

Cliente HTTP do PA para consultar um Gateway Agent.
Usado pelo Resolver no Step 2: para uma capability não coberta localmente,
chama POST /ga/resources/search e devolve um ResolverResult.

  search() mede latency_ms e extrai match_score — os dois sinais que o
  Resolver passa ao GAAffinityStore.update_partial().
"""

from __future__ import annotations

import time

import httpx

from axon.pa.models import ResolverResult
from axon.types import AuthConfig, ProtocolBinding, ResourceManifest, ResourceType


class GAClientError(Exception):
    """Falha ao consultar o Gateway Agent."""


class GAClient:
    """
    Cliente de um Gateway Agent específico.

    Uso:
        ga = GAClient("http://ga-corp:4005")
        result = ga.search(query="search the web for X",
                           capability="web_search", subtask_id="s3")
        if result:
            manifest = result.manifest   # melhor match, pronto p/ o Executor
    """

    SEARCH_PATH = "/ga/resources/search"

    def __init__(self, ga_url: str, timeout: float = 8.0) -> None:
        self._base    = ga_url.rstrip("/")
        self._timeout = timeout

    @property
    def url(self) -> str:
        return self._base

    def search(
        self,
        *,
        query:       str,
        capability:  str,
        subtask_id:  str,
        max_results: int = 5,
    ) -> ResolverResult | None:
        """
        Consulta o GA por recursos que cubram `capability` e melhor casem com `query`.

        Returns:
            ResolverResult (melhor match + alternativas) ou None se o GA não
            retornou nenhum recurso.

        Raises:
            GAClientError: falha de transporte/HTTP ao falar com o GA.
        """
        endpoint = f"{self._base}{self.SEARCH_PATH}"
        payload  = {
            "query":        query,
            "capabilities": [capability],
            "max_results":  max_results,
        }

        t0 = time.monotonic()
        try:
            resp = httpx.post(endpoint, json=payload, timeout=self._timeout)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise GAClientError(f"GA search failed at {endpoint}: {e}") from e
        latency_ms = (time.monotonic() - t0) * 1000.0

        results = resp.json().get("results", [])
        if not results:
            return None

        manifests = [self._to_manifest(item, capability) for item in results]

        return ResolverResult(
            capability=capability,
            subtask_id=subtask_id,
            manifest=manifests[0],
            alternatives=manifests[1:],
            ga_url=self._base,
            match_score=float(results[0].get("score", 0.0)),
            latency_ms=latency_ms,
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _to_manifest(item: dict, capability: str) -> ResourceManifest:
        """Reconstrói um ResourceManifest executável a partir de um result do /search."""
        tags = sorted({t for s in item.get("skills", []) for t in s.get("tags", [])})
        return ResourceManifest(
            resource_id=item["id"],
            name=item["name"],
            type=ResourceType(item["type"]),
            protocol_binding=ProtocolBinding(item["protocol_binding"]),
            description=item.get("description", ""),
            capability_tags=tags or [capability],
            callable_by="pa_direct",
            endpoint=item.get("endpoint"),
            command=item.get("command"),
            auth=AuthConfig.model_validate(item.get("auth") or {}),
        )
