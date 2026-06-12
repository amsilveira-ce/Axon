"""
Local MCP stdio tool — weather.

Advertises the same "weather" capability as the CACHED remote manifest
"cloud-weather" (which points at a dead endpoint). The Resolver must pick
this local one — pool order gives local tools implicit priority at equal
history — so the dead remote is never dialed.
"""
from fastmcp import FastMCP

mcp = FastMCP("weather")


@mcp.tool
def get_weather(city: str) -> dict:
    """Return the (canned) weather forecast for a city."""
    return {"city": city, "forecast": "sunny", "temp_c": 23, "source": "local-weather"}


if __name__ == "__main__":
    mcp.run(show_banner=False)
