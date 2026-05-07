from __future__ import annotations
 
import json
from pathlib import Path
 
from axon.config import read_config
from axon.types import Resource, RegistryFile, ResourceStatus
# Este módulo é responsável pela persistência e gerenciamento
# dos recursos registrados no Gateway Agent (GA).
#
# O arquivo `.axon/registry.json` atua como o repositório local
# de recursos, armazenando metadados necessários para descoberta,
# validação e execução de agentes e ferramentas.
# ------------------------------------------------------
# Decisões de Projeto
# ------------------------------------------------------
# - Persistência em arquivo JSON:
#   Permite simplicidade, versionamento e fácil inspeção.
#
# - Escopo do Gateway Agent:
#   O GA é responsável pelo ciclo de vida dos recursos,
#   atuando como ponto de registro e indexação.
#
# - Re-registro idempotente:
#   Ao adicionar um recurso existente, o registro anterior
#   é substituído, evitando duplicidade.
#

# ======================================================
# Caminho do arquivo de registry
# ======================================================

def _registry_path(cwd: Path | None = None) -> Path:
    config = read_config(cwd)
    return (cwd or Path.cwd()) / config.ga.registry_path
 
# ======================================================
# Operações de leitura e escrita
# ======================================================
def read_registry(cwd: Path | None = None) -> RegistryFile:
    p = _registry_path(cwd)
    if not p.exists():
        return RegistryFile()
    return RegistryFile.model_validate(json.loads(p.read_text(encoding="utf-8")))
 
 
def write_registry(registry: RegistryFile, cwd: Path | None = None) -> None:
    p = _registry_path(cwd)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(registry.model_dump_json(indent=2) + "\n", encoding="utf-8")
 
# ======================================================
# Operações de gerenciamento de recursos
# ======================================================

def add_resource(resource: Resource, cwd: Path | None = None) -> None:
    """
    Adiciona ou substitui um resource no registry.
 
    Re-registro: se já existe um resource com o mesmo NOME, ele é
    removido antes de adicionar o novo — garantindo unicidade de nome.
    O novo resource carrega seu próprio ID (gerado pelo chamador).
 
    Não permite dois recursos com o mesmo nome — nome é chave única.
    """
    registry = read_registry(cwd)


    # Remove qualquer resource com o mesmo nome (unicidade de nome)
    # Não filtra por ID — o novo resource já vem com seu próprio ID
    registry.resources = [r for r in registry.resources if r.name != resource.name]
    registry.resources.append(resource)
    write_registry(registry, cwd)
 



 
def remove_resource(name: str, cwd: Path | None = None) -> Resource | None:
    """
    Remove o resource com o nome exato informado.
 
    Retorna o resource removido, ou None se não encontrado.
    Remove exatamente um recurso — nome é chave única, portanto
    nunca há mais de um com o mesmo nome no registry.
    """
    registry = read_registry(cwd)
    target = next((r for r in registry.resources if r.name == name), None)
    if target:
        # Remove por ID — garante que apenas esse resource específico é afetado
        registry.resources = [r for r in registry.resources if r.id != target.id]
        write_registry(registry, cwd)
    return target


def remove_resource_by_id(resource_id: str, cwd: Path | None = None) -> Resource | None:
    """
    Remove o resource com o ID exato informado.
 
    Preferir este método quando o chamador já tem o ID — é mais preciso
    do que remove_resource pois não depende da unicidade de nome.
    """
    registry = read_registry(cwd)
    target = next((r for r in registry.resources if r.id == resource_id), None)
    if target:
        registry.resources = [r for r in registry.resources if r.id != resource_id]
        write_registry(registry, cwd)
    return target


def get_resource(name_or_id: str, cwd: Path | None = None) -> Resource | None:
    """
    Busca um resource por nome ou ID.
 
    ID tem prioridade — se o valor corresponder a um ID existente,
    retorna esse resource mesmo que outro tenha o mesmo nome.
    """
    registry = read_registry(cwd)
    # Prioridade: ID exato primeiro, depois nome
    by_id = next((r for r in registry.resources if r.id == name_or_id), None)
    if by_id:
        return by_id
    return next((r for r in registry.resources if r.name == name_or_id), None)
 
 
def list_resources(cwd: Path | None = None) -> list[Resource]:
    return read_registry(cwd).resources


def update_status(resource_id: str, status: str, cwd: Path | None = None) -> None:
    """
    Atualiza o status de um resource em-place, identificado por ID.
 
    Sempre opera por ID — nunca por nome — para evitar ambiguidade.
    """
    from axon.types import ResourceStatus
    registry = read_registry(cwd)
    for r in registry.resources:
        if r.id == resource_id:
            r.status = ResourceStatus(status)
            break
    write_registry(registry, cwd)
 
 
def update_resource_status(
    resource_id: str,
    status: ResourceStatus,
    cwd: Path | None = None,
) -> None:
    """Alias tipado de update_status — aceita ResourceStatus diretamente."""
    update_status(resource_id, status.value, cwd)
 