"""
MCP stdio server registered in the GA — patient record lookup.

Single-tool on purpose: the Executor's ga_proxy path sends tool=None and the
GA infers the tool when the server exposes exactly one. The GA spawns this
process on POST /ga/resources/{id}/invoke; the PA never runs it directly.
"""
from fastmcp import FastMCP

mcp = FastMCP("patient-search")


@mcp.tool
def search_patient(name: str) -> dict:
    """Search patient records by name."""
    return {
        "patient_id":  "PAC-001",
        "name":        name,
        "conditions":  ["Hypertension", "Type 2 Diabetes"],
        "medications": ["Metformin 500mg", "Losartan 50mg"],
        "last_visit":  "2026-05-15",
    }


if __name__ == "__main__":
    mcp.run(show_banner=False)
