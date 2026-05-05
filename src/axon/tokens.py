"""
axon/tokens.py - gestão de tokens Axon 

Responsabilidades desse modulo 
    - Emitir tokens para registro de recursos do tipo "agent"
"""
from axon.types import AxonToken, TokenStore
from axon.config import read_config
import secrets 
import json
from pathlib import Path

AXON_TOKEN_PREFIX = "axon_tk_"

def _tokens_registry_storage_path(cwd: Path | None = None) -> Path:

    config = read_config(cwd)
    # Fica no mesmo diretório .axon/ 
    base = Path(config.ga.registry_path).parent
    return (cwd or Path.cwd()) / base / "tokens.json"

def read_store(cwd: Path | None = None) -> TokenStore:
    p = _tokens_registry_storage_path(cwd)
    if not p.exists():
        return TokenStore()
    return TokenStore.model_validate(json.loads(p.read_text(encoding="utf-8")))

def write_store(store: TokenStore, cwd: Path | None = None) -> None:
    p = _tokens_registry_storage_path(cwd)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(store.model_dump_json(indent=2) + "\n", encoding="utf-8")
 

# Emissão de um token para registro de um recurso do tipo agente 
def generate(name: str, cwd: Path| None = None) -> AxonToken: 
    payload = f"{AXON_TOKEN_PREFIX}{secrets.token_urlsafe(24)}"
    token = AxonToken(
        token = payload,
        name = name, 
        registry_url=None,
        max_uses= 1
    )

    store = read_store()
    store.tokens.append(token)
    write_store(store, cwd)

    return token 