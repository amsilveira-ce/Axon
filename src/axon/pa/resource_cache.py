"""
pa/resource_cache.py — ResourceCache (LRU)

Cache de ResourceManifests de recursos **descobertos via GA** em runs anteriores
(tools locais ficam no LocalResourcePool, não aqui). Persiste em
.axon/pa/resource_cache.json.

Propósito:
  O Resolver, ao encontrar um recurso novo via GA, persiste o ResourceManifest
  no cache. Na próxima run, o AgentState começa com esses recursos já disponíveis
  — sem precisar consultar o GA novamente para capabilities já conhecidas.

Política LRU:
  O cache é limitado a `pa.cache.max_size` recursos (axon.config.json). A
  recência é dada pela ordem de `put` (descoberta/refresh): cada put move o
  recurso para o fim; quando o cache excede o limite, o recurso menos
  recentemente descoberto (frente) é removido. Assim recursos que continuam
  sendo redescobertos permanecem, e os obsoletos são despejados.

Ciclo de vida:
  startup  → ResourceCache.load(path, max_size) → list[ResourceManifest]
  run      → cache.put(manifest) → atualiza, evicta LRU se necessário, persiste
  shutdown → sem ação (persiste a cada update)
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from pathlib import Path

from pydantic import BaseModel, Field

from axon.types import ResourceManifest

logger = logging.getLogger(__name__)

DEFAULT_MAX_SIZE = 50


class ResourceCacheFile(BaseModel):
    """Conteúdo de .axon/pa/resource_cache.json."""
    version:   str                  = "0.1.0"
    resources: list[ResourceManifest] = Field(default_factory=list)


class ResourceCache:
    """
    Cache LRU de ResourceManifests descobertos via GA.

    Uso:
        cache     = ResourceCache.load(paths().pa_resource_cache, max_size=50)
        manifests = cache.all()          # recursos cacheados (mais recente por último)
        cache.put(manifest)              # adiciona/atualiza, evicta LRU, persiste
        cache.remove("resource-id")      # remove e persiste
    """

    def __init__(
        self,
        path:      Path,
        resources: list[ResourceManifest],
        max_size:  int = DEFAULT_MAX_SIZE,
    ) -> None:
        self._path     = path
        self._max_size = max_size
        # OrderedDict — a ordem é a recência: frente = menos recente, fim = mais recente.
        self._resources: "OrderedDict[str, ResourceManifest]" = OrderedDict(
            (r.resource_id, r) for r in resources
        )
        self._evict()   # caso o arquivo já exceda (ex.: max_size reduzido)

    @classmethod
    def load(cls, path: Path, max_size: int = DEFAULT_MAX_SIZE) -> "ResourceCache":
        """Carrega do arquivo. Retorna cache vazio se não existir."""
        if not path.exists():
            return cls(path=path, resources=[], max_size=max_size)
        try:
            data = ResourceCacheFile.model_validate(
                json.loads(path.read_text(encoding="utf-8"))
            )
            logger.debug("[ResourceCache] loaded %d resources", len(data.resources))
            return cls(path=path, resources=data.resources, max_size=max_size)
        except Exception as e:
            logger.warning("[ResourceCache] failed to load %s: %s — starting empty", path, e)
            return cls(path=path, resources=[], max_size=max_size)

    def all(self) -> list[ResourceManifest]:
        """Recursos cacheados, do menos ao mais recente."""
        return list(self._resources.values())

    def get(self, resource_id: str) -> ResourceManifest | None:
        return self._resources.get(resource_id)

    def put(self, manifest: ResourceManifest) -> None:
        """Adiciona/atualiza, marca como mais recente, evicta LRU e persiste."""
        self._resources[manifest.resource_id] = manifest
        self._resources.move_to_end(manifest.resource_id)   # mais recente
        self._evict()
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

    # ── LRU ───────────────────────────────────────────────────────────────────

    def _evict(self) -> None:
        """Remove os recursos menos recentemente descobertos até caber em max_size."""
        if self._max_size <= 0:
            return  # 0 ou negativo → sem limite
        while len(self._resources) > self._max_size:
            rid, evicted = self._resources.popitem(last=False)   # frente = LRU
            logger.info(
                "[ResourceCache] LRU evict '%s' (%s) — over max_size=%d",
                evicted.name, rid, self._max_size,
            )

    def _persist(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # ordem do OrderedDict = recência → preservada no arquivo
            data = ResourceCacheFile(resources=list(self._resources.values()))
            self._path.write_text(
                data.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
        except Exception as e:
            logger.warning("[ResourceCache] failed to persist: %s", e)
