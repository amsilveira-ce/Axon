"""
ga/tokens.py — Gestão de tokens do Gateway Agent.

Todos os métodos recebem GAPaths — sem paths hardcoded.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone

from axon.ga.config import GAPaths
from axon.types import AxonToken, TokenStore, TokenStatus

AXON_TOKEN_PREFIX = "axon_tk_"


def read_store(paths: GAPaths) -> TokenStore:
    if not paths.tokens.exists():
        return TokenStore()
    return TokenStore.model_validate(
        json.loads(paths.tokens.read_text(encoding="utf-8"))
    )


def write_store(store: TokenStore, paths: GAPaths) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.tokens.write_text(
        store.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )


class TokenVerificationError(Exception):
    """Raised quando um token não passa na verificação."""


def generate(name: str, paths: GAPaths) -> AxonToken:
    payload = f"{AXON_TOKEN_PREFIX}{secrets.token_urlsafe(24)}"
    token   = AxonToken(token=payload, name=name, registry_url=None, max_uses=1)
    store   = read_store(paths)
    store.tokens.append(token)
    write_store(store, paths)
    return token


def list_tokens(paths: GAPaths) -> list[AxonToken]:
    return read_store(paths).tokens


def revoke(token_or_name: str, paths: GAPaths) -> AxonToken:
    store = read_store(paths)
    entry = next(
        (t for t in store.tokens
         if t.token == token_or_name or t.name == token_or_name),
        None,
    )
    if entry is None:
        raise TokenVerificationError(
            f"token not found: '{token_or_name}'\n"
            "  run 'axon token list --all' to see available tokens"
        )
    entry.status = TokenStatus.revoked
    write_store(store, paths)
    return entry


def verify_local(token_value: str, paths: GAPaths) -> AxonToken:
    """Verifica token sem marcá-lo como usado. Chame mark_used() após persistir."""
    store = read_store(paths)
    entry = next((t for t in store.tokens if t.token == token_value), None)

    if entry is None:
        raise TokenVerificationError(
            "token not found — run 'axon token generate --name <name>' first"
        )
    if entry.status == TokenStatus.revoked:
        raise TokenVerificationError(f"token revoked")
    if entry.max_uses is not None and entry.use_count >= entry.max_uses:
        raise TokenVerificationError(
            f"token already used ({entry.use_count}/{entry.max_uses} uses)"
        )
    if entry.expires_at and datetime.now(timezone.utc) > entry.expires_at:
        raise TokenVerificationError(f"token expired at {entry.expires_at}")
    return entry


def mark_used(token_value: str, resource_id: str, paths: GAPaths) -> AxonToken:
    store = read_store(paths)
    entry = next((t for t in store.tokens if t.token == token_value), None)

    if entry is None:
        raise TokenVerificationError("token not found — cannot mark as used")
    if entry.status == TokenStatus.revoked:
        raise TokenVerificationError("token revoked")
    if entry.max_uses is not None and entry.use_count >= entry.max_uses:
        raise TokenVerificationError("token already used")

    entry.use_count += 1
    entry.used_by    = resource_id
    if entry.max_uses is not None and entry.use_count >= entry.max_uses:
        entry.status = TokenStatus.used

    write_store(store, paths)
    return entry