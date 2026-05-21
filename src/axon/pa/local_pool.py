"""
pa/local_pool.py — LocalResourcePool

Tools MCP locais do PA — chamadas diretamente via MCPClient
sem passar pelo Gateway Agent.
"""

from __future__ import annotations

import json
from pathlib import Path

from axon.types import ResourceManifest


class LocalResourcePool:
    """
    Pool de tools locais do PA.

    Lê de .axon/pa/local_tools.json — sem manifests hardcoded.
    Apenas tools com enabled=true são carregadas.
    """

    def __init__(self, tools: list[ResourceManifest]) -> None:
        self._tools = tools

    @classmethod
    def load(cls, path: Path) -> "LocalResourcePool":
        """
        Carrega tools do local_tools.json.

        Args:
            path: caminho para .axon/pa/local_tools.json
                  obtido via paths().pa_local_tools
        """
        if not path.exists():
            return cls(tools=[])

        data = json.loads(path.read_text(encoding="utf-8"))
        tools = [
            ResourceManifest(
                id=f"local-{t['name']}",
                name=t["name"],
                description=t.get("description", ""),
                capability_tags=[t["capability"]],
                callable_by="pa_direct",
                transport=t.get("transport", "stdio"),
                command=t.get("command"),
            )
            for t in data.get("tools", [])
            if t.get("enabled", True)
        ]
        return cls(tools=tools)

    # ------------------------------------------------------------------

    @property
    def tools(self) -> list[ResourceManifest]:
        return list(self._tools)

    def get_capabilities(self) -> list[str]:
        """Lista deduplica de todas as capability_tags disponíveis."""
        seen: set[str] = set()
        result: list[str] = []
        for tool in self._tools:
            for tag in tool.capability_tags:
                if tag not in seen:
                    seen.add(tag)
                    result.append(tag)
        return result

    def get(self, *, capability: str | None = None, name: str | None = None) -> ResourceManifest | None:
        """Busca por capability tag ou nome exato."""
        for tool in self._tools:
            if name and tool.name == name:
                return tool
            if capability and capability in tool.capability_tags:
                return tool
        return None

    def get_all(self, capability: str) -> list[ResourceManifest]:
        """Todas as tools com a capability_tag informada."""
        return [t for t in self._tools if capability in t.capability_tags]

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"LocalResourcePool({len(self._tools)} tools)"