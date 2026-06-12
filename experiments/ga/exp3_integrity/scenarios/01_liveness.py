"""
Scenario 1 — Liveness.

The GA must detect that a registered agent stopped responding.
We kill the mock A2A server and run a monitor cycle: the agent's status
must transition online → offline. MCP resources must not be touched.
"""

TITLE = "Scenario 1 — liveness detection"


def run(ctx) -> list[tuple[str, bool, str | None]]:
    checks: list[tuple[str, bool, str | None]] = []

    ctx.server.stop()
    checks.append(("server stopped", True, None))

    hits_before = ctx.mcp_hits()
    results     = ctx.run_cycle()
    agent       = ctx.agent_result(results)
    checks.append((
        "health check triggered",
        agent is not None,
        "agent missing from cycle results",
    ))

    registry_status = ctx.status_of(ctx.agent_name)
    checks.append((
        "status: online → offline",
        agent is not None
        and agent.status.value == "offline"
        and not agent.reachable
        and registry_status == "offline",
        f"health={agent.status.value if agent else '—'} registry={registry_status}",
    ))

    checks.append((
        "no MCP request during cycle",
        ctx.mcp_hits() == hits_before,
        f"{ctx.mcp_hits() - hits_before} request(s) reached the MCP endpoint",
    ))
    return checks
