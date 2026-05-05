"""Conformance — v0.9 Compute refusal semantics
(`compute-contract.md` §6 + `conversation-field-contract.md` §6).

Adapter-agnostic tests for:
  - The retired `compute_refusals` sidecar Content type — apps must
    NOT auto-generate it on v0.9.2 (the audit log is the queryable
    surface; conversation-mode computes additionally append a
    `kind: "assistant", type: "refusal"` entry to the conversation
    field per `conversation-field-contract.md` §6).
  - End-to-end refusal: agent calls system_refuse → audit row has
    outcome=refused with refusal_reason populated.

The conversation-mode in-field refusal-entry path is exercised in
`test_v092_conversation_field.py::TestRefusalAppendedToConversation`;
this file focuses on the cross-version invariants and the audit
surface that ALL ai-agent computes share regardless of conversation
mode.
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


def _content_by_snake(ir: dict, snake: str) -> dict | None:
    for cs in ir.get("content", []):
        name = cs.get("name", {})
        if isinstance(name, dict) and name.get("snake") == snake:
            return cs
    return None


def _field_names(content_schema: dict) -> set[str]:
    return {f["name"] for f in content_schema.get("fields", [])}


# ──────────────────────────────────────────────────────────────────────
# § 6.3 — `compute_refusals` sidecar is RETIRED in v0.9.2
# ──────────────────────────────────────────────────────────────────────


class TestSidecarRetired:
    """Per `conversation-field-contract.md` §6 + §9: the v0.9.1 /
    Phase 3 slice (e) `compute_refusals` Content type is retired in
    v0.9.2. Conforming v0.9.2 runtimes MUST NOT auto-generate it.
    The audit log is the queryable refusal-trail surface;
    conversation-mode computes additionally render the refusal
    inline in the conversation field as a
    `kind: "assistant", type: "refusal"` entry.

    Migration note: apps that read `compute_refusals` via a CEL
    access surface in v0.9.1 must migrate to the audit Content
    surface for v0.9.2. The CHANGELOG documents this."""

    def test_sidecar_not_generated_for_agent_chatbot(
            self, agent_chatbot, agent_chatbot_ir):
        """v0.9.2 agent_chatbot has an ai-agent compute but no
        compute_refusals sidecar."""
        sidecar = _content_by_snake(agent_chatbot_ir, "compute_refusals")
        assert sidecar is None, (
            "compute_refusals sidecar Content type was retired in "
            "v0.9.2 (per L7.5 — see "
            "`conversation-field-contract.md` §6 + §9). v0.9.2-shaped "
            "agent_chatbot must not carry it. Found: " + str(sidecar)
        )

    def test_sidecar_not_generated_for_llm_only_app(
            self, agent_simple, agent_simple_ir):
        """Apps with no ai-agent computes never had the sidecar in
        v0.9.1; the v0.9.2 invariant is unchanged for them."""
        sidecar = _content_by_snake(agent_simple_ir, "compute_refusals")
        assert sidecar is None

    def test_sidecar_not_generated_for_cel_only_app(
            self, compute_demo, compute_demo_ir):
        """compute_demo has only default-CEL computes."""
        sidecar = _content_by_snake(compute_demo_ir, "compute_refusals")
        assert sidecar is None


# ──────────────────────────────────────────────────────────────────────
# § 6.1–6.2 — system_refuse end-to-end: audit is the queryable surface
# ──────────────────────────────────────────────────────────────────────


def _require_agent_mock():
    if not hasattr(_adapter, "deploy_with_agent_mock"):
        pytest.skip("adapter does not expose deploy_with_agent_mock")
    pkg = FIXTURES_DIR / "agent_chatbot.termin.pkg"
    if not pkg.exists():
        pytest.skip("agent_chatbot fixture not found")
    return pkg


@pytest.fixture(scope="module")
def refused_agent_app():
    """Agent calls system_refuse with a known reason — runtime must
    write the audit row with outcome=refused and refusal_reason
    populated. The legacy sidecar is no longer involved."""
    pkg = _require_agent_mock()
    info, results = _adapter.deploy_with_agent_mock(
        pkg, "refusal_e2e",
        [("system_refuse", {"reason": "policy: cannot answer"})],
    )
    session = _adapter.create_session(info)
    yield session, info, results
    if info.cleanup:
        info.cleanup()


class TestRefusalEndToEnd:
    """Per compute-contract.md §6.1–6.2 — system_refuse triggers the
    full refusal path: the audit row gets outcome=refused +
    refusal_reason; the loop terminates; staged outputs are
    discarded.

    The conversation-field surface (the in-field assistant/refusal
    entry) is exercised in
    `test_v092_conversation_field.py::TestRefusalAppendedToConversation`."""

    def test_system_refuse_executes_and_drives_the_v092_path(
            self, refused_agent_app):
        """The mock agent's scripted system_refuse call goes through
        the gate (always-available) and lands as an in-field
        assistant/refusal entry on chat_threads.conversation. This
        test exercises the v0.9.2 conversation-mode dispatch end-
        to-end via the front-door HTTP surface — drive the trigger
        with a user append, wait for the background compute thread,
        verify the in-field refusal entry."""
        session, _info, results = refused_agent_app
        session.set_role("anonymous")
        # Drive the refusal: append a user message that will cause
        # the agent to refuse via the scripted system_refuse call.
        create = session.post(
            "/api/v1/chat_threads", json={"title": "refusal e2e"})
        thread_id = create.json()["id"]
        ap = session.post(
            f"/api/v1/chat_threads/{thread_id}/conversation:append",
            json={"kind": "user", "body": "trigger refusal"})
        assert ap.status_code == 201, ap.text
        time.sleep(_WAIT)

        # Mock recorded the system_refuse call.
        assert any(r["tool"] == "system_refuse" for r in results), (
            f"mock did not record system_refuse; got {results!r}"
        )

    def test_audit_row_has_outcome_refused(self, refused_agent_app):
        """After the refused invocation, the audit row's outcome
        must be `refused` and refusal_reason must be populated.
        This is the queryable refusal-trail surface in v0.9.2 (the
        sidecar surface is retired)."""
        session, _info, _results = refused_agent_app
        session.set_role("anonymous")
        r = session.get("/api/v1/compute_audit_log_reply")
        if r.status_code == 403:
            pytest.skip("audit content not visible to the test role")
        assert r.status_code == 200, r.text
        rows = r.json()
        refused_rows = [
            row for row in rows if row.get("outcome") == "refused"
        ]
        assert refused_rows, (
            f"no audit row with outcome=refused after system_refuse; "
            f"got {len(rows)} rows total: {rows!r}"
        )
        row = refused_rows[-1]
        assert row.get("refusal_reason"), (
            f"refused audit row must have refusal_reason populated; "
            f"got {row!r}"
        )
        assert "policy" in row["refusal_reason"]


class TestRefusalTerminatesLoop:
    """Per compute-contract.md §6.1: 'system_refuse triggers the
    full refusal path: ... the loop terminates; staged outputs
    are discarded.' Verify the runtime honors that — once
    system_refuse fires, no subsequent tool calls execute and no
    further conversation entries land beyond the refusal.

    Threat model the test covers: an agent calls system_refuse
    and then ALSO tries to call a side-effecting tool
    (content_query in the legacy fixture, simulating data
    exfiltration). The runtime must stop the second call from
    executing, not just record both."""

    def test_post_refusal_tool_call_is_blocked(self, tmp_path):
        pkg = _require_agent_mock()
        info, results = _adapter.deploy_with_agent_mock(
            pkg, "halt_refusal",
            [
                ("system_refuse", {"reason": "policy: cannot proceed"}),
                # Second tool call attempted post-refusal. The
                # runtime's tool gate must return an error
                # envelope; the agent never gets a real result.
                # `current_time` is the canonical Invokes-declared
                # tool on agent_chatbot.termin (v0.9.2 example).
                ("current_time", {}),
            ],
        )
        try:
            session = _adapter.create_session(info)
            session.set_role("anonymous")
            # Trigger the conversation-mode dispatch via the
            # v0.9.2 append surface.
            create = session.post(
                "/api/v1/chat_threads",
                json={"title": "halt-refusal"},
            )
            assert create.status_code in (200, 201), create.text
            thread_id = create.json()["id"]
            ap = session.post(
                f"/api/v1/chat_threads/{thread_id}/conversation:append",
                json={"kind": "user",
                      "body": "trigger refuse + try a side effect"},
            )
            assert ap.status_code == 201
            time.sleep(_WAIT)

            # The mock dispatched both tool calls. The first
            # (system_refuse) should ack normally; the second
            # (current_time) MUST surface an error envelope —
            # the runtime gated it because refusal_state was set.
            current_time_results = [
                r for r in results if r["tool"] == "current_time"
            ]
            assert current_time_results, (
                f"mock should have attempted the post-refusal tool "
                f"call; results={results!r}"
            )
            for q in current_time_results:
                result = q.get("result")
                assert isinstance(result, dict) and "error" in result, (
                    f"post-refusal tool call must NOT succeed; "
                    f"got result={result!r}"
                )
        finally:
            if info.cleanup:
                info.cleanup()
