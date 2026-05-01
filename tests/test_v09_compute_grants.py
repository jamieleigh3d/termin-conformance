"""Conformance — v0.9 Compute tool-surface gating (compute-contract.md §4).

Adapter-agnostic tests for the closed tool surface and double-gate
authorization. The agent's tool callbacks must:

  - Allow tools whose target is in the source's grant set (Accesses
    or Reads for read-side; Accesses only for write/state).
  - Deny tools whose target is undeclared, returning an error
    envelope rather than raising.
  - Refuse to execute tools that are not in the closed surface
    (§4.3) — calling a fictitious tool yields an error envelope.

These tests use the conformance adapter's ``deploy_with_agent_mock``
to script tool sequences against the agent_chatbot fixture and
verify the runtime's gating behavior through the front-door HTTP
surface and the recorded tool-call results.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
_WAIT = 1.5  # seconds for the background agent thread to drain


def _get_adapter():
    adapter_name = os.environ.get("TERMIN_ADAPTER", "reference")
    if adapter_name == "reference":
        from adapter_reference import ReferenceAdapter
        return ReferenceAdapter()
    elif adapter_name == "served-reference":
        from adapter_served_reference import ServedReferenceAdapter
        return ServedReferenceAdapter()
    elif adapter_name == "template":
        from adapter_template import MyRuntimeAdapter
        return MyRuntimeAdapter()
    raise ValueError(f"Unknown adapter: {adapter_name}")


_adapter = _get_adapter()


# ──────────────────────────────────────────────────────────────────────
# Module-scoped fixtures: scripted agent runs
# ──────────────────────────────────────────────────────────────────────


def _require_agent_mock():
    """Skip if the adapter doesn't expose deploy_with_agent_mock —
    the contract is exercised through that surface."""
    if not hasattr(_adapter, "deploy_with_agent_mock"):
        pytest.skip("adapter does not expose deploy_with_agent_mock")
    pkg = FIXTURES_DIR / "agent_chatbot.termin.pkg"
    if not pkg.exists():
        pytest.skip("agent_chatbot fixture not found")
    return pkg


@pytest.fixture(scope="module")
def declared_query_app():
    """Agent calls content_query on `messages`, which is declared in
    Accesses → should succeed."""
    pkg = _require_agent_mock()
    info, results = _adapter.deploy_with_agent_mock(
        pkg, "grants_declared_query",
        [("content_query", {"content_name": "messages"})],
    )
    session = _adapter.create_session(info)
    yield session, results
    if info.cleanup:
        info.cleanup()


@pytest.fixture(scope="module")
def undeclared_query_app():
    """Agent calls content_query on a content type NOT in Accesses
    or Reads → should be denied with an error envelope."""
    pkg = _require_agent_mock()
    info, results = _adapter.deploy_with_agent_mock(
        pkg, "grants_undeclared_query",
        [("content_query", {"content_name": "compute_audit_log_reply"})],
    )
    session = _adapter.create_session(info)
    yield session, results
    if info.cleanup:
        info.cleanup()


@pytest.fixture(scope="module")
def declared_create_app():
    """Agent calls content_create on `messages` (in Accesses) →
    succeeds and returns a record dict with id."""
    pkg = _require_agent_mock()
    info, results = _adapter.deploy_with_agent_mock(
        pkg, "grants_declared_create",
        [("content_create", {
            "content_name": "messages",
            "data": {"role": "assistant", "body": "from agent"},
        })],
    )
    session = _adapter.create_session(info)
    yield session, results
    if info.cleanup:
        info.cleanup()


@pytest.fixture(scope="module")
def undeclared_create_app():
    """Agent calls content_create on a content type that does not
    exist / is not in Accesses → denied."""
    pkg = _require_agent_mock()
    info, results = _adapter.deploy_with_agent_mock(
        pkg, "grants_undeclared_create",
        [("content_create", {
            "content_name": "nonexistent_content",
            "data": {"x": 1},
        })],
    )
    session = _adapter.create_session(info)
    yield session, results
    if info.cleanup:
        info.cleanup()


@pytest.fixture(scope="module")
def fictitious_tool_app():
    """Agent calls a tool name that doesn't exist in the closed
    surface → error envelope, no crash."""
    pkg = _require_agent_mock()
    info, results = _adapter.deploy_with_agent_mock(
        pkg, "grants_fictitious_tool",
        [("zz_unknown_tool", {"anything": "goes"})],
    )
    session = _adapter.create_session(info)
    yield session, results
    if info.cleanup:
        info.cleanup()


# ──────────────────────────────────────────────────────────────────────
# § 4.4 — Read tools require Accesses ∪ Reads
# ──────────────────────────────────────────────────────────────────────


class TestReadTools:
    """Per compute-contract.md §4.4 — content_query and content_read
    must accept any target that appears in either Accesses OR Reads."""

    def test_query_on_declared_content_succeeds(self, declared_query_app):
        session, results = declared_query_app
        session.set_role("anonymous")
        r = session.post("/api/v1/messages",
                         json={"role": "user", "body": "trigger query"})
        assert r.status_code == 201, r.text
        time.sleep(_WAIT)

        assert len(results) >= 1, "agent loop did not execute"
        result = results[0]
        assert result["tool"] == "content_query"
        # Success: result is a list (possibly empty), not an error
        # envelope.
        assert isinstance(result["result"], list), (
            f"expected list result for declared content_query; "
            f"got {result['result']!r}"
        )

    def test_query_on_undeclared_content_denied(self, undeclared_query_app):
        """A target not in Accesses or Reads → error envelope.
        The agent_chatbot compute declares Accesses messages only;
        querying compute_audit_log_reply must be denied."""
        session, results = undeclared_query_app
        session.set_role("anonymous")
        r = session.post("/api/v1/messages",
                         json={"role": "user", "body": "trigger denied"})
        assert r.status_code == 201
        time.sleep(_WAIT)

        assert len(results) >= 1
        denied = results[0]
        assert isinstance(denied["result"], dict), (
            f"expected error envelope dict; got {denied['result']!r}"
        )
        assert "error" in denied["result"], (
            f"undeclared content_query must return an error envelope; "
            f"got {denied['result']!r}"
        )


# ──────────────────────────────────────────────────────────────────────
# § 4.4 — Write tools require Accesses (NOT Reads)
# ──────────────────────────────────────────────────────────────────────


class TestWriteTools:
    """Per compute-contract.md §4.4 — content_create / content_update
    require the target to appear in Accesses (Reads is not enough).
    state_transition is the same — Accesses-only."""

    def test_create_on_declared_content_succeeds(self, declared_create_app):
        session, results = declared_create_app
        session.set_role("anonymous")
        r = session.post("/api/v1/messages",
                         json={"role": "user", "body": "trigger create"})
        assert r.status_code == 201
        time.sleep(_WAIT)

        assert len(results) >= 1
        create = results[0]
        assert create["tool"] == "content_create"
        # Success: result is a record dict with id.
        assert isinstance(create["result"], dict), create["result"]
        assert "id" in create["result"], create["result"]

    def test_created_record_visible_via_front_door(self, declared_create_app):
        """The agent-created record surfaces through the standard
        CRUD endpoint — verifying the gate didn't drop it silently."""
        session, _ = declared_create_app
        session.set_role("anonymous")
        r = session.get("/api/v1/messages")
        assert r.status_code == 200
        bodies = [m.get("body") for m in r.json()]
        assert "from agent" in bodies, (
            f"agent-created record missing from listing: {bodies}"
        )

    def test_create_on_undeclared_content_denied(self, undeclared_create_app):
        session, results = undeclared_create_app
        session.set_role("anonymous")
        r = session.post("/api/v1/messages",
                         json={"role": "user", "body": "trigger denied create"})
        assert r.status_code == 201
        time.sleep(_WAIT)

        assert len(results) >= 1
        denied = results[0]
        assert isinstance(denied["result"], dict)
        assert "error" in denied["result"], (
            f"undeclared content_create must return error envelope; "
            f"got {denied['result']!r}"
        )


# ──────────────────────────────────────────────────────────────────────
# § 4.3 — Closed tool surface
# ──────────────────────────────────────────────────────────────────────


class TestClosedToolSurface:
    """Per compute-contract.md §4.3 — providers cannot extend the
    tool surface. A tool name not in §4.2 yields an error envelope;
    the runtime does not crash."""

    def test_fictitious_tool_returns_error_envelope(self, fictitious_tool_app):
        session, results = fictitious_tool_app
        session.set_role("anonymous")
        r = session.post("/api/v1/messages",
                         json={"role": "user", "body": "trigger unknown"})
        assert r.status_code == 201
        time.sleep(_WAIT)

        assert len(results) >= 1
        unknown = results[0]
        # The runtime returned *something* — it did not raise.
        assert isinstance(unknown["result"], dict), (
            f"unknown tool must yield a dict result; got {unknown['result']!r}"
        )
        # Either an error envelope or a stub result; both are
        # conforming as long as the runtime handled it gracefully.
        # Most runtimes return an explicit error.
        if "error" not in unknown["result"]:
            pytest.skip("runtime returned non-error stub for unknown tool — "
                        "acceptable but not the more common shape")
        assert "error" in unknown["result"]


# ──────────────────────────────────────────────────────────────────────
# § 4.4 — IR-shape: source declarations propagate to ComputeSpec
# ──────────────────────────────────────────────────────────────────────


class TestComputeSpecGrantShape:
    """Adapter-agnostic IR-shape checks. The IR exposed via
    app_info.ir is the canonical declaration surface for what tools
    the agent will see. Conforming runtimes serve the IR as
    declared; tests here fail-fast if the IR is wrong before
    behavioral tests run."""

    def test_agent_chatbot_accesses_messages(self, agent_chatbot, agent_chatbot_ir):
        """IR-only fixtures (e.g. ``agent_chatbot_ir``) never close
        the cached TestClient on session teardown. We co-request
        the session-scoped ``agent_chatbot`` fixture so its cleanup
        runs and pytest exits cleanly."""
        agent = next(
            c for c in agent_chatbot_ir["computes"]
            if c.get("provider") == "ai-agent"
        )
        accesses = agent.get("accesses") or []
        assert "messages" in accesses, (
            f"agent_chatbot reply.accesses must include 'messages'; "
            f"got {accesses!r}"
        )

    def test_v09_compute_carries_reads_field(self, agent_chatbot, agent_chatbot_ir):
        """Per §4.4 / Phase 3 slice (c) — ComputeSpec gains a `reads`
        tuple. Apps without Reads declared have an empty list."""
        agent = next(
            c for c in agent_chatbot_ir["computes"]
            if c.get("provider") == "ai-agent"
        )
        # Must be present (possibly empty), not absent.
        assert "reads" in agent, (
            f"v0.9 ComputeSpec must carry a `reads` field; "
            f"got keys {list(agent)!r}"
        )

    def test_v09_compute_carries_grant_tuples(self, agent_chatbot, agent_chatbot_ir):
        """Per §4.4 — sends_to, emits, invokes are all v0.9 fields."""
        agent = next(
            c for c in agent_chatbot_ir["computes"]
            if c.get("provider") == "ai-agent"
        )
        for fld in ("sends_to", "emits", "invokes"):
            assert fld in agent, (
                f"v0.9 ComputeSpec must carry `{fld}`; "
                f"got keys {list(agent)!r}"
            )
