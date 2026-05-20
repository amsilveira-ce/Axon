from __future__ import annotations
 
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, ClassVar
import os
from pydantic import BaseModel, Field
 
from axon.types import OperationalMode, ReasoningMode

# ==============================================
#   caminho default do arquivo de configuração
# ==============================================

CONFIG_FILENAME = "axon.config.json"

 
# ======================================================
#   data_dir — resolvido em runtime
#
#   Prioridade:
#     1. AXON_DATA_DIR (env var)          → produção / container
#     2. axon.config.json → data_dir      → operador configurou explicitamente
#     3. ".axon"                          → default dev local
#
#   Uso:
#     from axon.config import paths
#     p = paths()                         # usa cwd implícito
#     p = paths(cwd=Path("/app"))         # override
#     p.ga_registry                       # Path resolvido
# ======================================================

_ENV_DATA_DIR = "AXON_DATA_DIR"


 
class AxonPaths:
    """
    Todos os paths do projeto derivados de um único data_dir.
 
    Nunca construa paths manualmente fora desta classe —
    registry.py, tokens.py e conversation.py importam daqui.
    """
 
    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir
 
        # GA
        self.ga_dir      = data_dir / "ga"
        self.ga_registry = data_dir / "ga" / "registry.json"    #guarda recursos que foram registrados no GA 
        self.ga_tokens   = data_dir / "ga" / "tokens.json"
        self.ga_traces   = data_dir / "ga" / "traces"
 
        # PA
        self.pa_dir            = data_dir / "pa"
        self.pa_sessions       = data_dir / "pa" / "sessions"
        self.pa_resource_cache = data_dir / "pa" / "resource_cache.json"
        self.pa_memory_bank    = data_dir / "pa" / "memory_bank.json"
        self.pa_traces         = data_dir / "pa" / "traces"
 
    def makedirs(self) -> None:
        """Cria toda a estrutura de diretórios (idempotente)."""
        for d in (
            self.ga_dir,
            self.ga_traces,
            self.pa_dir,
            self.pa_sessions,
            self.pa_traces,
        ):
            d.mkdir(parents=True, exist_ok=True)
 
def resolve_data_dir(config_data_dir: str | None = None, cwd: Path | None = None,) -> Path:
    """
    Resolve o data_dir seguindo a ordem de prioridade:
      1. AXON_DATA_DIR env var  (absoluto ou relativo ao cwd)
      2. config.data_dir        (valor do axon.config.json)
      3. ".axon"                (default dev local, relativo ao cwd)
    """
    base = cwd or Path.cwd()
 
    env = os.environ.get(_ENV_DATA_DIR)
    if env:
        p = Path(env)
        return p if p.is_absolute() else base / p
 
    if config_data_dir:
        p = Path(config_data_dir)
        return p if p.is_absolute() else base / p
 
    return base / ".axon"
 

# ============================
#   Modelos de configuração
# ============================

# Adicionar LLMConfig e atualizar PAConfig
#
# 1. Novo modelo — adicione antes de PAConfig:
 
class LLMConfig(BaseModel):
    host:        str   = "http://localhost:11434"
    model:       str   = "llama3.2"
    timeout:     int   = 300    # segundos por request
    temperature: float = 0.0
 

# obs:Por serem models relacionados ao arquivo de configuração eles ficam aqui por hora 

class GatewayEntry(BaseModel):
    id: str
    url: str 
    added_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PAConfig(BaseModel):
    port: int = 4100
    llm: LLMConfig = Field(default_factory=LLMConfig)
    default_mode: OperationalMode = OperationalMode.agent 
    default_reasoning_mode: ReasoningMode = ReasoningMode.react
    gateways: list[GatewayEntry] = Field(default_factory=list)
    max_iterations: int = 10 
    cache: bool = True 

class MCPConfig(BaseModel):
    """
    Configurações de segurança e isolamento para execução de tools MCP.
 
    allowed_env_vars:
        Whitelist de variáveis de ambiente que podem ser injetadas em
        processos stdio. O executor rejeita silenciosamente qualquer
        var declarada no manifesto que não esteja nessa lista.
 
        Isso impede que um manifesto malicioso ou mal configurado
        exponha variáveis sensíveis do ambiente do host (ex: AWS_SECRET,
        HOME, PATH) para o processo MCP.
 
        Adicione aqui apenas as vars que os seus MCPs realmente precisam.
 
    stdio_timeout:
        Tempo máximo (segundos) para o processo stdio responder a uma
        chamada tools/call. Processos que excedem o timeout são encerrados.
 
    http_timeout:
        Tempo máximo (segundos) para requests HTTP a servidores MCP remotos.
    """
    allowed_env_vars: list[str] = Field(default_factory=list)
    stdio_timeout:    int       = 30
    http_timeout:     int       = 10

class GAConfig(BaseModel):
    """
    Configuração do Gateway Agent.
 
    registry_path:        caminho do arquivo .axon/registry.json.
    mcp:                  configurações de segurança para tools MCP.
    registered_resources: referências leves aos recursos registrados.
                          Atualizado automaticamente pelo axon add agent/mcp.
                          Permite ao PA operator saber o que está disponível
                          sem acesso direto ao registry.json do GA.
    """
    port:                 int              = 5000
    registry_path:        str              = ".axon/registry.json"
    mcp:                  MCPConfig        = Field(default_factory=MCPConfig)
    registered_resources: list[ResourceRef] = Field(default_factory=list)

class ResourceRef(BaseModel):
    """
    Referência leve a um recurso registrado no GA.
 
    Persiste no axon.config.json para que o PA operator saiba quais
    recursos existem no GA sem precisar ler o registry.json diretamente.
 
    Em ambientes com múltiplos operadores (PA e GA separados), essa
    referência é o que o PA operator consulta para saber o que está
    disponível no GA que ele conectou.
 
    resource_id:  id gerado no momento do registro (res-xxxxxx)
    name:         nome do agente ou tool
    type:         "agent" | "mcp"
    endpoint:     URL do agente ou comando do stdio
    registered_at: timestamp do registro
    """
    resource_id:   str
    name:          str
    type:          str
    endpoint:      str
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AxonConfig(BaseModel):
    # Configuração do Axon básica envolve configurar o Principal Agent e Gateway Agent 
    # esses objetos criam a concepção do axon.config.json
    version: str      = "0.1.0"
    pa:      PAConfig = Field(default_factory=PAConfig)
    ga:      GAConfig = Field(default_factory=GAConfig)


# ===================================================
#  Metodos para lidar com o arquivo de configuração
# ===================================================


def config_path(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / CONFIG_FILENAME
 
 
def config_exists(cwd: Path | None = None) -> bool:
    return config_path(cwd).exists()

def read_config(cwd: Path | None = None)-> AxonConfig:
    p = config_path(cwd)
    if not p.exists():
        raise FileNotFoundError(
            f'axon.config.json not found. Run "axon init" to create one.'
        )
    return AxonConfig.model_validate(json.loads(p.read_text(encoding="utf-8")))

def write_config(config: AxonConfig, cwd: Path | None = None) -> None:
    p = config_path(cwd)
    p.write_text(
        config.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

def patch_config(fn: Callable[[AxonConfig], AxonConfig],cwd: Path | None = None,) -> AxonConfig:
    updated = fn(read_config(cwd))
    write_config(updated, cwd)
    return updated
