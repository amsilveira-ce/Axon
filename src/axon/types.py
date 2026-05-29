from __future__ import annotations

from enum import Enum
from datetime import datetime, timezone
from typing import Literal
from pydantic import AliasChoices, BaseModel, Field
from typing import Any

 
# URI - para extender o card do gateway agent e dos recursos 
AXON_EXTENSION_URI = "https://axon-framework.dev/extensions/registry/v1"
AXON_GATEWAY_EXTENSION_URI = "axon-framework.dev/extensions/gateway/v1"


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
    """Conteúdo de .axon/registry.json."""
    version:   str = "0.1.0"
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
 

class GatewayAxonMetadata(BaseModel):
    """
    Extensão Axon declarada no GatewayCard.capabilities.extensions.
 
    Carrega os campos específicos do ecossistema Axon que um cliente A2A
    genérico ignoraria — mas que o PA usa para avaliar confiança e capacidades.
 
    trust_level:
        "local"   → GA operado pela própria organização — confiança máxima
        "vendor"  → GA de vendor com SLA conhecido (Azure, Google, etc.)
        "unknown" → padrão — PA emite warning ao conectar
    """
    axon_version: str 
    organization: str | None 
    trust_level: Literal["local", "vendor", "unkown"]
    resources_count: int 
    accepted_types: list[str]
    requires_token: bool 

    # model_config = {}


class GatewayCard(BaseModel):
    """
    Cartão de identidade do Gateway Agent — exposto em GET /ga/card.
 
    Base A2A — interoperável com qualquer cliente do protocolo A2A.
    Extensão Axon — campos específicos acessíveis via property .axon.
 
    O mesmo padrão do AgentCard: vendors que já expõem agent cards A2A
    podem adicionar a extensão axon-framework.dev/extensions/gateway/v1
    e ser reconhecidos automaticamente pelo PA.
    """
    name:         str
    description:  str                  = ""
    url:          str
    version:      str                  = "0.1.0"
    capabilities: A2ACapabilities      = Field(default_factory=A2ACapabilities)
 
    model_config = {"extra": "allow"}
 
    @property
    def axon(self) -> GatewayAxonMetadata | None:
        """
        Localiza a extensão Axon em capabilities.extensions.
        Retorna None se não encontrada — gateway sem extensão Axon.
        """
        for ext in self.capabilities.extensions:
            if ext.uri == AXON_GATEWAY_EXTENSION_URI:
                try:
                    return GatewayAxonMetadata.model_validate(ext.params)
                except Exception:
                    return None
        return None
 