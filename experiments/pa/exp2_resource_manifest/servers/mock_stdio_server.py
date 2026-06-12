"""
Mock MCP stdio server — executed by the GA as a subprocess (ga_proxy path).

The GA spawns this process via MCPClient/StdioTransport, calls a tool over
stdin/stdout, and returns the result to the PA. The PA never touches this
process directly.
"""
from fastmcp import FastMCP

mcp = FastMCP("mock-health-search")


@mcp.tool
def search_patient(name: str) -> dict:
    """Search patient records by name."""
    return {
        "patient_id":  "PAC-001",
        "name":        name,
        "conditions":  ["Hypertension", "Type 2 Diabetes"],
        "medications": ["Metformin 500mg", "Losartan 50mg"],
        "last_visit":  "2026-05-15",
        "doctor":      "Dr. Carlos Mendes",
    }


@mcp.tool
def get_prescriptions(patient_id: str) -> list:
    """Get active prescriptions for a patient."""
    return [
        {"drug": "Metformin", "dose": "500mg", "frequency": "2x/day"},
        {"drug": "Losartan",  "dose": "50mg",  "frequency": "1x/day"},
    ]


if __name__ == "__main__":
    mcp.run(show_banner=False)   # reads stdin, writes stdout — MCP stdio protocol
