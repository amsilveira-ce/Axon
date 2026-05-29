"""
ga/connections.py — registro de PAs conectados.

Persistido em .axon/ga/{context}/connections.json via POST /pa/connect.
Observabilidade: o GA sabe quais PAs consomem seus recursos. Dedupe por nome.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from axon.ga.config import GAPaths
from axon.types import ConnectionsFile, PACard, PAConnection


def read_connections(paths: GAPaths) -> ConnectionsFile:
    if not paths.connections.exists():
        return ConnectionsFile()
    return ConnectionsFile.model_validate(
        json.loads(paths.connections.read_text(encoding="utf-8"))
    )


def write_connections(file: ConnectionsFile, paths: GAPaths) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.connections.write_text(
        file.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )


def add_connection(card: PACard, paths: GAPaths) -> PAConnection:
    """Registra ou atualiza a conexão de um PA (dedupe por card.name)."""
    file     = read_connections(paths)
    now      = datetime.now(timezone.utc)
    existing = next((c for c in file.connections if c.card.name == card.name), None)

    if existing:
        existing.card      = card
        existing.last_seen = now
        conn = existing
    else:
        conn = PAConnection(card=card)
        file.connections.append(conn)

    write_connections(file, paths)
    return conn


def list_connections(paths: GAPaths) -> list[PAConnection]:
    return read_connections(paths).connections
