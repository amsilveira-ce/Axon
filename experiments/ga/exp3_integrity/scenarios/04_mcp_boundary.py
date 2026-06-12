"""
Scenario 4 — MCP boundary.

The absence of MCP monitoring is by design, not a bug (thesis §4.4.2):
stdio has no server to ping, and probing MCP HTTP would require the
operator's credentials, which the GA does not store. A full monitor cycle
must make ZERO requests to MCP endpoints and leave their status untouched,
logging "monitoring not applicable: mcp" for each.
"""

TITLE = "Scenario 4 — MCP boundary"


def run(ctx) -> list[tuple[str, bool, str | None]]:
    checks: list[tuple[str, bool, str | None]] = []

    stdio_before = ctx.status_of("health-search")
    http_before  = ctx.status_of("resend")
    hits_before  = ctx.mcp_hits()

    results = ctx.run_cycle()

    hs = next((res for r, res in results if r.name == "health-search"), None)
    rs = next((res for r, res in results if r.name == "resend"), None)

    checks.append((
        "health-search: no ping attempted (stdio)",
        hs is not None
        and hs.fingerprint_match is None
        and ctx.status_of("health-search") == stdio_before,
        f"status {stdio_before} → {ctx.status_of('health-search')}",
    ))
    checks.append((
        "resend: no ping attempted (http, no credentials)",
        rs is not None
        and rs.fingerprint_match is None
        and ctx.status_of("resend") == http_before
        and ctx.mcp_hits() == hits_before,
        f"hits +{ctx.mcp_hits() - hits_before}, status {http_before} → {ctx.status_of('resend')}",
    ))
    checks.append((
        "0 requests made to MCP endpoints",
        ctx.mcp_hits() == 0,
        f"{ctx.mcp_hits()} request(s) reached the MCP endpoint across all cycles",
    ))
    checks.append((
        "log: monitoring not applicable: mcp",
        any("monitoring not applicable: mcp" in line for line in ctx.health_log),
        "expected log line not emitted",
    ))
    return checks
