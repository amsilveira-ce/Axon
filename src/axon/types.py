from __future__ import annotations

from enum import Enum
from datetime import datetime, timezone
from typing import Literal
from pydantic import AliasChoices, BaseModel, Field, model_validator
from typing import Any


class OperationalMode(str, Enum):
    agent   = "agent"
    copilot = "copilot"
    no_llm  = "no-llm"


class ReasoningMode(str, Enum):
    react = "react"
    rewoo = "rewoo"
    tot   = "tot"


class ResourceType(str, Enum):
    agent = "agent"
    mcp   = "mcp"


class ResourceStatus(str, Enum):
    online     = "online"
    offline    = "offline"
    validating = "validating"
    failed     = "failed"


class TokenStatus(str, Enum):
    """
    Ciclo de vida de um token emitido pelo registry local.

    pending  → emitido, ainda não consumido por nenhum registro
    used     → consumido (max_uses atingido)
    revoked  → revogado explicitamente — rejeitado em novos registros
    """
    pending = "pending"
    used    = "used"
    revoked = "revoked"


class AxonToken(BaseModel):
    """
    Estrutura de um token dentro da framework do Axon (axon_tk_<payload>).

    AxonToken = o recurso se autentica perante o GA no registro.
    Diferente do AuthConfig = o PA se autentica perante o recurso na execução.
    """
    token:        str
    name:         str
    registry_id:  str            = "local"
    registry_url: str | None     = None
    created_at:   datetime       = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at:   datetime | None = None
    max_uses:     int | None     = 1
    use_count:    int            = 0
    status:       TokenStatus    = TokenStatus.pending
    used_by:      str | None     = None


class TokenStore(BaseModel):
    """Conteúdo de .axon/ga/{context}/tokens.json."""
    version: str            = "0.1.0"
    tokens:  list[AxonToken] = Field(default_factory=list)


class AgentExtension(BaseModel):
    """Extensão de protocolo declarada no AgentCard — spec A2A 1.0."""
    uri:         str
    required:    bool            = False
    description: str | None     = None
    params:      dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


# URIs canônicas das extensões Axon
AXON_EXTENSION_URI         = "https://axon-framework.dev/extensions/registry/v1"
AXON_GATEWAY_EXTENSION_URI = "axon-framework.dev/extensions/gateway/v1"


class A2ASkill(BaseModel):
    """
    Skill declarada no agent card A2A.
    O GA usa description e tags para retrieval semântico.
    """
    id:          str
    name:        str | None = None
    description: str
    tags:        list[str]  = Field(default_factory=list)
    examples:    list[str]  = Field(default_factory=list)
    inputModes:  list[str]  = Field(
        default_factory=list,
        validation_alias=AliasChoices("inputModes", "input_modes"),
    )
    outputModes: list[str]  = Field(
        default_factory=list,
        validation_alias=AliasChoices("outputModes", "output_modes"),
    )

    model_config = {"extra": "allow"}


class A2ACapabilities(BaseModel):
    """Capacidades declaradas no AgentCard — spec A2A 1.0."""
    streaming:              bool                 = False
    pushNotifications:      bool                 = False
    stateTransitionHistory: bool                 = False
    extensions:             list[AgentExtension] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class AxonMetadata(BaseModel):
    """
    Extensão Axon no AgentCard.

    AxonToken que o recurso apresenta ao GA no registro.
    GA verifica contra tokens.json (local) ou POST /verify-token (externo).
    """
    token:            str
    registry_id:      str        = "local"
    registry_url:     str | None = None
    protocol_version: str        = "0.1"

    model_config = {"extra": "allow"}


class GatewayAxonMetadata(BaseModel):
    """
    Extensão Axon declarada no GatewayCard.capabilities.extensions.

    trust_level:
        "local"   → GA operado pela própria organização — confiança máxima
        "vendor"  → GA de vendor com SLA conhecido
        "unknown" → padrão — PA emite warning ao conectar
    """
    axon_version:    str
    organization:    str | None                            = None
    trust_level:     Literal["local", "vendor", "unknown"] = "unknown"
    resources_count: int                                   = 0
    accepted_types:  list[str]                             = Field(default_factory=list)
    requires_token:  bool                                  = False

    model_config = {"extra": "allow"}


class A2AInterface(BaseModel):
    protocol_binding: str = Field(
        validation_alias=AliasChoices("protocol_binding", "protocolBinding")
    )
    url: str

    model_config = {"extra": "allow"}


class AgentCard(BaseModel):
    """Agent Card padrão A2A 1.0."""
    name:               str
    description:        str
    url:                str | None = None
    version:            str
    skills:             list[A2ASkill]
    capabilities:       A2ACapabilities = Field(default_factory=A2ACapabilities)
    defaultInputModes:  list[str]       = Field(
        default_factory=lambda: ["text/plain"],
        validation_alias=AliasChoices("defaultInputModes", "default_input_modes"),
    )
    defaultOutputModes: list[str]       = Field(
        default_factory=lambda: ["text/plain"],
        validation_alias=AliasChoices("defaultOutputModes", "default_output_modes"),
    )
    supported_interfaces: list[A2AInterface] = Field(
        default_factory=list,
        validation_alias=AliasChoices("supported_interfaces", "supportedInterfaces"),
    )

    model_config = {"extra": "allow", "populate_by_name": True}

    @property
    def axon(self) -> AxonMetadata | None:
        for ext in self.capabilities.extensions:
            if ext.uri == AXON_EXTENSION_URI:
                try:
                    return AxonMetadata.model_validate(ext.params)
                except Exception:
                    return None
        return None


class GatewayCard(BaseModel):
    """
    Cartão de identidade do Gateway Agent — exposto em GET /ga/card.

    Base A2A + extensão Axon via property .axon.
    """
    name:         str
    description:  str             = ""
    url:          str
    version:      str             = "0.1.0"
    capabilities: A2ACapabilities = Field(default_factory=A2ACapabilities)

    model_config = {"extra": "allow"}

    @property
    def axon(self) -> GatewayAxonMetadata | None:
        for ext in self.capabilities.extensions:
            if ext.uri == AXON_GATEWAY_EXTENSION_URI:
                try:
                    return GatewayAxonMetadata.model_validate(ext.params)
                except Exception:
                    return None
        return None


class Resource(BaseModel):
    """Recurso registrado no GA (.axon/ga/{context}/registry.json)."""
    id:               str
    type:             ResourceType
    protocol_binding: ProtocolBinding
    name:             str
    endpoint:         str
    description:      str
    skills:           list[A2ASkill] | None = Field(default_factory=list)
    fingerprint:      str
    token_ref:        str | None    = None
    registered_at:    datetime      = Field(default_factory=lambda: datetime.now(timezone.utc))
    status:           ResourceStatus = ResourceStatus.online


class RegistryFile(BaseModel):
    """Conteúdo de .axon/ga/{context}/registry.json."""
    version:   str            = "0.1.0"
    resources: list[Resource] = Field(default_factory=list)


class ProtocolBinding(str, Enum):
    """Transporte de comunicação do recurso."""
    # A2A
    JSONRPC   = "JSONRPC"
    GRPC      = "GRPC"
    HTTP_JSON = "HTTP_JSON"
    # MCP
    MCP_HTTP  = "mcp_http"
    MCP_SSE   = "mcp_sse"
    MCP_STDIO = "mcp_stdio"


class AuthScheme(str, Enum):
    """
    Esquema de autenticação do PA perante o recurso na execução.

    Separado do AxonToken — que autentica o recurso perante o GA no registro.
    AxonToken = recurso → GA (registro)
    AuthConfig = PA → recurso (execução)
    """
    none    = "none"
    bearer  = "bearer"    # Authorization: Bearer {token}
    api_key = "api_key"   # {header}: {token}


class AuthConfig(BaseModel):
    """
    Configuração de autenticação do PA perante o recurso.

    O token nunca é armazenado aqui — é resolvido em runtime pelo TokenResolver
    via variável de ambiente (convenção: AXON_SECRET_{NAME_UPPER}).
    """
    scheme:  AuthScheme = AuthScheme.none
    header:  str | None = None
    env_var: str | None = None   # None → TokenResolver infere pela convenção


class ResourcePolicy(BaseModel):
    """
    Política declarada pelo recurso — lida pelo GA no registro e
    armazenada no ResourceManifest.

    O GA não interpreta essa política — ele apenas a persiste.
    É o Resolver do PA que filtra recursos com base nela,
    combinando com a ResourcePolicyConfig do operador.

    is_paid:       o recurso cobra por chamada?
    requires_auth: o recurso exige autenticação?
    cost_per_call: custo estimado em USD por chamada (None = desconhecido)
    """
    is_paid:       bool         = False
    requires_auth: bool         = False
    cost_per_call: float | None = None


class ResourceManifest(BaseModel):
    """
    Contrato de execução de um recurso — retornado pelo GA ao PA.

    Contém tudo que o PA precisa para chamar o recurso sem consultar
    o GA novamente. O Executor recebe apenas ResourceManifests
    já filtrados por política e com token resolvido.

    callable_by:
        "pa_direct" → PA chama diretamente (A2A, MCP HTTP/SSE)
        "ga_proxy"  → GA executa em nome do PA (MCP stdio)
    """
    resource_id:      str
    name:             str
    type:             ResourceType
    protocol_binding: ProtocolBinding
    description:      str                             = ""
    capability_tags:  list[str]                       = Field(default_factory=list)
    callable_by:      Literal["pa_direct", "ga_proxy"]

    # como chamar
    endpoint:         str | None             = None   # A2A e MCP HTTP/SSE
    command:          list[str] | None       = None   # MCP stdio
    ga_url:           str | None             = None   # ga_proxy
    a2a_capabilities: A2ACapabilities | None = None

    # política declarada pelo recurso
    policy: ResourcePolicy = Field(default_factory=ResourcePolicy)

    # autenticação — token resolvido em runtime pelo TokenResolver
    auth: AuthConfig = Field(default_factory=AuthConfig)

    # métricas de qualidade e cache
    match_score:   float          = 0.0
    last_used:     datetime | None = None
    success_count: int             = 0
    failure_count: int             = 0

    @model_validator(mode="after")
    def validate_fields_by_type(self) -> "ResourceManifest":
        if self.callable_by == "ga_proxy":
            assert self.ga_url,      "ga_proxy requer ga_url"
            assert self.resource_id, "ga_proxy requer resource_id"
        elif self.type == ResourceType.agent:
            assert self.endpoint,    "agent requer endpoint"
        elif self.type == ResourceType.mcp:
            if self.protocol_binding == ProtocolBinding.MCP_STDIO:
                assert self.command, "mcp_stdio requer command"
            else:
                assert self.endpoint, f"{self.protocol_binding} requer endpoint"
        return self