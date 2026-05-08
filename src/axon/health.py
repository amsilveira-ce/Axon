"""
health.py — verificação de saúde de recursos registrados.
 
Estratégia por tipo de recurso:
 
  agent (A2A):
    GET /.well-known/agent.json
      → se responde: servidor está no ar
      → compara fingerprint: detecta drift de configuração
    Sem side effects. É o mesmo mecanismo que o A2A Inspector oficial usa.
 
  mcp / stdio:
    Não tem servidor para pingar — o processo só existe durante a execução.
    Verificação de saúde não é aplicável. Status permanece como está.
 
  mcp / http:
    GET no endpoint declarado em resource.endpoint.
    Qualquer resposta HTTP confirma que o servidor está no ar.
    Fingerprint baseado em tools/list seria mais rigoroso, mas requer
    iniciar uma sessão MCP — overkill para um health check. Usamos
    apenas conectividade por ora.
"""
import httpx
from dataclasses import dataclass
from axon.types import Resource, ResourceStatus
from axon.validator import fingerprint as calc_fingerprint, AGENT_CARD_PATH, TIMEOUT


@dataclass
class HealthResult:
    status:      ResourceStatus
    reachable:   bool
    fingerprint_match: bool | None   # None = não aplicável (mcp stdio)
    error:       str | None = None
    new_fingerprint: str | None = None  # fingerprint atual se houve drift

def check_agent(resource: Resource) -> HealthResult:
    """
    Verifica um agente A2A via GET /.well-known/agent.json.
 
    Retorna:
      status=online       → responde e fingerprint bate
      status=offline      → não responde ou erro HTTP
      status=validating   → responde mas fingerprint diverge (drift detectado)
    """
    base = resource.endpoint.rstrip("/")

    try:
        resp = httpx.get(
            f"{base}{AGENT_CARD_PATH}",
            timeout=TIMEOUT,
            follow_redirects=True,
        )
        resp.raise_for_status()
        raw: dict = resp.json()
    except httpx.ConnectError:
        return HealthResult(
            status=ResourceStatus.offline,
            reachable=False,
            fingerprint_match=None,
            error="connection refused",
        )
    except httpx.TimeoutException:
        return HealthResult(
            status=ResourceStatus.offline,
            reachable=False,
            fingerprint_match=None,
            error=f"timeout after {TIMEOUT}s",
        )
    except httpx.HTTPStatusError as e:
        return HealthResult(
            status=ResourceStatus.offline,
            reachable=False,
            fingerprint_match=None,
            error=f"HTTP {e.response.status_code}",
        )
    except Exception as e:
        return HealthResult(
            status=ResourceStatus.offline,
            reachable=False,
            fingerprint_match=None,
            error=str(e),
        )

     # Servidor respondeu — compara fingerprint
    current_fp = calc_fingerprint(raw)
    matches     = current_fp == resource.fingerprint
 
    if matches:
        return HealthResult(
            status=ResourceStatus.online,
            reachable=True,
            fingerprint_match=True,
        )
    else:
        return HealthResult(
            status=ResourceStatus.validating,
            reachable=True,
            fingerprint_match=False,
            new_fingerprint=current_fp,
            error=(
                f"agent card changed since registration — re-run 'axon add agent' to update.\n"
                f"  saved:   {resource.fingerprint}\n"
                f"  current: {current_fp}"
            ),
        )


def check_mcp_http(resource: Resource) -> HealthResult:
    """
    Verifica um servidor MCP HTTP via conectividade simples.
 
    Qualquer resposta HTTP confirma que o servidor está no ar.
    Não iniciamos uma sessão MCP completa — apenas verificamos conectividade.
    """
    url = resource.endpoint.rstrip("/")
 
    try:
        httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
        return HealthResult(
            status=ResourceStatus.online,
            reachable=True,
            fingerprint_match=None,
        )
    except httpx.ConnectError:
        return HealthResult(
            status=ResourceStatus.offline,
            reachable=False,
            fingerprint_match=None,
            error="connection refused",
        )
    except httpx.TimeoutException:
        return HealthResult(
            status=ResourceStatus.offline,
            reachable=False,
            fingerprint_match=None,
            error=f"timeout after {TIMEOUT}s",
        )
    except Exception as e:
        return HealthResult(
            status=ResourceStatus.offline,
            reachable=False,
            fingerprint_match=None,
            error=str(e),
        )
    
def check_mcp_stdio(resource: Resource) -> HealthResult:
    """
    MCP stdio não tem servidor para pingar — não aplicável.
 
    O processo só existe durante a execução de uma tool call.
    Poderíamos verificar se o comando existe no PATH, mas isso é
    responsabilidade do executor no momento da chamada.
    """
    return HealthResult(
        status=resource.status,    # preserva o status atual
        reachable=True,            # assumimos disponível — sem como verificar
        fingerprint_match=None,
        error=None,
    )


def check(resource: Resource) -> HealthResult:
    """
    Despacha para o verificador correto baseado no tipo e transport do resource.
 
    Para MCP, infere o transport a partir do endpoint:
      - começa com http:// ou https:// → http
      - qualquer outra coisa → stdio (command)
    """
    from axon.types import ResourceType
 
    if resource.type == ResourceType.agent:
        return check_agent(resource)
 
    # MCP — infere transport pelo endpoint
    ep = resource.endpoint
    if ep.startswith("http://") or ep.startswith("https://"):
        return check_mcp_http(resource)
    else:
        return check_mcp_stdio(resource)