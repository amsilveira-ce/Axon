"""
pa/local_pool.py — LocalResourcePool

Tools MCP locais do PA — chamadas diretamente via MCPClient
sem passar pelo Gateway Agent.

Lê de .axon/pa/local_tools.json e constrói ResourceManifest
com todos os campos necessários para execução:
  type:             ResourceType.mcp
  protocol_binding: ProtocolBinding.MCP_STDIO
  callable_by:      "pa_direct"
  command:          [...] do local_tools.json
"""

from __future__ import annotations

import json
from pathlib import Path

from axon.types import ProtocolBinding, ResourceManifest, ResourceType


class LocalResourcePool:
    """
    Pool de tools locais do PA.
    Carregado no startup — sem LRU, sem expiração, sem GA.
    """

    def __init__(self, tools: list[ResourceManifest]) -> None:
        self._tools = tools

    @classmethod
    def load(cls, path: Path) -> "LocalResourcePool":
        """
        Carrega tools do local_tools.json.
        Constrói ResourceManifest com type, protocol_binding e command corretos.
        """
        if not path.exists():
            return cls(tools=[])

        data  = json.loads(path.read_text(encoding="utf-8"))
        tools = []

        for t in data.get("tools", []):
            if not t.get("enabled", True):
                continue

            transport = t.get("transport", "stdio")
            binding   = (
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
                ))
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    "[LocalResourcePool] skipping tool '%s': %s", t.get("name"), e
                )

        return cls(tools=tools)

    @property
    def tools(self) -> list[ResourceManifest]:
        return list(self._tools)

    def get_capabilities(self) -> list[str]:
        seen:   set[str]  = set()
        result: list[str] = []
        for tool in self._tools:
            for tag in tool.capability_tags:
                if tag not in seen:
                    seen.add(tag)
                    result.append(tag)
        return result

    def get(self, *, capability: str | None = None, name: str | None = None) -> ResourceManifest | None:
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