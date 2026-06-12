"""
Experiment 1 (PA) — IntentExtractor + Domain Skills

Validates that the intent extraction skill can be swapped to a
domain-specific one WITHOUT breaking the extractor:

  - non-ambiguous queries stay READY with or without a skill
  - ambiguous queries CLARIFY with the default prompt, but become READY
    when a domain skill provides the missing defaults (contrast pairs)
  - the skill must not make the extractor hallucinate: a query with no
    discernible goal still CLARIFIES even with the skill loaded

The experiment exercises the REAL production path:

  1. Installs the .md files from skills/ into src/axon/pa/skills/domains/
     — exactly what an operator does to add a domain
  2. Builds IntentExtractor(PAConfig(intent_extractor=
     IntentExtractorConfig(domain="hospital"))) — the production loader
     appends the domain file to the base intent_extraction.md skill
  3. Runs extract() per case and checks READY vs CLARIFY + extracted values
  4. Removes the installed files afterwards (try/finally)

Requires Ollama running locally with the configured model.

Run:
    uv run experiments/pa/exp1_intent_extractor/run.py
    uv run experiments/pa/exp1_intent_extractor/run.py --model llama3.1:8b --save
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3] / "src"))

EXPERIMENT_DIR = Path(__file__).parent
SKILLS_DIR     = EXPERIMENT_DIR / "skills"
CASES_DIR      = EXPERIMENT_DIR / "cases"

DEFAULT_HOST  = "http://localhost:11434"
DEFAULT_MODEL = "deepseek-r1:14b"


# ── skill installation (production domains dir) ──────────────────────────────

def _install_skills() -> list[Path]:
    """
    Copy the experiment's domain skills into pa/skills/domains/ — the same
    operation an operator performs. Refuses to overwrite existing domains.
    """
    from axon.pa import intent_extractor as ie

    installed = []
    ie._DOMAINS_DIR.mkdir(parents=True, exist_ok=True)
    for src in sorted(SKILLS_DIR.glob("*.md")):
        target = ie._DOMAINS_DIR / src.name
        if target.exists():
            raise RuntimeError(
                f"domain '{src.name}' already exists at {target} — "
                f"refusing to overwrite a real skill"
            )
        target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        installed.append(target)
    return installed


# ── extractor factory ─────────────────────────────────────────────────────────

def _extractor(domain: str | None, host: str, model: str):
    from axon.config import IntentExtractorConfig, LLMConfig, PAConfig
    from axon.pa.intent_extractor import IntentExtractor

    config = PAConfig(
        llm=LLMConfig(host=host, model=model),
        intent_extractor=IntentExtractorConfig(domain=domain),
    )
    return IntentExtractor(config)


# ── case evaluation ───────────────────────────────────────────────────────────

def _run_case(case: dict, extractors: dict, host: str, model: str) -> dict:
    skill  = case.get("skill")                       # "hospital.md" | None
    domain = skill.removesuffix(".md") if skill else None

    if domain not in extractors:
        extractors[domain] = _extractor(domain, host, model)

    t0 = time.monotonic()
    objective, _trace = extractors[domain].extract(case["query"])
    latency_s = time.monotonic() - t0

    status = "READY" if objective.clarification is None else "CLARIFY"
    serialized = json.dumps(objective.model_dump(), ensure_ascii=False).lower()

    expected_values = case.get("expected_values", [])
    missing = [v for v in expected_values if v.lower() not in serialized]

    if status == "READY":
        detail = "all" if not missing else f"{len(expected_values) - len(missing)}/{len(expected_values)}"
        if not expected_values:
            detail = "—"
    else:
        detail = str(len(objective.clarification.questions))

    passed = status == case["expected"] and (status != "READY" or not missing)

    return {
        "id":        case["id"],
        "query":     case["query"],
        "skill":     skill or "—",
        "expected":  case["expected"],
        "status":    status,
        "detail":    detail,
        "passed":    passed,
        "missing":   missing,
        "latency_s": round(latency_s, 1),
        "objective": objective.model_dump(),
    }


# ── reporter ──────────────────────────────────────────────────────────────────

def _trunc(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"

def _print_results(rows: list[dict]) -> None:
    sep = "─" * 78
    print()
    print("  Experiment 1 — IntentExtractor + Domain Skills")
    print(f"  {sep}")
    print(f"  {'ID':<9} {'Query':<34} {'Skill':<14} {'Expected':<9} Result")
    print(f"  {sep}")
    for r in rows:
        mark = "✓" if r["passed"] else "✗"
        print(
            f"  {r['id']:<9} {_trunc(r['query'], 33):<34} "
            f"{r['skill']:<14} {r['expected']:<9} {mark}  {r['detail']}"
        )
    print(f"  {sep}")
    passed = sum(1 for r in rows if r["passed"])
    print(f"  {passed}/{len(rows)} passed")

    failures = [r for r in rows if not r["passed"]]
    if failures:
        print()
        print("  Failures")
        for r in failures:
            print(f"    {r['id']}  expected {r['expected']}, got {r['status']}")
            if r["missing"]:
                print(f"          missing values: {', '.join(r['missing'])}")
            clar = r["objective"].get("clarification")
            if clar:
                for q in clar.get("questions", []):
                    print(f"          asked: {q.get('question')}")
    print()


def _save_results(rows: list[dict], model: str) -> Path:
    out_dir = EXPERIMENT_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out   = out_dir / f"run_{stamp}.json"
    out.write_text(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model":     model,
        "passed":    sum(1 for r in rows if r["passed"]),
        "total":     len(rows),
        "cases":     rows,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def _ollama_available(host: str, model: str) -> bool:
    import httpx
    try:
        resp = httpx.get(f"{host.rstrip('/')}/api/tags", timeout=3.0)
        resp.raise_for_status()
        models = [m.get("name", "") for m in resp.json().get("models", [])]
        return any(m.split(":")[0] == model.split(":")[0] for m in models)
    except Exception:
        return False


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Experiment 1 — IntentExtractor + Domain Skills")
    parser.add_argument("--host",  default=DEFAULT_HOST)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--save",  action="store_true",
                        help="save detailed results to results/run_<ts>.json")
    parser.add_argument("--cases", default=None, metavar="FILE",
                        help="run only one case file from cases/ (e.g. fun.json)")
    args = parser.parse_args()

    if not _ollama_available(args.host, args.model):
        print(f"\n  ✗ requires Ollama at {args.host} with model '{args.model}'")
        sys.exit(1)

    case_files = (
        [CASES_DIR / args.cases] if args.cases
        else sorted(CASES_DIR.glob("*.json"))
    )
    cases = []
    for f in case_files:
        cases.extend(json.loads(f.read_text(encoding="utf-8"))["cases"])

    installed = _install_skills()
    extractors: dict = {}
    rows: list[dict] = []
    try:
        for case in cases:
            print(f"  running {case['id']} ({case.get('skill') or 'default'}) …", flush=True)
            rows.append(_run_case(case, extractors, args.host, args.model))
    finally:
        for f in installed:
            f.unlink(missing_ok=True)

    _print_results(rows)
    if args.save:
        out = _save_results(rows, args.model)
        print(f"  Detailed results saved to: {out.relative_to(Path.cwd())}\n")

    if any(not r["passed"] for r in rows):
        sys.exit(1)


if __name__ == "__main__":
    main()
