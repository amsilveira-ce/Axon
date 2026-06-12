"""
Scenario 3 — Drift.

The architectural contribution: drift is NOT offline. The server is alive
and answering, but the agent card no longer matches what was registered
(one extra skill). Liveness passes; the HMAC fingerprint diverges; the
status must be `drift` — a third state, distinct from online and offline.
"""
import copy

TITLE = "Scenario 3 — drift detection"

EXTRA_SKILL = {
    "id":          "dependency-audit",
    "name":        "dependency-audit",
    "description": "Scans project dependencies for known vulnerabilities and license issues.",
    "tags":        ["dependencies", "audit", "cve", "licenses"],
}


def run(ctx) -> list[tuple[str, bool, str | None]]:
    checks: list[tuple[str, bool, str | None]] = []

    modified = copy.deepcopy(ctx.card)
    modified["skills"] = [*modified["skills"], EXTRA_SKILL]
    ctx.restart_server(modified)
    checks.append(("server restarted (modified card)", True, None))

    results = ctx.run_cycle()
    agent   = ctx.agent_result(results)
    status  = ctx.status_of(ctx.agent_name)

    checks.append((
        "liveness: OK (server responded)",
        agent is not None and agent.reachable,
        f"reachable={agent.reachable if agent else '—'} ({agent.error if agent else 'no result'})",
    ))
    checks.append((
        "fingerprint: diverged",
        agent is not None
        and agent.fingerprint_match is False
        and agent.new_fingerprint is not None
        and agent.new_fingerprint != ctx.stored_fingerprint,
        f"fingerprint_match={agent.fingerprint_match if agent else '—'}",
    ))
    checks.append((
        "status: online → drift",
        status == "drift",
        f"registry status={status}",
    ))
    checks.append((
        "drift ≠ offline (server is alive)",
        status == "drift" and agent is not None and agent.reachable,
        f"status={status}",
    ))
    return checks
