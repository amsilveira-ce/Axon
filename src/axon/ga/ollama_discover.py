"""
ga/ollama_discover.py — Descoberta de modelos de embedding no Ollama.

Identifica modelos de embedding via:
  1. details.families — bert, nomic-bert
  2. nome do modelo   — padrões conhecidos (embed, bge-, e5-, gte-, minilm, etc.)

Retorna lista de nomes de modelos disponíveis e prontos para uso com
POST /api/embed.
"""
from __future__ import annotations

_EMBEDDING_FAMILIES = {"bert", "nomic-bert"}

_EMBEDDING_NAME_PATTERNS = [
    "embed",
    "bge-",
    "e5-",
    "gte-",
    "minilm",
    "all-minilm",
    "mxbai-embed",
    "nomic-embed",
    "snowflake-arctic",
    "paraphrase",
    "sentence",
]


def _is_embedding_model(name: str, families: list[str]) -> bool:
    """Heurística para identificar modelos de embedding."""
    name_lower = name.lower()

    # família conhecida de embedding
    for fam in families:
        if fam.lower() in _EMBEDDING_FAMILIES:
            return True

    # nome contém padrão conhecido
    for pattern in _EMBEDDING_NAME_PATTERNS:
        if pattern in name_lower:
            return True

    return False


def list_embedding_models(host: str = "http://localhost:11434") -> list[str]:
    """
    Retorna lista de modelos de embedding disponíveis no Ollama.

    Chama GET /api/tags e filtra pelos critérios acima.
    Retorna lista vazia se Ollama não estiver rodando.
    """
    import httpx

    try:
        resp = httpx.get(f"{host}/api/tags", timeout=5.0)
        resp.raise_for_status()
        models = resp.json().get("models", [])
    except Exception:
        return []

    result = []
    for m in models:
        name     = m.get("name", "")
        families = m.get("details", {}).get("families") or []
        if _is_embedding_model(name, families):
            result.append(name)

    return sorted(result)