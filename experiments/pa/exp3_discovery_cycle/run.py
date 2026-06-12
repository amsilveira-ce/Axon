"""
Experiment 3 (PA) — Resolver: known resources, local tools, and the
discovery cycle.

Seven cases drive the REAL Resolver + Executor (no LLM — hand-built plans)
against live servers, showcasing every selection path:

  step 1 (local pool)   01 local tool wins; called via MCPClient (stdio)
  step 1 (cache)        02 resource known from a "previous run"; A2AClient
  step 1 (pool order)   03 local tool beats a cached remote with the same capability
  step 1 (history)      04 success_count ranking picks the reliable candidate
  step 2 (GA search)    05 unknown capability → GA discovery → ga_proxy invoke
  discovery cycle       06 re-run: resolved from cache, ZERO GA queries
  executor tool_cache   07 duplicate call in one run answered from tool_cache

The three execution clients all appear: MCPClient (01/03/07), A2AClient
(02/04), GAClient via ga_proxy (05/06). Everything is self-contained: the
GA is the real axon.ga.server.app under uvicorn in an isolated temp context.

Run:
    uv run experiments/pa/exp3_discovery_cycle/run.py
"""
from __future__ import annotations

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
SERVERS_DIR    = EXPERIMENT_DIR / "servers"
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(EXPERIMENT_DIR))

A2A_PORT = 18091
GA_PORT  = 18093
GA_URL   = f"http://127.0.0.1:{GA_PORT}"


# ── counting GA client — proves WHEN the Resolver goes to the network ─────────

class CountingGAFactory:
    """client_factory for the Resolver that counts /ga/resources/search calls."""

    def __init__(self) -> None:
        self.searches = 0

    def __call__(self, ga_url: str):
        from axon.pa.clients.ga_client import GAClient

        factory = self
        class _Counting(GAClient):
            def search(self, **kw):
                factory.searches += 1
                return super().search(**kw)
        return _Counting(ga_url)


# ── fixtures: local tools, seeded cache, GA with one registered resource ──────

def write_local_tools(tmp: Path) -> Path:
    """local_tools.json — consumed by the real LocalResourcePool.load()."""
    path = tmp / "local_tools.json"
    path.write_text(json.dumps({
        "tools": [
            {
                "name":        "calculator",
                "capability":  "calculation",
                "description": "Evaluate arithmetic expressions locally",
                "transport":   "stdio",
                "command":     ["python", str(SERVERS_DIR / "tool_calculator.py")],
                "tool":        "calculate",
            },
            {
                "name":        "weather",
                "capability":  "weather",
                "description": "Local weather lookup",
                "transport":   "stdio",
                "command":     ["python", str(SERVERS_DIR / "tool_weather.py")],
                "tool":        "get_weather",
            },
        ]
    }, indent=2), encoding="utf-8")
    return path


def seed_cache(tmp: Path):
    """
    ResourceCache pre-seeded as if a previous run had discovered these via GA.

    - mock-code-review   A2A agent, capability code_review            (case 02)
    - cloud-weather      remote MCP HTTP, DEAD endpoint, cap weather  (case 03 loser)
    - flaky-reviewer     A2A, doc_review, history 0 ok / 4 failed     (case 04 loser)
    - senior-reviewer    A2A, doc_review, history 5 ok / 1 failed     (case 04 winner)

    flaky-reviewer is put BEFORE senior-reviewer so pool order alone would
    pick the flaky one — only the history ranking flips the choice.
    """
    from axon.pa.resource_cache import ResourceCache
    from axon.types import AuthConfig, ProtocolBinding, ResourceManifest, ResourceType

    cache = ResourceCache(path=tmp / "resource_cache.json", resources=[])

    cache.put(ResourceManifest(
        resource_id="res-prev-code-review",
        name="mock-code-review",
        type=ResourceType.agent,
        protocol_binding=ProtocolBinding.JSONRPC,
        description="Code review agent discovered via GA in a previous run",
        capability_tags=["code_review"],
        callable_by="pa_direct",
        endpoint=f"http://127.0.0.1:{A2A_PORT}/",
        auth=AuthConfig(),
    ))
    cache.put(ResourceManifest(
        resource_id="res-prev-cloud-weather",
        name="cloud-weather",
        type=ResourceType.mcp,
        protocol_binding=ProtocolBinding.MCP_HTTP,
        description="Remote weather MCP — endpoint is DEAD; must never be dialed",
        capability_tags=["weather"],
        callable_by="pa_direct",
        endpoint="http://127.0.0.1:9/mcp",     # nothing listens here
        auth=AuthConfig(),
    ))
    cache.put(ResourceManifest(
        resource_id="res-prev-flaky-reviewer",
        name="flaky-reviewer",
        type=ResourceType.agent,
        protocol_binding=ProtocolBinding.JSONRPC,
        description="Document reviewer with a bad track record",
        capability_tags=["doc_review"],
        callable_by="pa_direct",
        endpoint=f"http://127.0.0.1:{A2A_PORT}/",
        auth=AuthConfig(),
        success_count=0,
        failure_count=4,
    ))
    cache.put(ResourceManifest(
        resource_id="res-prev-senior-reviewer",
        name="senior-reviewer",
        type=ResourceType.agent,
        protocol_binding=ProtocolBinding.JSONRPC,
        description="Document reviewer with a solid track record",
        capability_tags=["doc_review"],
        callable_by="pa_direct",
        endpoint=f"http://127.0.0.1:{A2A_PORT}/",
        auth=AuthConfig(),
        success_count=5,
        failure_count=1,
    ))
    return cache


def start_ga(tmp: Path) -> None:
    """
    Boot the REAL GA (uvicorn, daemon thread) against an isolated temp context
    with ONE registered resource: the patient-search MCP stdio server. Its
    skill tags carry the capability the Resolver will ask for in case 05.
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
        gateways={"exp3pa": GAInstanceConfig(name="exp3pa", data_dir=str(ga_dir))},
        current_gateway="exp3pa",
    ), cwd=tmp)

    add_resource(Resource(
        id="res-exp3-patient",
        type=ResourceType.mcp,
        protocol_binding=ProtocolBinding.MCP_STDIO,
        name="patient-search",
        command=["python", str(SERVERS_DIR / "mock_patient_stdio.py")],
        description="Patient record lookup tool (stdio)",
        skills=[A2ASkill(
            id="search_patient",
            description="Search patient records by name",
            tags=["patient_records", "health"],
        )],
        fingerprint=f"sha256:{secrets.token_hex(8)}",
        status=ResourceStatus.online,
    ), paths)

    os.environ["AXON_GA_CONTEXT"] = "exp3pa"
    os.chdir(tmp)   # GAConfig.resolve() reads axon.config.json from cwd

    import uvicorn
    from axon.ga.server import app
    config = uvicorn.Config(app, host="127.0.0.1", port=GA_PORT, log_level="error")
    threading.Thread(target=uvicorn.Server(config).run, daemon=True).start()


# ── pipeline plumbing (mirrors agent.py, minus the LLM stages) ────────────────

class Runner:
    """One PA 'instance': local pool + cache shared across runs, like agent.py."""

    def __init__(self, tmp: Path) -> None:
        from axon.pa.ga_affinity import GAAffinityStore
        from axon.pa.local_pool import LocalResourcePool

        self.local_pool    = LocalResourcePool.load(write_local_tools(tmp))
        self.cache         = seed_cache(tmp)
        self.affinity_path = tmp / "ga_affinity.json"
        self.affinity      = GAAffinityStore.load(self.affinity_path)

    def run(self, subtasks: list) -> tuple["object", CountingGAFactory]:
        """
        One full run: fresh AgentState (pool = local + cache, same assembly as
        agent.py), real Resolver (steps 1-4) and real Executor (steps 1-8).
        """
        from axon.pa.executor import Executor
        from axon.pa.models import AgentState, Objective, Plan
        from axon.pa.resolver import Resolver

        state = AgentState(raw_query="exp3", objective=Objective(goal="exp3"))
        state.plan          = Plan(subtasks=subtasks)
        state.resource_pool = self.local_pool.tools + self.cache.all()

        factory  = CountingGAFactory()
        resolver = Resolver(
            gateways=[GA_URL],
            affinity=self.affinity,
            affinity_path=self.affinity_path,
            cache=self.cache,
            client_factory=factory,
        )
        executor = Executor(
            affinity=self.affinity,
            affinity_path=self.affinity_path,
            pa_id="pa-exp3",
        )

        resolver.resolve(state)
        executor.execute(state)
        return state, factory


def subtask(id: str, description: str, capability: str, params: dict | None = None):
    from axon.pa.models import Subtask
    return Subtask(
        id=id,
        description=description,
        capability_required=capability,
        params_template=params or {},
    )


# ── the seven cases ───────────────────────────────────────────────────────────
# each returns (capability, resolved_via, client, ok, detail)

def case_01_local_tool(r: Runner):
    """Capability covered by a local tool → step 1, called via MCPClient stdio."""
    from axon.pa.models import Provenance

    state, ga = r.run([subtask(
        "s1", "calculate the expression 21*2", "calculation",
        {"expression": "21*2"},
    )])
    a, f = state.resource_assignments["s1"], state.get_fact("s1")
    ok = (
        a.ga_url == ""
        and a.manifest.resource_id == "local-calculator"
        and f is not None
        and f.provenance == Provenance.LOCAL
        and f.output.get("result") == 42
        and ga.searches == 0
    )
    return "calculation", "step1 · local pool", "MCPClient", ok, \
        f"local-calculator → 21*2 = {f.output.get('result') if f else '—'} · 0 GA queries"


def case_02_cached_agent(r: Runner):
    """Capability known from a previous run's cache → step 1, A2A round-trip."""
    from axon.pa.models import Provenance

    state, ga = r.run([subtask(
        "s1", "review this function: def add(a, b): return a + b", "code_review",
    )])
    a, f = state.resource_assignments["s1"], state.get_fact("s1")
    ok = (
        a.ga_url == ""
        and a.manifest.resource_id == "res-prev-code-review"
        and f is not None
        and f.provenance == Provenance.A2A          # cache hit must STAY a2a
        and "review" in str(f.output).lower()
        and ga.searches == 0
    )
    return "code_review", "step1 · cache", "A2AClient", ok, \
        f"mock-code-review (known from previous run) · provenance={f.provenance.value if f else '—'} · 0 GA queries"


def case_03_local_beats_cached(r: Runner):
    """Local tool and cached remote share a capability → pool order picks local."""
    from axon.pa.models import Provenance

    state, ga = r.run([subtask(
        "s1", "what is the weather in Curitiba", "weather",
        {"city": "Curitiba"},
    )])
    a, f = state.resource_assignments["s1"], state.get_fact("s1")
    ok = (
        a.manifest.resource_id == "local-weather"   # not the dead cloud-weather
        and f is not None
        and f.provenance == Provenance.LOCAL
        and f.output.get("source") == "local-weather"
        and ga.searches == 0
    )
    return "weather", "step1 · local pool", "MCPClient", ok, \
        "local-weather beat cached cloud-weather (dead endpoint never dialed)"


def case_04_history_ranking(r: Runner):
    """Two known candidates → success_count desc, failure_count asc decides."""
    state, ga = r.run([subtask(
        "s1", "review the quarterly report document", "doc_review",
    )])
    a, f = state.resource_assignments["s1"], state.get_fact("s1")
    ok = (
        a.manifest.name == "senior-reviewer"        # beats flaky despite pool order
        and f is not None
        and "review" in str(f.output).lower()
        and ga.searches == 0
    )
    return "doc_review", "step1 · cache+history", "A2AClient", ok, \
        "senior-reviewer (5 ok/1 fail) beat flaky-reviewer (0 ok/4 fail)"


def case_05_ga_discovery(r: Runner):
    """Unknown capability → step 2: GA search → ga_proxy invoke → cached."""
    from axon.pa.models import Provenance

    state, ga = r.run([subtask(
        "s1", "look up the medical record of patient João Silva", "patient_records",
        {"name": "João Silva"},
    )])
    a, f = state.resource_assignments["s1"], state.get_fact("s1")
    ok = (
        a.ga_url == GA_URL
        and a.manifest.callable_by == "ga_proxy"
        and f is not None
        and f.provenance == Provenance.MCP
        and "João Silva" in json.dumps(f.output, ensure_ascii=False)
        and ga.searches == 1
        and r.cache.get(a.manifest.resource_id) is not None   # persisted for next run
    )
    return "patient_records", "step2 · GA search", "GAClient", ok, \
        f"patient-search (match={a.match_score:.2f}) · 1 GA query · GA spawned stdio · cached"


def case_06_cache_reuse(r: Runner):
    """Same capability, NEW run → resolved from cache, zero GA queries."""
    from axon.pa.models import Provenance

    state, ga = r.run([subtask(
        "s1", "look up the medical record of patient João Silva", "patient_records",
        {"name": "João Silva"},
    )])
    a, f = state.resource_assignments["s1"], state.get_fact("s1")
    ok = (
        a.ga_url == ""                              # step 1 — no discovery needed
        and a.manifest.callable_by == "ga_proxy"    # still executed through the GA
        and f is not None
        and f.provenance == Provenance.MCP          # same provenance as case 05
        and "João Silva" in json.dumps(f.output, ensure_ascii=False)
        and ga.searches == 0
    )
    return "patient_records", "step1 · cache", "GAClient", ok, \
        "re-run resolved from cache · 0 GA queries · still invoked via ga_proxy"


def case_07_tool_cache(r: Runner):
    """Duplicate call (same tool, same params) in one run → executor tool_cache."""
    state, ga = r.run([
        subtask("s1", "calculate the expression 7*6", "calculation", {"expression": "7*6"}),
        subtask("s2", "calculate the expression 7*6 again", "calculation", {"expression": "7*6"}),
    ])
    f1, f2 = state.get_fact("s1"), state.get_fact("s2")
    cached_step = any("cached" in e.action for e in state.scratchpad)
    ok = (
        f1 is not None and f2 is not None
        and f1.output == f2.output
        and state.budget.calls_used == 1            # one external call for two facts
        and cached_step
        and ga.searches == 0
    )
    return "calculation ×2", "step1 + tool_cache", "MCPClient", ok, \
        f"2 facts, calls_used={state.budget.calls_used} — duplicate answered from tool_cache"


# ── reporter ──────────────────────────────────────────────────────────────────

def print_results(rows: list[tuple]) -> bool:
    sep = "─" * 110
    print()
    print("  exp3 — Resolver: known resources, local tools, and the discovery cycle")
    print(f"  {sep}")
    print(f"  {'ID':<22} {'Capability':<17} {'Resolved via':<22} {'Client':<10} {'R':<3} Detail")
    print(f"  {sep}")
    for cid, cap, via, client, ok, detail in rows:
        mark = "✓" if ok else "✗"
        print(f"  {cid:<22} {cap:<17} {via:<22} {client:<10} {mark:<3} {detail}")
    print(f"  {sep}")
    passed = sum(1 for row in rows if row[4])
    print(f"  {passed}/{len(rows)} passed")
    print()
    return passed == len(rows)


# ── entry point ───────────────────────────────────────────────────────────────

CASES = [
    ("01_local_tool",         case_01_local_tool),
    ("02_cached_agent",       case_02_cached_agent),
    ("03_local_beats_cached", case_03_local_beats_cached),
    ("04_history_ranking",    case_04_history_ranking),
    ("05_ga_discovery",       case_05_ga_discovery),
    ("06_cache_reuse",        case_06_cache_reuse),
    ("07_tool_cache",         case_07_tool_cache),
]


def main() -> None:
    old_cwd = os.getcwd()
    old_ctx = os.environ.get("AXON_GA_CONTEXT")
    # inherited by every spawned stdio server — keeps the table free of INFO noise
    os.environ.setdefault("FASTMCP_LOG_LEVEL", "WARNING")

    print("  starting mock A2A server + real GA …", flush=True)
    from servers.mock_a2a_server import start as start_a2a
    start_a2a(port=A2A_PORT)

    rows: list[tuple] = []
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        try:
            start_ga(tmp)
            time.sleep(1.5)   # let uvicorn servers bind

            runner = Runner(tmp)
            for cid, fn in CASES:
                try:
                    cap, via, client, ok, detail = fn(runner)
                except Exception as exc:
                    cap, via, client, ok = "—", "—", "—", False
                    detail = f"{type(exc).__name__}: {exc}"
                rows.append((cid, cap, via, client, ok, detail))
        finally:
            os.chdir(old_cwd)
            if old_ctx is None:
                os.environ.pop("AXON_GA_CONTEXT", None)
            else:
                os.environ["AXON_GA_CONTEXT"] = old_ctx

    all_passed = print_results(rows)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
