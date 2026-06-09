"""Local resource pool for the Principal Agent.

``LocalResourcePool`` exposes tools defined in ``local_tools.json`` as
``ResourceManifest`` objects so the Resolver and Executor can treat them
the same as Gateway Agent resources.

Tools are loaded once at startup — no LRU, no expiry, no Gateway Agent
involvement.  Each enabled tool becomes a manifest with:

- ``type``: ``ResourceType.mcp``
- ``protocol_binding``: ``MCP_STDIO`` or ``MCP_HTTP`` (from ``transport``)
- ``callable_by``: ``"pa_direct"``
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from axon.types import ProtocolBinding, ResourceManifest, ResourceType

logger = logging.getLogger(__name__)


class LocalResourcePool:
    """Pool of local MCP tools available to the Principal Agent.

    Loaded from ``local_tools.json`` at startup.  Each enabled entry becomes
    a ``ResourceManifest`` that the Resolver can assign to a subtask and the
    Executor can call directly without going through a Gateway Agent.

    Attributes:
        tools: Immutable snapshot of all loaded manifests.
    """

    def __init__(self, tools: list[ResourceManifest]) -> None:
        self._tools = tools

    @classmethod
    def load(cls, path: Path) -> "LocalResourcePool":
        """Load tools from *path* and return a new pool.

        Silently skips disabled entries and malformed tool definitions.
        Returns an empty pool when the file does not exist.
        """
        if not path.exists():
            return cls(tools=[])

        data = json.loads(path.read_text(encoding="utf-8"))
        tools = []

        for t in data.get("tools", []):
            if not t.get("enabled", True):
                continue

            transport = t.get("transport", "stdio")
            binding = (
                ProtocolBinding.MCP_STDIO if transport == "stdio"
                else ProtocolBinding.MCP_HTTP
            )

            try:
                tools.append(ResourceManifest(
                    resource_id=f"local-{t['name']}",
                    name=t["name"],
                    type=ResourceType.mcp,
                    protocol_binding=binding,
                    description=t.get("description", ""),
                    capability_tags=[t["capability"]],
                    callable_by="pa_direct",
                    command=t.get("command"),
                    endpoint=t.get("endpoint"),
                    tool=t.get("tool"),
                ))
            except Exception as exc:
                logger.warning("[LocalPool] skipping tool '%s': %s", t.get("name"), exc)

        return cls(tools=tools)

    @property
    def tools(self) -> list[ResourceManifest]:
        return list(self._tools)

    def get_capabilities(self) -> list[str]:
        """Return a deduplicated, insertion-ordered list of all capability tags."""
        tags = [tag for tool in self._tools for tag in tool.capability_tags]
        return list(dict.fromkeys(tags))

    def get(
        self,
        *,
        capability: str | None = None,
        name: str | None = None,
    ) -> ResourceManifest | None:
        """Return the first tool matching *name* or *capability*, or ``None``."""
        for tool in self._tools:
            if name and tool.name == name:
                return tool
            if capability and capability in tool.capability_tags:
                return tool
        return None

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"LocalResourcePool({len(self._tools)} tools)"
