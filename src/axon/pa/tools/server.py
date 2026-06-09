# Re-exports axon.local_pool.server — the server was moved there.
# Any code or config still referencing "axon.pa.tools.server" keeps working.
from axon.local_pool.server import mcp  # noqa: F401

if __name__ == "__main__":
    mcp.run()
