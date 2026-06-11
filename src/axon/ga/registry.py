"""
ga/registry.py — CRUD sobre registry.json.

"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path

from axon.ga.config import GAPaths
from axon.types import AgentCard, Resource, RegistryFile, ResourceStatus, ResourceYaml


# ── persistence ───────────────────────────────────────────────────────────────

def read_registry(paths: GAPaths) -> RegistryFile:
    """Load registry.json; return empty RegistryFile if the file does not exist."""
    if not paths.registry.exists():
        return RegistryFile()
    return RegistryFile.model_validate(
        json.loads(paths.registry.read_text(encoding="utf-8"))
    )


def write_registry(registry: RegistryFile, paths: GAPaths) -> None:
    """Atomically persist registry to disk (write → .tmp → rename)."""
    paths.root.mkdir(parents=True, exist_ok=True)
    tmp = paths.registry.with_suffix(".tmp")
    tmp.write_text(registry.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, paths.registry)


# ── queries ───────────────────────────────────────────────────────────────────

def resource_exists(name: str, paths: GAPaths) -> bool:
    """Return True if a resource with this name is already registered."""
    return any(r.name == name for r in read_registry(paths).resources)


def list_resources(paths: GAPaths) -> list[Resource]:
    return read_registry(paths).resources


def get_resource(name_or_id: str, paths: GAPaths) -> Resource | None:
    registry = read_registry(paths)
    by_id   = next((r for r in registry.resources if r.id   == name_or_id), None)
    by_name = next((r for r in registry.resources if r.name == name_or_id), None)
    return by_id or by_name


# ── mutations ─────────────────────────────────────────────────────────────────

def add_resource(resource: Resource, paths: GAPaths) -> None:
    """Append resource; replace any existing entry with the same name (upsert)."""
    registry = read_registry(paths)
    registry.resources = [r for r in registry.resources if r.name != resource.name]
    registry.resources.append(resource)
    write_registry(registry, paths)


def update_status(resource_id: str, status: ResourceStatus, paths: GAPaths) -> None:
    """Update the status field of a resource in-place (used by integrity monitor)."""
    registry = read_registry(paths)
    for r in registry.resources:
        if r.id == resource_id:
            r.status = status
            break
    write_registry(registry, paths)


def remove_resource(name: str, paths: GAPaths) -> Resource | None:
    """Remove a resource by name; returns the removed entry or None."""
    registry = read_registry(paths)
    target   = next((r for r in registry.resources if r.name == name), None)
    if target:
        registry.resources = [r for r in registry.resources if r.id != target.id]
        write_registry(registry, paths)
    return target


def remove_resource_by_id(resource_id: str, paths: GAPaths) -> Resource | None:
    """Remove a resource by ID; returns the removed entry or None."""
    registry = read_registry(paths)
    target   = next((r for r in registry.resources if r.id == resource_id), None)
    if target:
        registry.resources = [r for r in registry.resources if r.id != resource_id]
        write_registry(registry, paths)
    return target


# ── fingerprinting ────────────────────────────────────────────────────────────

def fingerprint_of_agent_card(card: AgentCard, token: str) -> str:
    """
    HMAC-SHA256 fingerprint of an A2A agent card keyed by the admission token.

    Using the token as the HMAC key means the fingerprint can't be reproduced
    without the secret — it ties this registration to the specific token that
    admitted it, not just to the card content.
    """
    skill_ids = sorted(s.id for s in card.skills)
    payload = json.dumps(
        {"url": card.url, "name": card.name, "version": card.version, "skills": skill_ids},
        sort_keys=True,
    )
    return "sha256:" + hmac.new(token.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]


def fingerprint_of_resource_yaml(manifest: ResourceYaml, token: str) -> str:
    """
    HMAC-SHA256 fingerprint of an MCP resource YAML keyed by the admission token.

    Auth env-var names are excluded — rotating a secret must not invalidate
    an otherwise unchanged registration.
    """
    t = manifest.spec.transport
    skill_ids = sorted(s.id for s in manifest.spec.skills)
    payload = json.dumps(
        {
            "name":     manifest.metadata.name,
            "protocol": t.protocol,
            "endpoint": t.endpoint,
            "command":  t.command,
            "skills":   skill_ids,
        },
        sort_keys=True,
    )
    return "sha256:" + hmac.new(token.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]


def fingerprint_of_mcp_live(manifest: "ResourceManifest", tool_specs: list[dict], token: str) -> str:  # type: ignore[name-defined]
    """
    HMAC-SHA256 fingerprint of an MCP resource keyed by the admission token,
    computed over live-probed tool data (name + description from the real server).

    Used by the 'axon add mcp' CLI path where no YAML is available.
    Rotating auth secrets does not change the fingerprint — env_var is excluded.
    """
    payload = json.dumps(
        {
            "name":     manifest.name,
            "binding":  manifest.protocol_binding.value,
            "endpoint": manifest.endpoint,
            "command":  manifest.command,
            "tools":    sorted(f"{s['name']}\n{s['description']}" for s in tool_specs),
        },
        sort_keys=True,
    )
    return "sha256:" + hmac.new(token.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]