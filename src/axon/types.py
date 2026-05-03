from __future__ import annotations

from enum import Enum
from datetime import datetime, timezone
from pydantic import BaseModel, Field, Any
# ======================================================
# Modos Operacionais e Estratégias de Raciocínio
# ======================================================

# Este módulo define os modos de operação do Principal Agent (PA)
# e as estratégias de raciocínio utilizadas durante a execução de tarefas.
#
# A separação entre "modo operacional" e "modo de raciocínio" é uma decisão
# de projeto que permite desacoplar:
# - COMO o agente interage com o usuário (interface/comportamento)
# - COMO o agente resolve o problema internamente (estratégia de execução)


# ------------------------------------------------------
# OperationalMode
# ------------------------------------------------------
# Define o comportamento externo do sistema e o nível de autonomia do agente.

class OperationalMode(str, Enum):
    agent   = "agent"
    copilot = "copilot"
    no_llm  = "no-llm"


# ------------------------------------------------------
# ReasoningMode
# ------------------------------------------------------
# Define a estratégia de raciocínio utilizada pelo agente durante a execução.
# Esses modos afetam diretamente como tarefas são decompostas e resolvidas.
class ReasoningMode(str, Enum):
    react = "react"
    rewoo = "rewoo"
    # tot   = "tot"

# ======================================================
# Objetos relacionados com os recursos dentro do Axon
# ======================================================
# Um recurso no Axon representa qualquer entidade externa invocável pelo Principal Agent.
# Isso inclui tanto ferramentas (via MCP) quanto agentes especializados (via A2A).
#
# Recursos são definidos como todos os componentes externos ao Principal Agent,
# excluindo os Gateway Agents, que atuam apenas como intermediários de descoberta e roteamento.
#
# Dessa forma, recursos constituem a camada funcional do sistema, responsável pela
# execução efetiva de tarefas delegadas.

class ResourceType(str, Enum):
    agent = "agent"
    mcp   = "mcp"

class ResourceStatus(str, Enum):
    online     = "online"
    offline    = "offline"
    validating = "validating"
    failed     = "failed"

# ======================================================
# A2A Agent Card
# ======================================================

# Este módulo segue o schema oficial do protocolo A2A:
# https://a2a-protocol.org/latest/specification/
#
# A validação de recursos do tipo agente A2A é realizada com base
# nas informações contidas no Agent Card, obtido a partir do endpoint:
# /.well-known/agent.json
#
# O processo consiste em:
# 1. Realizar o fetch do Agent Card exposto pelo agente
# 2. Validar os campos essenciais (ex: name, version, skills)
# 3. A partir dessa validação, registrar o agente como um recurso válido no sistema
#
# Para suportar esse processo, são definidos objetos que representam:
# - Skill: capacidades específicas que o agente pode executar
# - Capability: abstrações de funcionalidades expostas pelo agente
#
# Esses elementos estruturam a forma como agentes A2A são descritos,
# descobertos e integrados à framework.

class A2ASkill(BaseModel):
    id:          str
    name:        str | None = None
    description: str
    tags:        list[str] = Field(default_factory=list)
    examples:    list[str] = Field(default_factory=list)
    inputModes:  list[str] = Field(default_factory=list)
    outputModes: list[str] = Field(default_factory=list)

class A2ACapabilities(BaseModel):
    streaming:              bool = False
    pushNotifications:      bool = False
    stateTransitionHistory: bool = False

# ======================================================
# Agent Card / Axon token
# ======================================================

# Para fins de registro e autenticação dentro do Axon, é utilizado o conceito de "axon.token",
# análogo a uma API Key.
#
# O axon.token tem como objetivo garantir que o agente:
# - declarou explicitamente sua participação no ecossistema Axon
# - teve seu Agent Card validado pela framework (incluindo formato e versão do protocolo)
# - possui um identificador único associado ao seu estado no momento do registro
#
# Durante o processo de registro, é gerado um fingerprint baseado em SHA-256
# a partir do conteúdo do Agent Card. Esse fingerprint permite:
# - identificar unicamente o agente
# - detectar alterações no Agent Card ao longo do tempo
# - assegurar integridade e rastreabilidade do recurso registrado
#
# Dessa forma, o axon.token atua como um mecanismo leve de identificação,
# validação e versionamento de agentes dentro da framework.

class AxonExtension(BaseModel):
    """Extensão Axon obrigatória no agent card para registro."""
    token:            str        # prefixo axon_tk_
    protocol_version: str = "0.1"
    input_schema:     dict[str, Any] = Field(default_factory=dict)
    output_schema:    dict[str, Any] = Field(default_factory=dict)
 
class AgentCard(BaseModel):
    """Agent Card padrão A2A com extensão Axon."""
    name:             str
    description:      str
    url:              str
    version:          str
    skills:           list[A2ASkill]
    capabilities:     A2ACapabilities = Field(default_factory=A2ACapabilities)
    defaultInputModes:  list[str] = Field(default_factory=lambda: ["text/plain"])
    defaultOutputModes: list[str] = Field(default_factory=lambda: ["text/plain"])
    axon:             AxonExtension | None = None  # None = agente sem extensão Axon
 
    model_config = {"populate_by_name": True}

# ======================================================
# Resource Registry Model
# ======================================================

# O objeto Resource representa a unidade básica de registro dentro do Axon.
# Ele abstrai qualquer entidade externa invocável pelo Principal Agent,
# incluindo tanto agentes A2A quanto ferramentas integradas via MCP.
#
# Este modelo define a identidade, capacidades e metadados necessários
# para descoberta, validação e execução de recursos no sistema.

# OBS:
# Este modelo está sujeito a evolução conforme novos tipos de recursos 
# e mecanismos de validação sejam incorporados à framework.


class Resource(BaseModel):
    id:            str
    type:          ResourceType
    name:          str
    endpoint:      str
    description:   str
    skills:        list[A2ASkill] = Field(default_factory=list)
    input_schema:  dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    fingerprint:   str                      # sha256 do agent card canônico
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status:        ResourceStatus = ResourceStatus.online