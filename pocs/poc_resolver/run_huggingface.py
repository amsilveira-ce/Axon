"""
poc_resolver/run_huggingface.py

Demonstra o roadmap do Resolver usando o **contexto Hugging Face** da
documentação (docs/mcp-resources.md): um MCP server `bearer`/`header` em
https://huggingface.co/mcp, com o segredo em HF_TOKEN.

Auto-contido: o Gateway Agent é simulado por um stub que devolve o recurso HF
(o transporte HTTP/retrieval do GA já é validado em outros pocs). O foco aqui é
mostrar TODAS as etapas do Resolver — pool local, ranking UCB + broadcast,
filtro de política (auth) e a atribuição final — sem depender de Ollama nem de
um token real.

Dois cenários:
  A) HF_TOKEN ausente   → Step 4 (token) descarta o recurso, fail-fast
  B) HF_TOKEN presente  → recurso elegível, atribuído à subtask

Rodar:
  python pocs/poc_resolver/run_huggingface.py
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager

from axon.config import ResourcePolicyConfig
from axon.pa.ga_affinity import GAAffinityStore
from axon.pa.models import AgentState, Plan, ResolverResult, Subtask
from axon.pa.resolver import Resolver, ResolverError
from axon.types import (
    AuthConfig, AuthLocation, AuthScheme,
    ProtocolBinding, ResourceManifest, ResourcePolicy, ResourceType,
)

GA_URL  = "http://hf-gateway.local"
HF_NAME = "huggingface"

# Recurso Hugging Face exatamente como em docs/mcp-resources.md:
#   mcp_http · bearer · Authorization: Bearer hf_… · segredo em HF_TOKEN
HF_MANIFEST = ResourceManifest(
    resource_id="res-hf",
    name=HF_NAME,
    type=ResourceType.mcp,
    protocol_binding=ProtocolBinding.MCP_HTTP,
    description="Hugging Face MCP — model/dataset/paper search and docs semantic search",
    capability_tags=["models", "datasets", "papers", "search"],
    callable_by="pa_direct",
    endpoint="https://huggingface.co/mcp",
    auth=AuthConfig(scheme=AuthScheme.bearer, location=AuthLocation.header, env_var="HF_TOKEN"),
    policy=ResourcePolicy(is_paid=False, requires_auth=True, cost_per_call=None),
)


class StubHFGateway:
    """GA simulado: encontra o recurso HF para a capability pedida."""
    def __init__(self, ga_url: str) -> None:
        self.ga_url = ga_url

    def search(self, *, query, capability, subtask_id, max_results=5):
        return ResolverResult(
            capability=capability, subtask_id=subtask_id,
            manifest=HF_MANIFEST, alternatives=[],
            ga_url=self.ga_url, match_score=0.62, latency_ms=28.0,
        )


@contextmanager
def capture(name: str):
    """Captura as mensagens INFO de um logger durante o bloco."""
    lines: list[str] = []

    class H(logging.Handler):
        def emit(self, record): lines.append(record.getMessage())

    lg, h = logging.getLogger(name), H()
    lg.addHandler(h); prev = lg.level; lg.setLevel(logging.INFO)
    try:
        yield lines
    finally:
        lg.removeHandler(h); lg.setLevel(prev)


def fresh_state() -> AgentState:
    s = AgentState(raw_query="find trending text-generation models on Hugging Face")
    s.plan = Plan(subtasks=[Subtask(
        id="s1",
        description="search Hugging Face for trending text-generation models",
        capability_required="models",
    )])
    s.resource_pool = []   # pool local vazio → força o Step 2 (GA)
    return s


def run_scenario(label: str, policy: ResourcePolicyConfig) -> None:
    print(f"\n{'='*68}\n{label}\n{'='*68}")
    state    = fresh_state()
    affinity = GAAffinityStore()
    resolver = Resolver(
        gateways=[GA_URL],
        affinity=affinity,
        policy=policy,
        client_factory=StubHFGateway,
    )

    with capture("axon.pa.resolver") as steps:
        try:
            resolver.resolve(state)
            err = None
        except ResolverError as e:
            err = e

    print("\n[ etapas do Resolver ]")
    for line in steps:
        print("   ", line)

    print("\n[ assignments ]")
    rr = state.resource_assignments.get("s1")
    if rr:
        print(f"    s1 (cap=models) → {rr.manifest.name} via {rr.ga_url} "
              f"| match={rr.match_score} | {rr.latency_ms:.0f}ms")
    else:
        print("    s1 (cap=models) → UNRESOLVED")

    print("\n[ gateway affinity (UCB) ]")
    for ga, caps in affinity._table.items():
        for cap, e in caps.items():
            print(f"    {ga} [{cap}] queries={e.query_count} reward={e.reward_mean:.3f}")

    if err:
        print(f"\n[ ResolverError ] {str(err).splitlines()[0]}")


def main() -> None:
    # política do operador: recursos pagos proibidos
    policy = ResourcePolicyConfig(allow_paid=False)

    # Cenário A — HF_TOKEN ausente
    os.environ.pop("HF_TOKEN", None)
    run_scenario("A) HF_TOKEN ausente — Step 4 descarta o recurso (token, fail-fast)", policy)

    # Cenário B — HF_TOKEN presente
    os.environ["HF_TOKEN"] = "hf_demo_token_xxxxxxxxxxxxxxxxxxxx"
    run_scenario("B) HF_TOKEN presente — recurso elegível, atribuído", policy)
    os.environ.pop("HF_TOKEN", None)


if __name__ == "__main__":
    main()
