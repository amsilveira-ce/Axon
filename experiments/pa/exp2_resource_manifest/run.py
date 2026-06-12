"""
Experiment 2 (PA) — ResourceManifest as the execution contract

Integration test of the PA's three clients. Each path calls a real
protocol-correct mock server using ONLY a hand-built ResourceManifest —
no Agent Card fetch, no GA discovery:

  Path 1 — A2A (pa_direct)
    PA → A2AClient → JSON-RPC message/send → mock A2A server (a2a SDK)

  Path 2 — MCP HTTP (pa_direct)
    PA → MCPClient → MCP streamable HTTP → mock FastMCP server
         TokenResolver injects the Bearer header from the env var;
         the mock REJECTS unauthenticated handshakes (401), so success
         proves the credential chain end to end.

  Path 3 — ga_proxy (stdio)
    PA → GAClient → POST /ga/resources/{id}/invoke → real GA (uvicorn)
         → GA spawns the stdio subprocess and returns the result.

Everything is self-contained: the GA runs in-process against an isolated
temp context; all servers bind to 127.0.0.1.

Run:
    uv run experiments/pa/exp2_resource_manifest/run.py
    uv run experiments/pa/exp2_resource_manifest/run.py --skip-ga-proxy
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT      = Path(__file__).parents[3]
EXPERIMENT_DIR = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(EXPERIMENT_DIR))

from manifests import (   # noqa: E402
    A2A_PORT, GA_PORT, MCP_ENV_VAR, MCP_PORT, STDIO_RES_ID,
    a2a_manifest, ga_proxy_manifest, mcp_http_manifest,
)

MCP_TOKEN = "test_token_exp2"


# ── path 1: A2A via pa_direct ────────────────────────────────────────────────

def test_a2a_path(state) -> tuple[bool, str]:
    """A2AClient calls a live A2A agent from the manifest alone."""
    from axon.pa.clients.a2a_client import A2AClient
    from axon.pa.models import Fact, Provenance

    manifest = a2a_manifest()
    result   = asyncio.run(
        A2AClient().call(
            manifest,
            task="Review this function: def add(a, b): return a + b",
        )
    )
    if not result:
        return False, "A2AClient returned empty result"

    fact = Fact(
        subtask_id="s1",
        tool=manifest.name,
        output=result,
        provenance=Provenance.A2A,
    )
    state.facts.append(fact)

    ok = fact.provenance == Provenance.A2A and "review" in result.lower()
    return ok, f"Fact(provenance=a2a, len={len(result)})"


# ── path 2: MCP HTTP via pa_direct + TokenResolver ───────────────────────────

def test_mcp_http_path(state) -> tuple[bool, str]:
    """
    MCPClient calls an auth-protected MCP HTTP tool from the manifest.

    Two sub-checks:
      negative — without the env var the handshake must fail (401)
      positive — with the env var, TokenResolver injects the Bearer header
    """
    from axon.pa.clients.mcp_client import MCPClient, MCPTransportError
    from axon.pa.models import Fact, Provenance
    from axon.token_resolver import resolve

    manifest = mcp_http_manifest()

    # negative: no credential configured → resolver yields None → server 401s
    os.environ.pop(MCP_ENV_VAR, None)
    if resolve(manifest) is not None:
        return False, "TokenResolver resolved a credential that should not exist"
    try:
        asyncio.run(MCPClient.call_once(
            manifest, "check_interactions", {"drug_a": "a", "drug_b": "b"},
        ))
        return False, "call succeeded WITHOUT credentials — auth gate broken"
    except MCPTransportError:
        pass   # expected: 401 at the MCP handshake

    # positive: credential in env → TokenResolver builds the Bearer header
    os.environ[MCP_ENV_VAR] = MCP_TOKEN
    resolved = resolve(manifest)
    if resolved is None or resolved.value != f"Bearer {MCP_TOKEN}":
        return False, f"TokenResolver mis-resolved: {resolved!r}"

    result = asyncio.run(MCPClient.call_once(
        manifest, "check_interactions",
        {"drug_a": "metformin", "drug_b": "losartan"},
    ))
    if not result:
        return False, "MCPClient returned empty result"

    fact = Fact(
        subtask_id="s2",
        tool=manifest.name,
        output=result,
        provenance=Provenance.MCP,
    )
    state.facts.append(fact)

    ok = "interaction" in str(result).lower()
    return ok, "Fact(provenance=mcp, token_resolved=True, 401_without_token=True)"


# ── path 3: stdio via ga_proxy ────────────────────────────────────────────────

def test_ga_proxy_path(state, ga_url: str) -> tuple[bool, str]:
    """GAClient delegates to the GA, which spawns the stdio subprocess."""
    from axon.pa.clients.ga_client import GAClient
    from axon.pa.models import Fact, Provenance

    manifest = ga_proxy_manifest(ga_url=ga_url)
    client   = GAClient(ga_url=manifest.ga_url)

    body = client.invoke(
        resource_id=manifest.resource_id,
        tool="search_patient",
        params={"name": "João Silva"},
        pa_id="pa-exp2-test",
        task="look up patient João Silva",
    )
    if body.get("status") != "ok":
        return False, f"GA returned status={body.get('status')!r}"

    fact = Fact(
        subtask_id="s3",
        tool=manifest.name,
        output=body["result"],
        provenance=Provenance.MCP,
    )
    state.facts.append(fact)

    ok = "João" in json.dumps(body["result"], ensure_ascii=False)
    return ok, "Fact(provenance=mcp, via=ga_proxy, subprocess=GA-side)"


# ── self-contained GA ─────────────────────────────────────────────────────────

def start_ga(tmp: Path) -> None:
    """
    Boot the REAL GA (uvicorn, daemon thread) against an isolated temp
    context, with the stdio mock registered — same resolution chain as
    `axon ga serve` (axon.config.json + AXON_GA_CONTEXT).
    """
    from axon.config import AxonConfig, GAInstanceConfig, write_config
    from axon.ga.config import GAPaths
    from axon.ga.registry import add_resource
    from axon.types import (
        A2ASkill, ProtocolBinding, Resource, ResourceStatus, ResourceType,
    )

    ga_dir = tmp / "ga"
    paths  = GAPaths(ga_dir)
    paths.makedirs()
    paths.registry.write_text('{"version": "0.1.0", "resources": []}\n')
    paths.tokens.write_text('{"version": "0.1.0", "tokens": []}\n')

    write_config(AxonConfig(
        gateways={"exp2pa": GAInstanceConfig(name="exp2pa", data_dir=str(ga_dir))},
        current_gateway="exp2pa",
    ), cwd=tmp)

    stdio_script = EXPERIMENT_DIR / "servers" / "mock_stdio_server.py"
    add_resource(Resource(
        id=STDIO_RES_ID,
        type=ResourceType.mcp,
        protocol_binding=ProtocolBinding.MCP_STDIO,
        name="mock-health-search",
        command=["python", str(stdio_script)],
        description="Mock health search stdio tool",
        skills=[
            A2ASkill(id="search_patient",    description="Search patient records by name", tags=["health", "patient"]),
            A2ASkill(id="get_prescriptions", description="Get active prescriptions",       tags=["health", "prescriptions"]),
        ],
        fingerprint=f"sha256:{secrets.token_hex(8)}",
        status=ResourceStatus.online,
    ), paths)

    os.environ["AXON_GA_CONTEXT"] = "exp2pa"
    os.chdir(tmp)   # GAConfig.resolve() reads axon.config.json from cwd

    import uvicorn
    from axon.ga.server import app
    config = uvicorn.Config(app, host="127.0.0.1", port=GA_PORT, log_level="error")
    threading.Thread(target=uvicorn.Server(config).run, daemon=True).start()


# ── reporter ──────────────────────────────────────────────────────────────────

def print_results(results: list[tuple[str, str, bool, str]]) -> bool:
    sep = "─" * 76
    print()
    print("  exp2 — ResourceManifest as the execution contract")
    print(f"  {sep}")
    print(f"  {'Path':<16} {'Client':<11} {'Result':<7} Detail")
    print(f"  {sep}")
    for name, client, ok, detail in results:
        mark = "✓" if ok else "✗"
        print(f"  {name:<16} {client:<11} {mark:<7} {detail}")
    print(f"  {sep}")
    passed, total = sum(1 for _, _, ok, _ in results if ok), len(results)
    print(f"  {passed}/{total} passed")
    print()
    return passed == total


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-ga-proxy", action="store_true",
                        help="skip path 3 (no GA boot, no stdio subprocess)")
    args = parser.parse_args()

    from axon.pa.models import AgentState, Provenance
    state   = AgentState()
    old_cwd = os.getcwd()
    old_ctx = os.environ.get("AXON_GA_CONTEXT")

    print("  starting mock servers …", flush=True)
    sys.path.insert(0, str(EXPERIMENT_DIR / "servers"))
    from servers.mock_a2a_server import start as start_a2a
    from servers.mock_mcp_http_server import start as start_mcp
    start_a2a(port=A2A_PORT)
    start_mcp(port=MCP_PORT)

    results: list[tuple[str, str, bool, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        try:
            if not args.skip_ga_proxy:
                start_ga(Path(tmp))
            time.sleep(1.5)   # let uvicorn servers bind

            def run(label, client, fn, *fn_args):
                try:
                    ok, detail = fn(state, *fn_args)
                except Exception as exc:
                    ok, detail = False, f"{type(exc).__name__}: {exc}"
                results.append((label, client, ok, detail))

            run("a2a_path",      "A2AClient", test_a2a_path)
            run("mcp_http_path", "MCPClient", test_mcp_http_path)
            if not args.skip_ga_proxy:
                run("ga_proxy_path", "GAClient", test_ga_proxy_path,
                    f"http://127.0.0.1:{GA_PORT}")
            else:
                print("  ga_proxy: skipped (--skip-ga-proxy)")
        finally:
            os.chdir(old_cwd)
            if old_ctx is None:
                os.environ.pop("AXON_GA_CONTEXT", None)
            else:
                os.environ["AXON_GA_CONTEXT"] = old_ctx

    all_passed = print_results(results)

    # key invariant: every Fact was produced from a manifest, with provenance
    assert all(f.provenance in (Provenance.A2A, Provenance.MCP) for f in state.facts)
    expected_facts = 2 if args.skip_ga_proxy else 3
    assert len(state.facts) == expected_facts, (
        f"expected {expected_facts} facts, got {len(state.facts)}"
    )

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
