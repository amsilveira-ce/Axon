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
 
 
 
class Resource(BaseModel):
    """
    Recurso registrado no Gateway (.axon/registry.json).
 
    Representa tanto agentes A2A quanto tools MCP de forma unificada.
    O campo type discrimina o comportamento do GA no momento do retrieval
    e execução.
 
    Campos de rastreabilidade:
      fingerprint: SHA-256 do agent card canônico no momento do registro.
                   Permite detectar drift de configuração no ping contínuo.
      token_ref:   valor do token que autorizou o registro.
                   None = token foi verificado e consumido (não armazenamos
                   o valor por segurança). Str = apenas para diagnóstico
                   interno, nunca exposto via CLI.
 
    Skills são preservadas do agent card para uso pelo GA no retrieval
    semântico — o PA descreve a subtarefa em linguagem natural e o GA
    ranqueia recursos por correspondência com skills.description e tags.
    """
    id:            str
    type:          ResourceType
    name:          str
    endpoint:      str
    description:   str
    skills:        list[A2ASkill] = Field(default_factory=list)
    fingerprint:   str
    token_ref:     str | None = None
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status:        ResourceStatus = ResourceStatus.online
 
 
class RegistryFile(BaseModel):
    """Conteúdo de .axon/ga/{context}/registry.json."""
    version:   str            = "0.1.0"
    resources: list[Resource] = Field(default_factory=list)


 
class ResourceManifest(BaseModel):
    """
    Referência leve a um recurso — usado pelo PA para execução.
 
    Mais enxuto que Resource (registro completo do GA).
    O GA retorna ResourceManifests no retrieval; o PA os usa para executar.
 
    callable_by:
        "pa_direct"  → PA chama via MCPClient diretamente (tools locais)
        "ga_proxy"   → PA chama via GA (recursos remotos registrados)
 
    transport:
        "stdio"      → processo local via stdin/stdout
        "http"       → endpoint HTTP remoto
    """
 
    id:              str
    name:            str
    description:     str
    capability_tags: list[str]                        = Field(default_factory=list)
    callable_by:     Literal["pa_direct", "ga_proxy"] = "ga_proxy"
    transport:       Literal["stdio", "http"]         = "http"
    command:         list[str] | None                 = None   # stdio
    endpoint:        str | None                       = None   # http
 