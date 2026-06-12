"""
Scenario 2 — Recovery.

The transition must work in both directions. The server comes back with
the SAME agent card: the monitor must move the agent offline → online,
and the recomputed HMAC fingerprint must match the stored one (no drift).
"""

TITLE = "Scenario 2 — recovery"


def run(ctx) -> list[tuple[str, bool, str | None]]:
    checks: list[tuple[str, bool, str | None]] = []

    before = ctx.status_of(ctx.agent_name)   # offline, left by scenario 1
    ctx.restart_server(ctx.card)
    checks.append(("server restarted (same card)", True, None))

    results = ctx.run_cycle()
    agent   = ctx.agent_result(results)
    after   = ctx.status_of(ctx.agent_name)

    checks.append((
        "status: offline → online",
        before == "offline" and after == "online",
        f"{before} → {after}",
    ))
    checks.append((
        "fingerprint: match (no drift)",
        agent is not None and agent.fingerprint_match is True,
        f"fingerprint_match={agent.fingerprint_match if agent else '—'}",
    ))
    return checks
