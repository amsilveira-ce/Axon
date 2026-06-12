"""
Experiment 3 — Integrity Monitoring

Validates the GA's health/integrity monitor across four scenarios:

  1. Liveness  — a registered agent stops responding   → status offline
  2. Recovery  — the agent comes back, same card       → status online
  3. Drift     — alive, but the agent card CHANGED     → status drift
  4. Boundary  — MCP resources are never probed        → credential boundary

The narrative arc of the A2A scenarios is a state machine:

    online → offline → online → drift

drift is NOT offline: the agent is alive and responding, but what it offers
no longer matches what was registered. The HMAC fingerprint (keyed by the
admission token) is what makes the distinction detectable.

Everything runs against an isolated temporary GA directory — no real
.axon/ state, no real network beyond 127.0.0.1 mock servers.

Run:
    uv run experiments/ga/exp3_integrity/run.py
"""
from __future__ import annotations

import importlib.util
import json
import logging
import secrets
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).parents[2]))  # experiments/

EXPERIMENT_DIR   = Path(__file__).parent
EXPERIMENTS_ROOT = Path(__file__).parents[2]
AGENT_CARDS      = EXPERIMENTS_ROOT / "shared" / "features" / "agent_cards"
MCP_MANIFESTS    = EXPERIMENTS_ROOT / "shared" / "features" / "mcp_manifest"

AXON_EXTENSION_URI = "https://axon-framework.dev/extensions/registry/v1"
A2A_PORT = 18061
MCP_PORT = 18062


# ── shared context handed to every scenario ───────────────────────────────────

@dataclass
class Ctx:
    paths:              "GAPaths"            # type: ignore[name-defined]
    agent_name:         str
    agent_id:           str
    stored_fingerprint: str
    a2a_port:           int
    card:               dict                 # exact card served at registration
    server:             "MockA2AServer"      # type: ignore[name-defined]
    mcp_server:         "CountingMockServer" # type: ignore[name-defined]
    health_log:         list[str] = field(default_factory=list)

    def run_cycle(self):
        from axon.health import run_cycle
        return run_cycle(self.paths)

    def status_of(self, name: str) -> str:
        from axon.ga.registry import get_resource
        r = get_resource(name, self.paths)
        return r.status.value if r else "—"

    def restart_server(self, card: dict) -> None:
        from shared.mock_a2a_server import MockA2AServer
        if self.server:
            self.server.stop()
        self.server = MockA2AServer(port=self.a2a_port, card=card)
        self.server.start()

    def agent_result(self, results):
        return next(
            (res for r, res in results if r.name == self.agent_name), None
        )

    def mcp_hits(self) -> int:
        return self.mcp_server.hits


# ── setup: register 1 A2A agent + 2 MCP resources ────────────────────────────

def _register_agent(paths, url: str):
    """Full production registration: token → card → validate_agent → persist."""
    import secrets as _secrets
    from axon.ga.registry import add_resource
    from axon.ga.tokens import generate, mark_used
    from axon.types import ProtocolBinding, Resource, ResourceStatus, ResourceType
    from axon.validator import validate_agent

    token = generate("code-review-agent", paths)
    base  = json.loads((AGENT_CARDS / "code_review_agent.json").read_text())
    card  = {
        **base,
        "capabilities": {
            **base.get("capabilities", {}),
            "extensions": [{
                "uri":      AXON_EXTENSION_URI,
                "required": True,
                "params": {
                    "token":            token.token,
                    "registry_id":      "local",
                    "protocol_version": "0.1",
                },
            }],
        },
    }

    from shared.mock_a2a_server import MockA2AServer
    server = MockA2AServer(port=A2A_PORT, card=card)
    server.start()

    result = validate_agent(url, paths)
    assert result.ok, f"validate_agent failed at '{result.step}': {result.error}"

    resource = Resource(
        id=f"res-{_secrets.token_hex(3)}",
        type=ResourceType.agent,
        protocol_binding=ProtocolBinding.HTTP_JSON,
        name=result.agent_card.name,
        endpoint=url,
        description=result.agent_card.description,
        skills=result.agent_card.skills,
        fingerprint=result.fingerprint,
        status=ResourceStatus.online,
    )
    add_resource(resource, paths)
    mark_used(result.verified_token, resource.id, paths)
    return resource, card, server


def _register_mcp(paths, manifest_file: str, endpoint_override: str | None = None):
    from axon.ga.registry import add_resource
    from axon.ga.tokens import generate, mark_used
    from axon.types import (
        A2ASkill, AuthConfig, AuthLocation, AuthScheme,
        ProtocolBinding, Resource, ResourceStatus, ResourceType,
    )

    manifest = json.loads((MCP_MANIFESTS / f"{manifest_file}.json").read_text())
    binding = {
        "http":  ProtocolBinding.MCP_HTTP,
        "sse":   ProtocolBinding.MCP_SSE,
        "stdio": ProtocolBinding.MCP_STDIO,
    }[manifest.get("transport", "http")]

    token    = generate(manifest["name"], paths)
    resource = Resource(
        id=f"res-{secrets.token_hex(3)}",
        type=ResourceType.mcp,
        protocol_binding=binding,
        name=manifest["name"],
        endpoint=endpoint_override or manifest.get("endpoint"),
        command=manifest.get("command"),
        description=manifest["description"],
        skills=[
            A2ASkill(
                id=t["name"], name=t["name"],
                description=t.get("description", t["name"]),
                tags=t.get("tags", []),
            )
            for t in manifest.get("tools", [])
        ],
        fingerprint=f"sha256:{secrets.token_hex(8)}",
        auth=AuthConfig(
            scheme=AuthScheme(manifest.get("auth_scheme", "none")),
            location=AuthLocation.header,
            env_var=manifest.get("auth_env_var"),
        ),
        token_ref=token.token,
        status=ResourceStatus.online,
    )
    add_resource(resource, paths)
    mark_used(token.token, resource.id, paths)
    return resource


# ── scenario loader ───────────────────────────────────────────────────────────

def _load_scenarios():
    mods = []
    for path in sorted((EXPERIMENT_DIR / "scenarios").glob("*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mods.append(mod)
    return mods


# ── log capture ───────────────────────────────────────────────────────────────

class _ListHandler(logging.Handler):
    def __init__(self, sink: list[str]) -> None:
        super().__init__(level=logging.INFO)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self._sink.append(record.getMessage())


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    from axon.ga.config import GAPaths
    from shared.mock_mcp_server import CountingMockServer

    sep = "─" * 52
    print()
    print("  Experiment 3 — Integrity Monitoring")
    print(f"  {sep}")

    with tempfile.TemporaryDirectory() as tmp:
        paths = GAPaths(Path(tmp) / "ga")
        paths.makedirs()
        paths.registry.write_text('{"version": "0.1.0", "resources": []}\n')
        paths.tokens.write_text('{"version": "0.1.0", "tokens": []}\n')

        health_log: list[str] = []
        logger = logging.getLogger("axon.health")
        logger.setLevel(logging.INFO)
        logger.addHandler(_ListHandler(health_log))

        mcp_server = CountingMockServer(port=MCP_PORT)
        mcp_server.start()

        agent, card, a2a_server = _register_agent(paths, f"http://127.0.0.1:{A2A_PORT}")
        _register_mcp(paths, "resend", endpoint_override=mcp_server.url)
        _register_mcp(paths, "health_search")

        ctx = Ctx(
            paths=paths,
            agent_name=agent.name,
            agent_id=agent.id,
            stored_fingerprint=agent.fingerprint,
            a2a_port=A2A_PORT,
            card=card,
            server=a2a_server,
            mcp_server=mcp_server,
            health_log=health_log,
        )

        passed = total = 0
        try:
            for mod in _load_scenarios():
                total += 1
                print(f"  {mod.TITLE}")
                checks = mod.run(ctx)
                ok = all(c[1] for c in checks)
                passed += ok
                for label, check_ok, detail in checks:
                    mark = "✓" if check_ok else "✗"
                    tail = f"  → {detail}" if (not check_ok and detail) else ""
                    print(f"    {mark} {label}{tail}")
                print()
        finally:
            if ctx.server:
                ctx.server.stop()
            mcp_server.stop()

        print(f"  {sep}")
        print(f"  {passed}/{total} passed")
        print()

        if passed != total:
            sys.exit(1)


if __name__ == "__main__":
    main()
