"""
axon/tokens.py — gestão de tokens Axon

Responsabilidades:
    - Emitir tokens para registro de recursos do tipo "agent"
    - Verificar, revogar e marcar tokens como consumidos
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from axon.config import paths
from axon.types import AxonToken, TokenStore, TokenStatus

AXON_TOKEN_PREFIX = "axon_tk_"


# ======================================================
#   Leitura e escrita
# ======================================================

def read_store(cwd: Path | None = None) -> TokenStore:
    p = paths(cwd).ga_tokens
    if not p.exists():
        return TokenStore()
    return TokenStore.model_validate(json.loads(p.read_text(encoding="utf-8")))


def write_store(store: TokenStore, cwd: Path | None = None) -> None:
    p = paths(cwd).ga_tokens
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(store.model_dump_json(indent=2) + "\n", encoding="utf-8")


# ======================================================
#   Operações
# ======================================================

def generate(name: str, cwd: Path | None = None) -> AxonToken:
    payload = f"{AXON_TOKEN_PREFIX}{secrets.token_urlsafe(24)}"
    token = AxonToken(token=payload, name=name, registry_url=None, max_uses=1)
    store = read_store(cwd)
    store.tokens.append(token)
    write_store(store, cwd)
    return token


def list_tokens(cwd: Path | None = None) -> list[AxonToken]:
    return read_store(cwd).tokens


class TokenVerificationError(Exception):
    """Raised quando um token não passa na verificação local."""


def revoke(token_or_name: str, cwd: Path | None = None) -> AxonToken:
    store = read_store(cwd)
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
    write_store(store, cwd)
    return entry


def verify_local(token_value: str, cwd: Path | None = None) -> AxonToken:
    """
    Verifica um token contra o store local.

    Levanta TokenVerificationError se:
      - token não encontrado
      - token revogado
      - token já consumido (max_uses atingido)
      - token expirado

    Retorna o AxonToken sem marcá-lo como usado.
    Chame mark_used() após confirmar que o registro foi bem-sucedido.
    """
    store = read_store(cwd)
    entry = next((t for t in store.tokens if t.token == token_value), None)

    if entry is None:
        raise TokenVerificationError(
            "token not found in local store — "
            "run 'axon token generate --name <agent-name>' first"
        )
    if entry.status == TokenStatus.revoked:
        raise TokenVerificationError(
            f"token '{token_value[:20]}...' has been revoked"
        )
    if entry.max_uses is not None and entry.use_count >= entry.max_uses:
        raise TokenVerificationError(
            f"token '{token_value[:20]}...' has already been used "
            f"({entry.use_count}/{entry.max_uses} uses)"
        )
    if entry.expires_at and datetime.now(timezone.utc) > entry.expires_at:
        raise TokenVerificationError(
            f"token '{token_value[:20]}...' expired at {entry.expires_at}"
        )
    return entry


def mark_used(token_value: str, resource_id: str, cwd: Path | None = None) -> AxonToken:
    """
    Marca um token como consumido por um resource já persistido.

    Atualiza use_count/used_by e muda status para "used" quando atinge max_uses.
    """
    store = read_store(cwd)
    entry = next((t for t in store.tokens if t.token == token_value), None)

    if entry is None:
        raise TokenVerificationError(
            "token not found in local store — cannot mark it as used"
        )
    if entry.status == TokenStatus.revoked:
        raise TokenVerificationError(
            f"token '{token_value[:20]}...' has been revoked"
        )
    if entry.max_uses is not None and entry.use_count >= entry.max_uses:
        raise TokenVerificationError(
            f"token '{token_value[:20]}...' has already been used "
            f"({entry.use_count}/{entry.max_uses} uses)"
        )

    entry.use_count += 1
    entry.used_by = resource_id
    if entry.max_uses is not None and entry.use_count >= entry.max_uses:
        entry.status = TokenStatus.used

    write_store(store, cwd)
    return entry