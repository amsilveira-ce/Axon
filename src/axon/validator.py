from dataclasses import dataclass, field
from axon.types import AgentCard
import httpx
from pydantic import ValidationError
import json 
import hashlib
from axon.ga.tokens import TokenVerificationError, verify_local
from axon.types import AgentCard, AxonMetadata, AXON_EXTENSION_URI
 
AXON_TOKEN_PREFIX           = "axon_tk_"
SUPPORTED_PROTOCOL_VERSIONS = {"0.1"}
AGENT_CARD_PATHS            = (
    "/.well-known/agent-card.json",
    "/.well-known/agent.json",
)
HEALTH_PATH                 = "/health"
TIMEOUT                     = 5.0




def _canonical_json(data: dict) -> str:
    """JSON com chaves ordenadas — fingerprint determinístico."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def fingerprint(data: dict) -> str:
    """
    SHA-256 dos primeiros 16 bytes do JSON canônico.

    Calculado sobre o dict original (não o objeto Pydantic parseado)
    para garantir que campos extras preservados pelo extra="allow"
    entrem no cálculo — o fingerprint reflete o card/manifesto completo.
    """
    return "sha256:" + hashlib.sha256(
        _canonical_json(data).encode()
    ).hexdigest()[:16]


@dataclass
class ValidationResult:
    ok:          bool
    agent_card:  AgentCard | None = None
    fingerprint: str | None = None
    error:       str | None = None
    step:        str | None = None
    # Valor do token verificado — usado por add_agent para chamar mark_used()
    # após persistir o resource. Nunca armazenado no registry diretamente.
    verified_token: str | None = None


@dataclass
class McpValidationResult:
    """Resultado da validação de um recurso MCP (conexão viva + tools)."""
    ok:          bool
    tools:       list[str]            = field(default_factory=list)   # nomes (para preview/count)
    tool_specs:  list[dict[str, str]] = field(default_factory=list)   # {name, description} p/ matching
    fingerprint: str | None           = None
    error:       str | None           = None
    step:        str | None           = None


def validate_mcp(manifest: "ResourceManifest") -> McpValidationResult:  # type: ignore[name-defined]
    """
    Valida um recurso MCP antes do registro no Gateway.

    Prova de validade = conexão viva: usa o MCPClient para conectar de verdade
    (HTTP/SSE/stdio, com a auth do manifest) e listar as tools. As tools provam
    que o recurso existe, está no ar e o que ele faz. O fingerprint é calculado
    sobre (binding + endpoint/command + tools ordenadas).

    Diferente do A2A, o recurso MCP não carrega axon_token — a autorização é
    apresentada pelo operador no momento do registro (token de admissão).
    """
    import asyncio

    from axon.ga.clients.mcp_client import MCPClient, MCPClientError

    async def _probe() -> list[dict[str, str]]:
        async with MCPClient(manifest, timeout=20.0) as client:
            return await client.list_tools_detailed()

    try:
        specs = asyncio.run(_probe())
    except MCPClientError as e:
        return McpValidationResult(ok=False, step="connect", error=str(e))
    except Exception as e:
        return McpValidationResult(ok=False, step="connect", error=str(e))

    names = [s["name"] for s in specs]
    fp = fingerprint({
        "binding":  manifest.protocol_binding.value,
        "endpoint": manifest.endpoint,
        "command":  manifest.command,
        # nome + descrição → drift detectado se o servidor mudar o que oferece
        "tools":    sorted(f"{s['name']}\n{s['description']}" for s in specs),
    })
    return McpValidationResult(ok=True, tools=names, tool_specs=specs, fingerprint=fp)


def _verify_token(axon_meta: AxonMetadata) -> TokenVerificationError | None:
    """
    Despacha a verificação do token para o registry correto.
 
    Retorna None se o token é válido, ou um TokenVerificationError se não.
    """
    if axon_meta.registry_id == "local":
        try:
            verify_local(axon_meta.token)
            return None
        except TokenVerificationError as e:
            return e
    else:
        # Gancho para verificação remota (vendor externo) — pós-MVP.
        # Quando registry_id != "local", o CLI chamará:
        #   POST {axon_meta.registry_url}/verify-token
        #   { "token": axon_meta.token }
        # e interpretará { "valid": true/false, "reason": "..." }.
        return TokenVerificationError(
            f"external registry '{axon_meta.registry_id}' not supported yet — "
            f"only registry_id='local' is supported in this version"
        )


def validate_agent(url: str)-> ValidationResult:
    """
    Valida um agente A2A antes do registro no Gateway.

    Etapas:
      1. Fetch do agent card (A2A/ADK ou rota legada)
      2. Validação de schema A2A
      3. Verificação do token Axon (metadata["axon"]["token"])
      4. Fingerprint SHA-256
    """
    base = url.rstrip("/")

    # Etapa 1: fetch do agent card 
    try:
        raw: dict | None = None
        last_status_code: int | None = None

        for card_path in AGENT_CARD_PATHS:
            resp = httpx.get(
                f"{base}{card_path}", timeout=TIMEOUT, follow_redirects=True
            )
            if resp.status_code == 404:
                last_status_code = resp.status_code
                continue
            resp.raise_for_status()
            raw = resp.json()
            break

        if raw is None:
            return ValidationResult(
                ok=False, step="agent_card",
                error=(
                    f"agent card not found ({last_status_code or 404}) — "
                    f"does the agent expose one of: {', '.join(AGENT_CARD_PATHS)}?"
                )
            )
    except httpx.ConnectError:
        return ValidationResult(
            ok=False, step="agent_card",
            error=f"connection refused — is the agent running at {url}?"
        )
    except httpx.TimeoutException:
        return ValidationResult(
            ok=False, step="agent_card",
            error=f"timeout after {TIMEOUT}s — agent did not respond"
        )
    except httpx.HTTPStatusError as e:
        return ValidationResult(
            ok=False, step="agent_card",
            error=(
                f"agent card not found ({e.response.status_code}) — "
                f"does the agent expose one of: {', '.join(AGENT_CARD_PATHS)}?"
            )
        )
    except Exception as e:
        return ValidationResult(ok=False, step="agent_card", error=str(e))
    

    # Etapa 2: validação de schema A2A 
    # obs: usamos basicamente o modelo que ja temos definido em axon/types.py 
    try:
        card = AgentCard.model_validate(raw)
    except ValidationError as e:
        missing = [str(err["loc"][-1]) for err in e.errors()]
        return ValidationResult(
            ok=False, step="schema",
            error=f"invalid agent card schema — missing or invalid fields: {missing}"
        )
    
    # Etapa 3: verificação do token Axon 
    axon_meta = card.axon
 
    if axon_meta is None:
        return ValidationResult(
            ok=False, step="axon_token",
            error=(
                "missing Axon extension in agent card.\n"
                "  generate a token first:\n"
                "    axon token generate --name <agent-name>\n"
                "  then add it to your agent card in capabilities.extensions:\n"
                '    "capabilities": {\n'
                '      "extensions": [{\n'
                f'        "uri": "{AXON_EXTENSION_URI}",\n'
                '        "params": {\n'
                '          "token": "axon_tk_...",\n'
                '          "registry_id": "local",\n'
                '          "protocol_version": "0.1"\n'
                '        }\n'
                '      }]\n'
                '    }'
            )
        )
 
    if not axon_meta.token.startswith(AXON_TOKEN_PREFIX):
        return ValidationResult(
            ok=False, step="axon_token",
            error=(
                f'invalid token format — token must start with "{AXON_TOKEN_PREFIX}".\n'
                f"\n"
                f"  If you are registering with a local Gateway:\n"
                f"    axon token generate --name <agent-name>\n"
                f"\n"
                f"  If you are registering with an external Gateway provider:\n"
                f"    request a token from the Gateway operator you want to register with.\n"
                f"    the token will be issued by their registry and must be placed in\n"
                f"    your agent card under capabilities.extensions:\n"
                f"\n"
                f'      "uri": "{AXON_EXTENSION_URI}",\n'
                f'      "params": {{\n'
                f'        "token": "axon_tk_...",\n'
                f'        "registry_id": "<gateway-id>",\n'
                f'        "registry_url": "<gateway-verify-url>"\n'
                f'      }}\n'
            )
        )
 
    if axon_meta.protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
        return ValidationResult(
            ok=False, step="axon_protocol",
            error=(
                f"protocol version mismatch — "
                f"agent declares v{axon_meta.protocol_version}, "
                f"axon supports {sorted(SUPPORTED_PROTOCOL_VERSIONS)}"
            )
        )
 
    token_err = _verify_token(axon_meta)
    if token_err is not None:
        return ValidationResult(
            ok=False, step="axon_token",
            error=str(token_err)
        )
    
    # Etapa 4: Fingerprint 

    fp = fingerprint(raw)

    # Tudo ocorreu corretamente na validação e retornamos uma Validação com ok True

    return ValidationResult(
        ok=True,
        agent_card=card,
        fingerprint=fp,
        verified_token=axon_meta.token,
    )
