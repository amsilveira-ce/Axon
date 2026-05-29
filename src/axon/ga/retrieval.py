"""
ga/retrieval.py — Matching semântico de recursos.

Dois modos configurados via GAInstanceConfig.retrieval_strategy:

  "keyword"   — MVP sem dependências externas.
                Score por keyword matching em tags, description e nome.

  "embedding" — Embedding via Ollama (nomic-embed-text, mxbai-embed-large, etc.)
                Indexação no startup, cosine similarity em cada search.
                Modelo configurado em GAInstanceConfig.embedding_model.

Interface pública (idêntica nos dois modos):
  EmbeddingIndex.build(resources, config) → EmbeddingIndex
  EmbeddingIndex.search(query, top_k, threshold) → list[(Resource, float)]
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from axon.types import Resource


# ---------------------------------------------------------------------------
#   Helpers de score
# ---------------------------------------------------------------------------

def _keyword_score(query: str, resource: Resource) -> float:
    q = query.lower()
    s = 0.0

    for skill in resource.skills:
        for tag in skill.tags:
            if tag.lower() in q:
                s += 1.0
        if q in skill.description.lower():
            s += 0.5

    if q in resource.description.lower():
        s += 1.0
    if q in resource.name.lower():
        s += 0.5

    return s


def _cosine(a: list[float], b: list[float]) -> float:
    dot  = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return dot / norm if norm > 0 else 0.0


def _resource_text(resource: Resource) -> str:
    parts = [resource.name, resource.description]
    for skill in resource.skills:
        parts.append(skill.description)
        parts.extend(skill.tags)
    return " ".join(parts)


# ---------------------------------------------------------------------------
#   OllamaEmbedder
# ---------------------------------------------------------------------------

class OllamaEmbedder:
    """Gera embeddings via POST /api/embed."""

    def __init__(self, host: str, model: str) -> None:
        self._host  = host.rstrip("/")
        self._model = model

    def embed(self, text: str) -> list[float]:
        import httpx
        resp = httpx.post(
            f"{self._host}/api/embed",
            json={"model": self._model, "input": text},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        # Ollama retorna embeddings como lista de listas
        embeddings = data.get("embeddings") or data.get("embedding")
        if isinstance(embeddings[0], list):
            return embeddings[0]
        return embeddings


# ---------------------------------------------------------------------------
#   EmbeddingIndex
# ---------------------------------------------------------------------------

@dataclass
class EmbeddingIndex:
    """
    Índice de recursos para busca semântica.

    Criado uma vez no startup do GA via EmbeddingIndex.build().
    Mantido em memória durante o ciclo de vida do processo.
    """
    strategy:  Literal["keyword", "embedding"]
    resources: list[Resource]                    = field(default_factory=list)
    vectors:   dict[str, list[float]]            = field(default_factory=dict)  # resource.id → vetor
    embedder:  OllamaEmbedder | None             = None

    @classmethod
    def build(
        cls,
        resources: list[Resource],
        strategy:  Literal["keyword", "embedding"] = "keyword",
        embed_host: str = "http://localhost:11434",
        embed_model: str | None = None,
    ) -> "EmbeddingIndex":
        """
        Constrói o índice a partir dos recursos do registry.

        keyword:   sem vetores — score calculado em tempo de busca
        embedding: gera vetor para cada recurso via Ollama no startup
        """
        index = cls(strategy=strategy, resources=list(resources))

        if strategy == "embedding":
            if not embed_model:
                raise ValueError(
                    "embedding_model must be set when retrieval_strategy='embedding'\n"
                    "  run 'axon ga init --name <ctx>' or set embedding_model in ga.json"
                )
            index.embedder = OllamaEmbedder(host=embed_host, model=embed_model)
            index._index_resources()

        return index

    def _index_resources(self) -> None:
        """Gera e armazena vetores para todos os recursos."""
        if self.embedder is None:
            return

        import logging
        logger = logging.getLogger(__name__)

        for r in self.resources:
            text = _resource_text(r)
            try:
                self.vectors[r.id] = self.embedder.embed(text)
                logger.debug("[Retrieval] indexed %s (%d dims)", r.name, len(self.vectors[r.id]))
            except Exception as e:
                logger.warning("[Retrieval] failed to index %s: %s", r.name, e)

    def reindex(self, resources: list[Resource]) -> None:
        """Re-indexa após mudanças no registry (novo registro, remoção)."""
        self.resources = list(resources)
        if self.strategy == "embedding":
            self.vectors = {}
            self._index_resources()

    # ------------------------------------------------------------------
    #   Search
    # ------------------------------------------------------------------

    def search(
        self,
        query:     str,
        top_k:     int   = 5,
        threshold: float = 0.0,
    ) -> list[tuple[Resource, float]]:
        """
        Busca os recursos mais relevantes para a query.

        Returns:
            list[(Resource, score)] ordenado por score descendente.
            Filtra por threshold. Se nenhum recurso passa, retorna lista vazia.
        """
        if self.strategy == "embedding":
            return self._search_embedding(query, top_k, threshold)
        return self._search_keyword(query, top_k, threshold)

    def _search_keyword(
        self,
        query:     str,
        top_k:     int,
        threshold: float,
    ) -> list[tuple[Resource, float]]:
        scored = [
            (r, _keyword_score(query, r))
            for r in self.resources
        ]
        scored = [(r, s) for r, s in scored if s >= threshold]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def _search_embedding(
        self,
        query:     str,
        top_k:     int,
        threshold: float,
    ) -> list[tuple[Resource, float]]:
        if self.embedder is None:
            return []

        try:
            query_vec = self.embedder.embed(query)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "[Retrieval] embed query failed: %s — falling back to keyword", e
            )
            return self._search_keyword(query, top_k, threshold)

        scored = []
        for r in self.resources:
            vec = self.vectors.get(r.id)
            if vec is None:
                continue
            score = _cosine(query_vec, vec)
            if score >= threshold:
                scored.append((r, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]