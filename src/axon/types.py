from __future__ import annotations

from enum import Enum
from datetime import datetime, timezone
from pydantic import BaseModel, Field, Any


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

