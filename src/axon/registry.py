from __future__ import annotations

import json
from pathlib import Path

from axon.config import paths
from axon.types import Resource, RegistryFile, ResourceStatus


# ======================================================
#   Leitura e escrita
# ======================================================

def read_registry(cwd: Path | None = None) -> RegistryFile:
    p = paths(cwd).ga_registry
    if not p.exists():
        return RegistryFile()
    return RegistryFile.model_validate(json.loads(p.read_text(encoding="utf-8")))


def write_registry(registry: RegistryFile, cwd: Path | None = None) -> None:
    p = paths(cwd).ga_registry
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(registry.model_dump_json(indent=2) + "\n", encoding="utf-8")


# ======================================================
#   Operações de gerenciamento de recursos
# ======================================================

def add_resource(resource: Resource, cwd: Path | None = None) -> None:
    """
    Adiciona ou substitui um resource no registry.
    Nome é chave única — re-registro remove o anterior.
    """
    registry = read_registry(cwd)
    registry.resources = [r for r in registry.resources if r.name != resource.name]
    registry.resources.append(resource)
    write_registry(registry, cwd)


def remove_resource(name: str, cwd: Path | None = None) -> Resource | None:
    """Remove por nome. Retorna o removido ou None."""
    registry = read_registry(cwd)
    target = next((r for r in registry.resources if r.name == name), None)
    if target:
        registry.resources = [r for r in registry.resources if r.id != target.id]
        write_registry(registry, cwd)
    return target


def remove_resource_by_id(resource_id: str, cwd: Path | None = None) -> Resource | None:
    """Remove por ID. Preferir quando o ID já está disponível."""
    registry = read_registry(cwd)
    target = next((r for r in registry.resources if r.id == resource_id), None)
    if target:
        registry.resources = [r for r in registry.resources if r.id != resource_id]
        write_registry(registry, cwd)
    return target


def get_resource(name_or_id: str, cwd: Path | None = None) -> Resource | None:
    """Busca por ID (prioridade) ou por nome."""
    registry = read_registry(cwd)
    by_id = next((r for r in registry.resources if r.id == name_or_id), None)
    if by_id:
        return by_id
    return next((r for r in registry.resources if r.name == name_or_id), None)


def list_resources(cwd: Path | None = None) -> list[Resource]:
    return read_registry(cwd).resources


def update_status(resource_id: str, status: str, cwd: Path | None = None) -> None:
    """Atualiza o status de um resource em-place por ID."""
    registry = read_registry(cwd)
    for r in registry.resources:
        if r.id == resource_id:
            r.status = ResourceStatus(status)
            break
    write_registry(registry, cwd)


def update_resource_status(
    resource_id: str,
    status: ResourceStatus,
    cwd: Path | None = None,
) -> None:
    """Alias tipado de update_status — aceita ResourceStatus diretamente."""
    update_status(resource_id, status.value, cwd)