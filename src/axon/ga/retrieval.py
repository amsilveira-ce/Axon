"""
ga/retrieval.py — Matching semântico de recursos.

Dois modos configurados via GAInstanceConfig.retrieval_strategy:

  "keyword"   — MVP sem dependências externas.
                Ranking lexical via BM25 (Okapi) sobre nome, description,
                skills e tags.

  "embedding" — Embedding via Ollama (nomic-embed-text, mxbai-embed-large, etc.)
                Indexação no startup, cosine similarity em cada search.
                Modelo configurado em GAInstanceConfig.embedding_model.

Interface pública (idêntica nos dois modos):
  EmbeddingIndex.build(resources, config) → EmbeddingIndex
  EmbeddingIndex.search(query, top_k, threshold) → list[(Resource, float)]
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal
from axon.config import GAPaths
from axon.types import Resource


# ---------------------------------------------------------------------------
#   BM25 (Okapi) — ranking lexical do modo "keyword"
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class _BM25Index:
    """
    Índice BM25 construído uma vez sobre o texto dos recursos.

    score(D, Q) = Σ_q IDF(q) · f(q,D)·(k1+1) / (f(q,D) + k1·(1 - b + b·|D|/avgdl))

    IDF usa a variante não-negativa (estilo Lucene):
      IDF(q) = ln(1 + (N - df(q) + 0.5) / (df(q) + 0.5))

    k1 controla a saturação da frequência do termo; b controla a
    normalização pelo tamanho do documento (defaults clássicos: 1.5 / 0.75).
    """
    k1:        float = 1.5
    b:         float = 0.75
    doc_freqs: list[Counter[str]] = field(default_factory=list)   # f(q, D) por recurso
    doc_lens:  list[int]          = field(default_factory=list)
    avgdl:     float              = 1.0
    idf:       dict[str, float]   = field(default_factory=dict)

    @classmethod
    def build(cls, documents: list[str], k1: float = 1.5, b: float = 0.75) -> "_BM25Index":
        index = cls(k1=k1, b=b)
        df: Counter[str] = Counter()

        for doc in documents:
            tokens = _tokenize(doc)
            freqs  = Counter(tokens)
            index.doc_freqs.append(freqs)
            index.doc_lens.append(len(tokens))
            df.update(freqs.keys())

        n = len(documents)
        index.avgdl = (sum(index.doc_lens) / n) if n else 1.0
        index.idf   = {
            term: math.log(1.0 + (n - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }
        return index

    def score(self, query: str, doc_index: int) -> float:
        freqs   = self.doc_freqs[doc_index]
        doc_len = self.doc_lens[doc_index]
        norm    = self.k1 * (1.0 - self.b + self.b * doc_len / (self.avgdl or 1.0))

        s = 0.0
        for term in _tokenize(query):
            f = freqs.get(term, 0)
            if f == 0:
                continue
            s += self.idf.get(term, 0.0) * f * (self.k1 + 1.0) / (f + norm)
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
    bm25:      _BM25Index | None                 = None

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

        keyword:   índice BM25 sobre o texto dos recursos (sem deps externas)
        embedding: gera vetor para cada recurso via Ollama no startup
                   (o índice BM25 também é construído — fallback do embedding)
        """
        index = cls(strategy=strategy, resources=list(resources))
        index._build_bm25()

        if strategy == "embedding":
            if not embed_model:
                raise ValueError(
                    "embedding_model must be set when retrieval_strategy='embedding'\n"
                    "  run 'axon ga init --name <ctx>' or set embedding_model in ga.json"
                )
            index.embedder = OllamaEmbedder(host=embed_host, model=embed_model)
            index._index_resources()

        return index

    def _build_bm25(self) -> None:
        """Constrói o índice BM25 — barato, sempre disponível como fallback."""
        self.bm25 = _BM25Index.build([_resource_text(r) for r in self.resources])

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
        self._build_bm25()
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
        """
        Ranking BM25. Score 0 significa que nenhum termo da query aparece
        no recurso — esses são sempre descartados, mesmo com threshold 0.
        """
        if self.bm25 is None:
            self._build_bm25()

        scored = [
            (r, self.bm25.score(query, i))
            for i, r in enumerate(self.resources)
        ]
        scored = [(r, s) for r, s in scored if s > 0 and s >= threshold]
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


# ---------------------------------------------------------------------------
#   Função de conveniência — usada por POST /ga/resources/search
# ---------------------------------------------------------------------------

def search(
    query:        str,
    paths:        "GAPaths",  # noqa: F821
    capabilities: list[str] | None = None,
    max_results:  int              = 5,
) -> list[tuple[float, Resource]]:
    """
    Busca recursos do registry do contexto ativo e retorna (score, Resource)
    ordenado por relevância — a ordem que o endpoint /ga/resources/search consome.

    Filtra por capability tags (interseção com as tags das skills) quando
    informado, e então ranqueia semanticamente via EmbeddingIndex (keyword ou
    embedding, conforme a estratégia do GA).

    Nota: constrói o índice a cada chamada — adequado ao MVP. Em produção,
    manter um EmbeddingIndex persistente no processo do GA.
    """
    from axon.ga.config import GAConfig
    from axon.ga.registry import list_resources

    inst      = GAConfig.resolve().instance
    resources = list_resources(paths)

    if capabilities:
        wanted = {c.lower() for c in capabilities}
        resources = [
            r for r in resources
            if wanted & {t.lower() for s in (r.skills or []) for t in s.tags}
        ]

    index = EmbeddingIndex.build(
        resources,
        strategy=inst.retrieval_strategy,
        embed_host=inst.embedding_host,
        embed_model=inst.embedding_model,
    )
    threshold = inst.embedding_threshold if inst.retrieval_strategy == "embedding" else 0.0
    hits      = index.search(query, top_k=max_results, threshold=threshold)  # [(Resource, score)]

    return [(score, r) for r, score in hits]