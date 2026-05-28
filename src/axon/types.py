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
 

# Configurações relacionados aos recursos 
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
    Estrutura de um token dentro da framework do Axon, o token segue a
    estrutura axon_tk_<payload>

    registry_id e registry_url servem para responder a pergunta "quem 
    emitiu esse token e onde verificar se ele é valido", no MVP o registry_id
    é preenchdio como "local" e portanto a checagem é feita no .axon/tokens.json

    Em um cenário onde um vendor gerou esse token, nós teriamos o registry_id
    algo como "google-agent-gateway" e o registry_url serviria para validar se
    esse token foi realmente gerado pelo vendo. 
 
    Para registries externos (vendor), registry_id != "local" e o CLI
    chamará POST {registry_url}/verify-token para validar — o formato do
    token e o contrato de verificação são idênticos, só o destino muda.

    Para o MVP no CLI não vamos dar suporte para flag de expiração do token
    mas o cenário foi sim mapeado e fica algo como: 
        axon token generate --name meu-agent --expires 24 #expira em 24h
 
    Campos:
      token:        valor do token (axon_tk_<urlsafe random>)
      name:         nome declarado ao gerar — identifica o recurso alvo
      registry_id:  "local" | id do vendor 
      registry_url: None para local; endpoint /verify-token para externos
      max_uses:     1 = uso único (padrão); None = ilimitado
      use_count:    quantas vezes foi consumido
      used_by:      id do resource que consumiu (quando status=used)
    """
    token:        str
    name:         str

    registry_id:  str = "local"
    registry_url: str | None = None

    created_at:   datetime = Field(default_factory=lambda: datetime.now(timezone.utc)) # preenchido automaticamente com o pydantic 
    expires_at:   datetime | None = None # None por hora é permitido para poder ocorrer testes com um unico token

    max_uses:     int | None = 1 # permite um registro, um token por registro 
    use_count:    int = 0   # controlar o uso desse token 
    status:       TokenStatus = TokenStatus.pending # quando um token é criado ele recebe o statul de pending = "disponivel para uso"
    used_by:      str | None = None 
 
 
class TokenStore(BaseModel):
    """Conteúdo de .axon/tokens.json."""
    version: str = "0.1.0"
    tokens:  list[AxonToken] = Field(default_factory=list)


class AgentExtension(BaseModel):
    """
    Extensão de protocolo declarada no AgentCard — spec A2A 1.0.
 
    Conforme a especificação oficial, extensões são declaradas em
    AgentCapabilities.extensions como objetos AgentExtension.
    A URI identifica globalmente a extensão; params carrega os dados.
 
    Referência: https://a2a-protocol.org/latest/topics/extensions/
    """
    uri:         str
    required:    bool                = False
    description: str | None         = None
    params:      dict[str, Any]     = Field(default_factory=dict)
 
    model_config = {"extra": "allow"}
 
 
# URI canônica da extensão Axon — identifica globalmente o registry Axon
AXON_EXTENSION_URI = "https://axon-framework.dev/extensions/registry/v1"

class A2ASkill(BaseModel):
    """
    Skill declarada no agent card A2A.
 
    Representa uma capacidade atômica do agente. O GA usa description e tags
    para retrieval semântico — quando o PA envia uma query descrevendo uma
    subtarefa, o GA ranqueia recursos por similaridade com esses campos.
    """
    id:          str
    name:        str | None = None
    description: str
    tags:        list[str] = Field(default_factory=list)
    examples:    list[str] = Field(default_factory=list)
    inputModes:  list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("inputModes", "input_modes"),
    )
    outputModes: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("outputModes", "output_modes"),
    )
 
    model_config = {"extra": "allow"}
 
 
class A2ACapabilities(BaseModel):
    """
    Capacidades declaradas no AgentCard.
 
    extensions: lista de AgentExtension — mecanismo oficial da spec A2A 1.0
                para extensões de protocolo de terceiros.
                O Axon declara sua extensão aqui com uri=AXON_EXTENSION_URI.
    """
    streaming:              bool                 = False
    pushNotifications:      bool                 = False
    stateTransitionHistory: bool                 = False
    extensions:             list[AgentExtension] = Field(default_factory=list)
 
    model_config = {"extra": "allow"}
 
 
class AxonMetadata(BaseModel):
    """
    Extensão Axon declarada em AgentCard.metadata["axon"].
 
    Posicionada em metadata conforme a especificação A2A, que reserva esse
    campo para extensões de terceiros sem alterar as estruturas core do
    protocolo. Clientes A2A que não conhecem o Axon ignoram metadata["axon"].
 
    token:            valor emitido pelo registry antes do registro.
                      Verificado contra .axon/tokens.json (local) ou
                      via POST {registry_url}/verify-token (externo).
    registry_id:      "local" | id do vendor que emitiu o token.
    registry_url:     None para local; endpoint de verificação para externos.
    protocol_version: versão do protocolo Axon que o agente suporta.
    """
    token:            str
    registry_id:      str = "local"
    registry_url:     str | None = None
    protocol_version: str = "0.1"
 
    model_config = {"extra": "allow"}


class A2AInterface(BaseModel):
    protocol_binding: str = Field(
        validation_alias=AliasChoices("protocol_binding", "protocolBinding")
    )
    url: str

    model_config = {"extra": "allow"}
 
 
class AgentCard(BaseModel):
    """
    Agent Card padrão A2A 1.0.
 
    A extensão Axon é declarada em capabilities.extensions conforme a
    especificação oficial — não em metadata. Clientes A2A que não conhecem
    o Axon simplesmente ignoram a extensão desconhecida.
 
    A property .axon localiza a extensão Axon em capabilities.extensions
    e retorna os params como AxonMetadata, ou None se ausente.
 
    Referência: https://a2a-protocol.org/latest/specification/#agentcard
    """
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
        """
        Localiza e retorna a extensão Axon declarada em capabilities.extensions.
 
        Busca por uri == AXON_EXTENSION_URI. Retorna None se não encontrada
        ou se os params não forem válidos como AxonMetadata.
        """
        for ext in self.capabilities.extensions:
            if ext.uri == AXON_EXTENSION_URI:
                try:
                    return AxonMetadata.model_validate(ext.params)
                except Exception:
                    return None
        return None
 
 
 
class Resource(BaseModel):
    id:               str
    type:             ResourceType
    protocol_binding: ProtocolBinding      # vem do AgentCard.supported_interfaces
    
    name:             str
    endpoint:         str
    description:      str
    skills:           list[A2ASkill] | None = Field(default_factory=list)
    fingerprint:      str
    token_ref:        str | None = None
    registered_at:    datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status:           ResourceStatus = ResourceStatus.online

class RegistryFile(BaseModel):
    """Conteúdo de .axon/registry.json."""
    version:   str = "0.1.0"
    resources: list[Resource] = Field(default_factory=list)


class ProtocolBinding(str, Enum):
    """
    Transporte de comunicação do recurso.
    Para agentes A2A: JSONRPC, GRPC, HTTP_JSON.
    Para ferramentas MCP: MCP_HTTP, MCP_SSE, MCP_STDIO.
    """
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
    """
    none    = "none"
    bearer  = "bearer"    # Authorization: Bearer {token}
    api_key = "api_key"   # {header}: {token}


class AuthConfig(BaseModel):
    """
    Configuração de autenticação do PA perante o recurso.

    O token nunca é armazenado aqui — é resolvido em runtime
    via variável de ambiente pelo TokenResolver antes de cada chamada.

    scheme:  esquema esperado pelo recurso — inferido do agent card ou manifesto MCP
    header:  nome do header HTTP: "Authorization", "X-Api-Key", etc.
    env_var: variável de ambiente que contém o token
             None → TokenResolver infere como AXON_SECRET_{NAME_UPPER}
    """
    scheme:  AuthScheme = AuthScheme.none
    header:  str | None = None
    env_var: str | None = None


class ResourceManifest(BaseModel):
    """
    Contrato de execução de um recurso.
    Contém tudo que os clientes (A2AClient, MCPClient) precisam
    para chamar o recurso sem consultar o GA novamente.
    """
    resource_id:      str
    name:             str
    type:             ResourceType          # "agent" | "mcp"
    protocol_binding: ProtocolBinding       # transporte efetivo — vem do AgentCard/registro
    description:      str = ""
    capability_tags:  list[str] = Field(default_factory=list)
    callable_by:      Literal["pa_direct", "ga_proxy"]

    # agent (A2A) — pa_direct
    endpoint:         str | None = None
    a2a_capabilities: A2ACapabilities | None = None

    # mcp (HTTP / SSE) — pa_direct
    # endpoint já cobre — protocol_binding distingue MCP_HTTP de MCP_SSE

    # mcp stdio local do PA — pa_direct
    command:          list[str] | None = None

    # ga_proxy
    ga_url:           str | None = None

    # metadata de qualidade e cache
    match_score:      float = 0.0
    last_used:        datetime | None = None
    success_count:    int = 0
    failure_count:    int = 0

    # autenticação do PA perante o recurso — resolvida em runtime
    auth:             AuthConfig = Field(default_factory=AuthConfig)

    @model_validator(mode="after")
    def validate_fields_by_type(self) -> "ResourceManifest":
        if self.callable_by == "ga_proxy":
            assert self.ga_url,       "ga_proxy requer ga_url"
            assert self.resource_id,  "ga_proxy requer resource_id"
        elif self.type == ResourceType.agent:
            assert self.endpoint,     "agent requer endpoint"
        elif self.type == ResourceType.mcp:
            if self.protocol_binding == ProtocolBinding.MCP_STDIO:
                assert self.command,  "mcp_stdio requer command"
            else:
                assert self.endpoint, f"{self.protocol_binding} requer endpoint"
        return self