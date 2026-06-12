"""
Experiment 2 — Semantic Discovery (precision@1)

Measures how accurately the GA finds the right resource for a natural
language query, across 25 queries and 11 registered resources.

Every search goes through the REAL production path — the same POST the
PA's GAClient sends:

    POST /ga/resources/search
    {"query": "...", "capabilities": [...], "max_results": 5}

served by the FastAPI app via TestClient. The server resolves the GA
context through axon.config.json exactly as `axon ga serve` does — the
experiment writes its own config inside a temporary directory, so no
real .axon/ state is touched.

Run:
    uv run experiments/ga/exp2_retrieval/run.py                       # BM25 only
    uv run experiments/ga/exp2_retrieval/run.py --strategy embedding  # needs Ollama
    uv run experiments/ga/exp2_retrieval/run.py --strategy both --save
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3] / "src"))

import tempfile

EXPERIMENT_DIR   = Path(__file__).parent
EXPERIMENTS_ROOT = Path(__file__).parents[2]
AGENT_CARDS      = EXPERIMENTS_ROOT / "shared" / "features" / "agent_cards"
MCP_MANIFESTS    = EXPERIMENTS_ROOT / "shared" / "features" / "mcp_manifest"

A2A_CARDS = ["code_review_agent", "incident_manager", "documentation_agent"]
MCP_FILES = [
    "health_search", "medical_mcp", "resend", "legal_compass",
    "climate_intelligence", "finance_oracle", "hr_nexus", "supply_chain",
]

DEFAULT_EMBED_MODEL = "nomic-embed-text"
DEFAULT_EMBED_HOST  = "http://localhost:11434"


# ── fixture → Resource ────────────────────────────────────────────────────────

def _agent_resource(card_file: str):
    from axon.types import (
        A2ASkill, ProtocolBinding, Resource, ResourceStatus, ResourceType,
    )
    card = json.loads((AGENT_CARDS / f"{card_file}.json").read_text())
    return Resource(
        id=f"res-{secrets.token_hex(3)}",
        type=ResourceType.agent,
        protocol_binding=ProtocolBinding.HTTP_JSON,
        name=card["name"],
        endpoint=card.get("url") or "http://localhost:0",
        description=card["description"],
        skills=[A2ASkill.model_validate(s) for s in card["skills"]],
        fingerprint=f"sha256:{secrets.token_hex(8)}",
        status=ResourceStatus.online,
    )


def _mcp_resource(manifest_file: str):
    from axon.types import (
        A2ASkill, AuthConfig, AuthLocation, AuthScheme,
        ProtocolBinding, Resource, ResourceStatus, ResourceType,
    )
    manifest = json.loads((MCP_MANIFESTS / f"{manifest_file}.json").read_text())
    binding = {
        "http":  ProtocolBinding.MCP_HTTP,
        "sse":   ProtocolBinding.MCP_SSE,
        "stdio": ProtocolBinding.MCP_STDIO,
    }[manifest.get("transport", "http")]
    return Resource(
        id=f"res-{secrets.token_hex(3)}",
        type=ResourceType.mcp,
        protocol_binding=binding,
        name=manifest["name"],
        endpoint=manifest.get("endpoint"),
        command=manifest.get("command"),
        description=manifest["description"],
        skills=[
            A2ASkill(
                id=t["name"], name=t["name"],
                description=t.get("description", t["name"]),
                tags=t.get("tags", []),
            )
            for t in manifest.get("tools", [])
        ],
        fingerprint=f"sha256:{secrets.token_hex(8)}",
        auth=AuthConfig(
            scheme=AuthScheme(manifest.get("auth_scheme", "none")),
            location=AuthLocation.header,
            env_var=manifest.get("auth_env_var"),
        ),
        status=ResourceStatus.online,
    )


# ── isolated GA contexts ──────────────────────────────────────────────────────

def _setup_contexts(tmp: Path, embed_model: str, embed_host: str) -> "GAPaths":  # noqa: F821
    """
    Write axon.config.json with two GA contexts sharing one registry:
    exp2-keyword (BM25) and exp2-embedding (Ollama). The server picks the
    context via AXON_GA_CONTEXT — exactly how `axon ga serve` injects it.
    """
    from axon.config import AxonConfig, GAInstanceConfig, write_config
    from axon.ga.config import GAPaths

    ga_dir = tmp / "ga-exp2"
    paths  = GAPaths(ga_dir)
    paths.makedirs()
    paths.registry.write_text('{"version": "0.1.0", "resources": []}\n')
    paths.tokens.write_text('{"version": "0.1.0", "tokens": []}\n')

    cfg = AxonConfig(
        gateways={
            "exp2-keyword": GAInstanceConfig(
                name="exp2-keyword",
                data_dir=str(ga_dir),
                retrieval_strategy="keyword",
            ),
            "exp2-embedding": GAInstanceConfig(
                name="exp2-embedding",
                data_dir=str(ga_dir),
                retrieval_strategy="embedding",
                embedding_model=embed_model,
                embedding_host=embed_host,
                # calibrado para nomic-embed-text com task prefixes + max-pooling:
                # in-scope ≥ 0.52, out-of-scope ≤ 0.49 neste corpus
                embedding_threshold=0.5,
            ),
        },
        current_gateway="exp2-keyword",
    )
    write_config(cfg, cwd=tmp)
    return paths


def _register_all(paths: "GAPaths") -> list[str]:  # noqa: F821
    from axon.ga.registry import add_resource
    names = []
    for card in A2A_CARDS:
        r = _agent_resource(card)
        add_resource(r, paths)
        names.append(r.name)
    for mf in MCP_FILES:
        r = _mcp_resource(mf)
        add_resource(r, paths)
        names.append(r.name)
    return names


# ── search through the production endpoint ────────────────────────────────────

def _run_strategy(client, context: str, queries: list[dict]) -> list[dict]:
    """
    POST each query to /ga/resources/search — the same payload shape the
    PA's GAClient.search() sends — under the given GA context.
    """
    os.environ["AXON_GA_CONTEXT"] = context
    rows = []
    for q in queries:
        resp = client.post(
            "/ga/resources/search",
            json={
                "query":        q["query"],
                "capabilities": q["capabilities"],
                "max_results":  5,
            },
        )
        resp.raise_for_status()
        body    = resp.json()
        results = body["results"]
        top1    = results[0]["name"] if results else None
        score   = results[0]["score"] if results else None
        hit     = (top1 == q["expected"]) if q["expected"] else (top1 is None)
        rows.append({
            "id":       q["id"],
            "query":    q["query"],
            "category": q["category"],
            "expected": q["expected"],
            "got":      top1,
            "score":    score,
            "hit":      hit,
        })
    return rows


def _ollama_available(host: str, model: str) -> bool:
    import httpx
    try:
        resp = httpx.get(f"{host.rstrip('/')}/api/tags", timeout=3.0)
        resp.raise_for_status()
        models = [m.get("name", "") for m in resp.json().get("models", [])]
        return any(m.split(":")[0] == model.split(":")[0] for m in models)
    except Exception:
        return False


# ── reporter ──────────────────────────────────────────────────────────────────

def _summarize(rows: list[dict]) -> dict:
    def bucket(cat):
        sub = [r for r in rows if r["category"] == cat]
        return sum(1 for r in sub if r["hit"]), len(sub)
    d_ok, d_n = bucket("direct")
    p_ok, p_n = bucket("paraphrase")
    o_ok, o_n = bucket("out-of-scope")
    scored_ok, scored_n = d_ok + p_ok, d_n + p_n
    return {
        "direct":       {"correct": d_ok, "total": d_n},
        "paraphrase":   {"correct": p_ok, "total": p_n},
        "out_of_scope": {"filtered": o_ok, "total": o_n},
        "precision_at_1": round(scored_ok / scored_n, 3) if scored_n else 0.0,
        "correct":      scored_ok,
        "total":        scored_n,
    }


def _print_report(all_runs: dict[str, list[dict]]) -> None:
    sep = "─" * 68
    print()
    print("  Experiment 2 — Semantic Discovery")
    print(f"  {sep}")
    print(f"  {'Strategy':<12} {'Correct':>7} {'Total':>6} {'P@1':>6} {'Direct':>8} {'Para':>7} {'OOS':>6}")
    print(f"  {sep}")
    for label, rows in all_runs.items():
        s = _summarize(rows)
        print(
            f"  {label:<12} {s['correct']:>7} {s['total']:>6} {s['precision_at_1']:>6.2f}"
            f" {s['direct']['correct']:>5}/{s['direct']['total']:<2}"
            f" {s['paraphrase']['correct']:>4}/{s['paraphrase']['total']:<2}"
            f" {s['out_of_scope']['filtered']:>3}/{s['out_of_scope']['total']:<2}"
        )
    print(f"  {sep}")
    for label, rows in all_runs.items():
        misses = [r for r in rows if not r["hit"]]
        if misses:
            print(f"\n  {label} — misses")
            for r in misses:
                print(f"    #{r['id']:>2} [{r['category']}] {r['query']!r}")
                print(f"        expected {r['expected']!r}, got {r['got']!r}")
    print()


def _save_results(all_runs: dict[str, list[dict]], registered: list[str]) -> Path:
    out_dir = EXPERIMENT_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out   = out_dir / f"run_{stamp}.json"
    out.write_text(json.dumps({
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "resources":  registered,
        "strategies": {
            label: {"summary": _summarize(rows), "queries": rows}
            for label, rows in all_runs.items()
        },
    }, indent=2, ensure_ascii=False) + "\n")
    return out


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Experiment 2 — Semantic Discovery")
    parser.add_argument("--strategy", choices=["keyword", "embedding", "both"],
                        default="keyword")
    parser.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    parser.add_argument("--embed-host",  default=DEFAULT_EMBED_HOST)
    parser.add_argument("--save", action="store_true",
                        help="save detailed results to results/run_<ts>.json")
    args = parser.parse_args()

    queries = json.loads((EXPERIMENT_DIR / "queries.json").read_text())["queries"]
    assert len(queries) == 25, f"expected 25 queries, found {len(queries)}"

    strategies = ["keyword", "embedding"] if args.strategy == "both" else [args.strategy]
    if "embedding" in strategies and not _ollama_available(args.embed_host, args.embed_model):
        print(f"\n  ✗ embedding strategy requires Ollama at {args.embed_host} "
              f"with model '{args.embed_model}' — skipping it")
        strategies = [s for s in strategies if s != "embedding"]
        if not strategies:
            sys.exit(1)

    old_cwd = os.getcwd()
    old_ctx = os.environ.get("AXON_GA_CONTEXT")

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp   = Path(tmp_str)
        paths = _setup_contexts(tmp, args.embed_model, args.embed_host)
        registered = _register_all(paths)
        print(f"\n  Registered {len(registered)} resources in isolated context")

        # the server resolves axon.config.json from cwd — point it at the temp dir
        os.chdir(tmp)
        try:
            from fastapi.testclient import TestClient
            from axon.ga.server import app

            client   = TestClient(app, raise_server_exceptions=False)
            all_runs: dict[str, list[dict]] = {}
            labels   = {"keyword": "BM25", "embedding": "Embeddings"}
            for strat in strategies:
                print(f"  Running {labels[strat]} — 25 queries through POST /ga/resources/search")
                all_runs[labels[strat]] = _run_strategy(client, f"exp2-{strat}", queries)
        finally:
            os.chdir(old_cwd)
            if old_ctx is None:
                os.environ.pop("AXON_GA_CONTEXT", None)
            else:
                os.environ["AXON_GA_CONTEXT"] = old_ctx

        _print_report(all_runs)
        if args.save:
            out = _save_results(all_runs, registered)
            print(f"  Detailed results saved to: {out.relative_to(Path(old_cwd))}\n")


if __name__ == "__main__":
    main()
