"""
ga/registry.py — CRUD sobre registry.json.

Todos os métodos recebem GAPaths — sem paths hardcoded.
"""
from __future__ import annotations

import json
from pathlib import Path

from axon.ga.config import GAPaths
from axon.types import Resource, RegistryFile, ResourceStatus


def read_registry(paths: GAPaths) -> RegistryFile:
    if not paths.registry.exists():
        return RegistryFile()
    return RegistryFile.model_validate(
        json.loads(paths.registry.read_text(encoding="utf-8"))
    )


def write_registry(registry: RegistryFile, paths: GAPaths) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.registry.write_text(
        registry.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )


def add_resource(resource: Resource, paths: GAPaths) -> None:
    """Adiciona ou substitui por nome."""
    registry = read_registry(paths)
    registry.resources = [r for r in registry.resources if r.name != resource.name]
    registry.resources.append(resource)
    write_registry(registry, paths)


def remove_resource(name: str, paths: GAPaths) -> Resource | None:
    registry = read_registry(paths)
    target   = next((r for r in registry.resources if r.name == name), None)
    if target:
        registry.resources = [r for r in registry.resources if r.id != target.id]
        write_registry(registry, paths)
    return target


def remove_resource_by_id(resource_id: str, paths: GAPaths) -> Resource | None:
    registry = read_registry(paths)
    target   = next((r for r in registry.resources if r.id == resource_id), None)
    if target:
        registry.resources = [r for r in registry.resources if r.id != resource_id]
        write_registry(registry, paths)
    return target


def get_resource(name_or_id: str, paths: GAPaths) -> Resource | None:
    registry = read_registry(paths)
    by_id    = next((r for r in registry.resources if r.id    == name_or_id), None)
    by_name  = next((r for r in registry.resources if r.name  == name_or_id), None)
    return by_id or by_name


def list_resources(paths: GAPaths) -> list[Resource]:
    return read_registry(paths).resources


def update_status(resource_id: str, status: ResourceStatus, paths: GAPaths) -> None:
    registry = read_registry(paths)
    for r in registry.resources:
        if r.id == resource_id:
            r.status = status
            break
    write_registry(registry, paths)