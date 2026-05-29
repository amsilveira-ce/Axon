"""
pa/resource_cache.py — ResourceCache

Cache de ResourceManifests de recursos descobertos via GA em runs anteriores.
Persiste em .axon/pa/resource_cache.json.

Propósito:
  O Resolver, ao encontrar um recurso novo via GA, persiste o ResourceManifest
  no cache. Na próxima run, o AgentState começa com esses recursos já disponíveis
  — sem precisar consultar o GA novamente para capabilities já conhecidas.

Ciclo de vida:
  startup  → ResourceCache.load(path) → list[ResourceManifest]
  run      → Resolver.persist(manifest) → atualiza o cache
  shutdown → sem ação necessária (persiste imediatamente a cada update)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field

from axon.types import ResourceManifest

logger = logging.getLogger(__name__)


class ResourceCacheFile(BaseModel):
    """Conteúdo de .axon/pa/resource_cache.json."""
    version:   str                  = "0.1.0"
    resources: list[ResourceManifest] = Field(default_factory=list)


class ResourceCache:
    """
    Cache de ResourceManifests descobertos via GA.

    Uso:
        cache    = ResourceCache.load(paths().pa_resource_cache)
        manifests = cache.all()          # todos os recursos cacheados
        cache.put(manifest)              # adiciona/atualiza e persiste
        cache.remove("resource-id")      # remove e persiste
    """

    def __init__(self, path: Path, resources: list[ResourceManifest]) -> None:
        self._path      = path
        self._resources = {r.resource_id: r for r in resources}

    @classmethod
    def load(cls, path: Path) -> "ResourceCache":
        """
        Carrega do arquivo. Retorna cache vazio se não existir.
        """
        if not path.exists():
            return cls(path=path, resources=[])

        try:
            data = ResourceCacheFile.model_validate(
                json.loads(path.read_text(encoding="utf-8"))
            )
            logger.debug("[ResourceCache] loaded %d resources", len(data.resources))
            return cls(path=path, resources=data.resources)
        except Exception as e:
            logger.warning("[ResourceCache] failed to load %s: %s — starting empty", path, e)
            return cls(path=path, resources=[])

    def all(self) -> list[ResourceManifest]:
        """Retorna todos os ResourceManifests cacheados."""
        return list(self._resources.values())

    def get(self, resource_id: str) -> ResourceManifest | None:
        return self._resources.get(resource_id)

    def put(self, manifest: ResourceManifest) -> None:
        """Adiciona ou atualiza um manifest e persiste imediatamente."""
        self._resources[manifest.resource_id] = manifest
        self._persist()

    def remove(self, resource_id: str) -> bool:
        """Remove um manifest pelo id. Retorna True se removido."""
        if resource_id not in self._resources:
            return False
        del self._resources[resource_id]
        self._persist()
        return True

    def __len__(self) -> int:
        return len(self._resources)

    def _persist(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = ResourceCacheFile(resources=list(self._resources.values()))
            self._path.write_text(
                data.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
        except Exception as e:
            logger.warning("[ResourceCache] failed to persist: %s", e)