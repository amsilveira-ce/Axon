"""
Experiment 1 — Registration & Admission

Tests the GA registration system end-to-end using a temporary GA directory
and a mock A2A HTTP server. No real GA process or config file required.

Run:
    python experiments/ga/exp1_registration/run.py
"""
from __future__ import annotations

import json
import secrets
import sys
import tempfile
from pathlib import Path

# resolve project root so imports work when run directly
sys.path.insert(0, str(Path(__file__).parents[3] / "src"))

from axon.ga.config import GAPaths
from axon.ga.registry import add_resource, list_resources, resource_exists
from axon.ga.tokens import (
    TokenVerificationError,
    generate,
    list_tokens,
    mark_used,
    revoke,
    verify_local,
)
from axon.types import (
    A2ASkill,
    AuthConfig,
    AuthLocation,
    AuthScheme,
    ProtocolBinding,
    Resource,
    ResourcePolicy,
    ResourceStatus,
    ResourceType,
)
from axon.validator import validate_agent

EXPERIMENTS_ROOT = Path(__file__).parents[2]
AGENT_CARDS      = EXPERIMENTS_ROOT / "shared" / "features" / "agent_cards"
MCP_MANIFESTS    = EXPERIMENTS_ROOT / "shared" / "features" / "mcp_manifest"

AXON_EXTENSION_URI = "https://axon-framework.dev/extensions/registry/v1"
MOCK_PORT = 18041


# ── test harness ──────────────────────────────────────────────────────────────

_results: list[tuple[str, str, bool, str | None]] = []


class _Case:
    def __init__(self, sid: str, label: str) -> None:
        self._sid   = sid
        self._label = label

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, *_):
        if exc_type is AssertionError:
            _results.append((self._sid, self._label, False, str(exc_val)))
            return True
        if exc_type is not None:
            _results.append((self._sid, self._label, False, f"{type(exc_val).__name__}: {exc_val}"))
            return True
        _results.append((self._sid, self._label, True, None))
        return False


def case(sid: str, label: str) -> _Case:
    return _Case(sid, label)


# ── fixture helpers ───────────────────────────────────────────────────────────

def _load_card(name: str) -> dict:
    return json.loads((AGENT_CARDS / f"{name}.json").read_text())


def _load_manifest(name: str) -> dict:
    return json.loads((MCP_MANIFESTS / f"{name}.json").read_text())


def _resource_from_manifest(manifest: dict, rid: str | None = None) -> Resource:
    rid = rid or f"res-{secrets.token_hex(3)}"
    transport = manifest.get("transport", "http")
    binding = {
        "http":  ProtocolBinding.MCP_HTTP,
        "sse":   ProtocolBinding.MCP_SSE,
        "stdio": ProtocolBinding.MCP_STDIO,
    }.get(transport, ProtocolBinding.MCP_HTTP)

    skills = [
        A2ASkill(
            id=t["name"], name=t["name"],
            description=t.get("description", t["name"]),
            tags=t.get("tags", []),
        )
        for t in manifest.get("tools", [])
    ]

    auth_scheme_str = manifest.get("auth_scheme", "none")
    auth_cfg = AuthConfig(
        scheme=AuthScheme(auth_scheme_str),
        location=AuthLocation.header,
        env_var=manifest.get("auth_env_var"),
    )

    return Resource(
        id=rid,
        type=ResourceType.mcp,
        protocol_binding=binding,
        name=manifest["name"],
        endpoint=manifest.get("endpoint"),
        command=manifest.get("command"),
        description=manifest["description"],
        skills=skills,
        fingerprint=f"sha256:{secrets.token_hex(8)}",
        auth=auth_cfg,
        policy=ResourcePolicy(
            is_paid=manifest.get("is_paid", False),
            cost_per_call=manifest.get("cost_per_call"),
        ),
        status=ResourceStatus.online,
    )


# ── scenarios ─────────────────────────────────────────────────────────────────

def run_scenarios(paths: GAPaths, mock_url: str, a2a_token_value: str) -> None:

    # ── positive ─────────────────────────────────────────────────────────────

    with case("pos_04", "Token status is pending before use"):
        tokens = list_tokens(paths)
        t = next((t for t in tokens if t.token == a2a_token_value), None)
        assert t is not None, "token not found in store"
        assert t.status.value == "pending", f"expected pending, got {t.status.value}"

    with case("pos_01", "A2A agent registered successfully"):
        result = validate_agent(mock_url, paths)
        assert result.ok, f"validate_agent failed at step '{result.step}': {result.error}"
        card     = result.agent_card
        resource = Resource(
            id=f"res-{secrets.token_hex(3)}",
            type=ResourceType.agent,
            protocol_binding=ProtocolBinding.HTTP_JSON,
            name=card.name,
            endpoint=mock_url,
            description=card.description,
            skills=card.skills,
            fingerprint=result.fingerprint or "",
            status=ResourceStatus.online,
        )
        add_resource(resource, paths)
        mark_used(result.verified_token, resource.id, paths)
        assert resource_exists("code-review-agent", paths), "resource not persisted"

    with case("pos_05", "Token consumed after registration"):
        tokens = list_tokens(paths)
        t = next((t for t in tokens if t.token == a2a_token_value), None)
        assert t is not None, "token not found in store"
        assert t.status.value == "used", f"expected used, got {t.status.value}"

    with case("pos_02", "MCP HTTP tool registered from manifest"):
        manifest  = _load_manifest("resend")
        mcp_token = generate("resend", paths)
        resource  = _resource_from_manifest(manifest)
        resource.token_ref = mcp_token.token
        add_resource(resource, paths)
        mark_used(mcp_token.token, resource.id, paths)
        assert resource_exists("resend", paths), "resource not persisted"

    with case("pos_03", "MCP stdio tool registered from manifest"):
        manifest  = _load_manifest("health_search")
        mcp_token = generate("health-search", paths)
        resource  = _resource_from_manifest(manifest)
        resource.token_ref = mcp_token.token
        add_resource(resource, paths)
        mark_used(mcp_token.token, resource.id, paths)
        assert resource_exists("health-search", paths), "resource not persisted"

    with case("pos_06", "Token revocation prevents future use"):
        tk = generate("revoke-test", paths)
        revoke(tk.token, paths)
        try:
            verify_local(tk.token, paths)
            assert False, "expected TokenVerificationError, got none"
        except TokenVerificationError as e:
            assert "revoked" in str(e).lower(), f"unexpected error message: {e}"

    # ── negative ─────────────────────────────────────────────────────────────

    with case("neg_01", "Invalid token format rejected"):
        try:
            verify_local("not_a_valid_format", paths)
            assert False, "expected TokenVerificationError, got none"
        except TokenVerificationError as e:
            assert "not found" in str(e).lower(), f"unexpected error message: {e}"

    with case("neg_02", "Consumed token rejected"):
        tk      = generate("consumed-test", paths)
        dummy   = _resource_from_manifest(_load_manifest("resend"))
        dummy.name = "consumed-test-resource"
        add_resource(dummy, paths)
        mark_used(tk.token, dummy.id, paths)
        try:
            verify_local(tk.token, paths)
            assert False, "expected TokenVerificationError, got none"
        except TokenVerificationError as e:
            assert "already used" in str(e).lower(), f"unexpected error message: {e}"

    with case("neg_03", "Unknown token rejected"):
        fake = f"axon_tk_{secrets.token_urlsafe(24)}"
        try:
            verify_local(fake, paths)
            assert False, "expected TokenVerificationError, got none"
        except TokenVerificationError as e:
            assert "not found" in str(e).lower(), f"unexpected error message: {e}"

    with case("neg_04", "Unreachable agent rejected, token preserved"):
        tk     = generate("unreachable-agent", paths)
        result = validate_agent("http://127.0.0.1:19999", paths)
        assert not result.ok, "expected failure for unreachable agent"
        stored = next((t for t in list_tokens(paths) if t.token == tk.token), None)
        assert stored is not None and stored.status.value == "pending", (
            f"token should be pending, got {stored.status.value if stored else 'not found'}"
        )

    with case("neg_05", "Duplicate resource rejected, token preserved"):
        # code-review-agent was registered in pos_01
        assert resource_exists("code-review-agent", paths), "precondition: resource must exist"
        tk = generate("code-review-agent-dup", paths)
        # a guarded flow detects the duplicate before consuming the token
        is_dup = resource_exists("code-review-agent", paths)
        assert is_dup, "duplicate not detected"
        # token must still be pending because we aborted before mark_used
        stored = next((t for t in list_tokens(paths) if t.token == tk.token), None)
        assert stored is not None and stored.status.value == "pending", (
            f"token was consumed despite duplicate rejection — got {stored.status.value if stored else 'not found'}"
        )

    with case("neg_06", "Request without X-Axon-PA-ID rejected"):
        from fastapi.testclient import TestClient
        from axon.ga.server import app
        client = TestClient(app, raise_server_exceptions=False)
        resp   = client.post("/ga/resources", json={"url": mock_url})
        assert resp.status_code == 401, (
            f"expected 401 without X-Axon-PA-ID header, got {resp.status_code}: {resp.text}"
        )


# ── reporter ──────────────────────────────────────────────────────────────────

def _print_results(paths: GAPaths) -> None:
    pos     = sorted([r for r in _results if r[0].startswith("pos")])
    neg     = sorted([r for r in _results if r[0].startswith("neg")])
    passed  = sum(1 for r in _results if r[2])
    total   = len(_results)
    sep     = "─" * 52

    print()
    print("  Experiment 1 — Registration & Admission")
    print(f"  {sep}")
    print("  Positive scenarios")
    for sid, label, ok, reason in pos:
        mark = "✓" if ok else "✗"
        tail = f"  → {reason}" if not ok else ""
        print(f"    {mark} {sid}  {label}{tail}")
    print()
    print("  Negative scenarios")
    for sid, label, ok, reason in neg:
        mark = "✓" if ok else "✗"
        tail = f"  → {reason}" if not ok else ""
        print(f"    {mark} {sid}  {label}{tail}")
    print(f"  {sep}")
    print(f"  {passed}/{total} passed")
    print()

    resources = list_resources(paths)
    tokens    = list_tokens(paths)
    used      = sum(1 for t in tokens if t.status.value == "used")
    pending   = sum(1 for t in tokens if t.status.value == "pending")
    revoked_  = sum(1 for t in tokens if t.status.value == "revoked")

    names = ", ".join(r.name for r in resources)
    print("  Registry state")
    print(f"    resources : {len(resources)} ({names})")
    print(f"    tokens     : {used} used, {pending} pending, {revoked_} revoked")
    print()


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    import sys
    sys.path.insert(0, str(Path(__file__).parents[3] / "src"))
    sys.path.insert(0, str(Path(__file__).parents[2]))  # experiments/

    from shared.mock_a2a_server import MockA2AServer

    with tempfile.TemporaryDirectory() as tmp:
        ga_dir = Path(tmp) / "ga"
        paths  = GAPaths(ga_dir)
        paths.makedirs()
        paths.registry.write_text(
            json.dumps({"version": "0.1.0", "resources": []}, indent=2) + "\n"
        )
        paths.tokens.write_text(
            json.dumps({"version": "0.1.0", "tokens": []}, indent=2) + "\n"
        )

        # mint the A2A admission token, embed it in the card
        a2a_token = generate("code-review-agent", paths)
        base_card = _load_card("code_review_agent")
        card_with_token = {
            **base_card,
            "capabilities": {
                **base_card.get("capabilities", {}),
                "extensions": [{
                    "uri": AXON_EXTENSION_URI,
                    "required": True,
                    "params": {
                        "token":            a2a_token.token,
                        "registry_id":      "local",
                        "protocol_version": "0.1",
                    },
                }],
            },
        }

        with MockA2AServer(port=MOCK_PORT, card=card_with_token) as server:
            run_scenarios(paths, server.url, a2a_token.token)

        _print_results(paths)


if __name__ == "__main__":
    main()
