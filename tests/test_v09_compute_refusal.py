"""Conformance — v0.9 Compute refusal semantics (compute-contract.md §6).

Adapter-agnostic tests for:
  - The `compute_refusals` sidecar Content type — auto-generated for
    any app with at least one ai-agent compute (§6.3).
  - The sidecar's required field set (§6.3).
  - End-to-end refusal: agent calls system_refuse → audit row has
    outcome=refused with refusal_reason, sidecar row exists with
    matching invocation_id.
  - Apps without ai-agent computes do NOT get the sidecar.

These tests use the conformance adapter's ``deploy_with_agent_mock``
to script a system_refuse tool call and verify the runtime's
refusal-propagation behavior through the front-door HTTP surface.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
_WAIT = 1.5  # seconds for the background agent thread to drain


# Per compute-contract.md §6.3 — required sidecar fields.
_SIDECAR_FIELDS = {
    "compute_name",
    "invocation_id",
    "reason",
    "refused_at",
    "invoked_by_principal_id",
    "on_behalf_of_principal_id",
}


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
# § 6.3 — Sidecar Content auto-generation
# ──────────────────────────────────────────────────────────────────────


class TestSidecarGeneration:
    """Per compute-contract.md §6.3 — apps with at least one ai-agent
    compute auto-generate the `compute_refusals` Content type. Apps
    with no ai-agent computes do NOT."""

    def test_sidecar_present_for_agent_chatbot(self, agent_chatbot, agent_chatbot_ir):
        """IR-only fixtures don't drive cleanup; we co-request the
        session-scoped app fixture so its cleanup runs at session
        teardown and pytest exits cleanly."""
        sidecar = _content_by_snake(agent_chatbot_ir, "compute_refusals")
        assert sidecar is not None, (
            "Apps with at least one ai-agent compute must auto-"
            "generate the compute_refusals sidecar Content"
        )

    def test_sidecar_has_required_fields(self, agent_chatbot, agent_chatbot_ir):
        sidecar = _content_by_snake(agent_chatbot_ir, "compute_refusals")
        assert sidecar is not None
        names = _field_names(sidecar)
        missing = _SIDECAR_FIELDS - names
        assert not missing, (
            f"compute_refusals sidecar missing fields: {missing}"
        )

    def test_sidecar_absent_for_llm_only_app(self, agent_simple, agent_simple_ir):
        """agent_simple has only an `llm` compute — no ai-agent
        compute means no sidecar. The contract is asymmetric: only
        `system_refuse` (an agent tool) writes the sidecar, so apps
        without agents have no need for it."""
        sidecar = _content_by_snake(agent_simple_ir, "compute_refusals")
        assert sidecar is None, (
            "Apps with no ai-agent computes do not need the "
            "compute_refusals sidecar"
        )

    def test_sidecar_absent_for_cel_only_app(self, compute_demo, compute_demo_ir):
        """compute_demo has only default-CEL computes."""
        sidecar = _content_by_snake(compute_demo_ir, "compute_refusals")
        assert sidecar is None


# ──────────────────────────────────────────────────────────────────────
# § 6.1 — system_refuse end-to-end through the agent loop
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
    write the audit row with outcome=refused and the sidecar row."""
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
    """Per compute-contract.md §6.2 — system_refuse triggers the full
    refusal path: audit row gets outcome=refused, sidecar gets a
    row, both share invocation_id, refusal event fires."""

    def test_system_refuse_executes(self, refused_agent_app):
        """The mock agent's scripted system_refuse call goes through
        the gate (always-available) and is captured."""
        session, _info, results = refused_agent_app
        session.set_role("anonymous")
        r = session.post("/api/v1/messages",
                         json={"role": "user", "body": "trigger refusal"})
        assert r.status_code == 201
        time.sleep(_WAIT)

        # The mock recorded the system_refuse call.
        assert len(results) >= 1
        refuse = results[0]
        assert refuse["tool"] == "system_refuse"
        # The result is an acknowledgment dict — system_refuse never
        # raises; it captures the reason and tells the agent to keep
        # going (until set_output or max_turns terminate the loop).
        assert isinstance(refuse["result"], dict), refuse["result"]

    def test_audit_row_has_outcome_refused(self, refused_agent_app):
        """After the refused invocation, the audit row's outcome
        must be `refused` and refusal_reason must be populated."""
        session, _info, _results = refused_agent_app
        session.set_role("anonymous")
        # Read back the audit log via the standard CRUD surface.
        r = session.get("/api/v1/compute_audit_log_reply")
        if r.status_code == 403:
            pytest.skip("audit content not visible to the test role")
        assert r.status_code == 200, r.text
        rows = r.json()
        # Find the most recent refused row.
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

    def test_sidecar_row_matches_audit(self, refused_agent_app):
        """Sidecar row must exist with the same invocation_id and
        the exact reason string passed to system_refuse."""
        session, _info, _results = refused_agent_app
        session.set_role("anonymous")
        r = session.get("/api/v1/compute_refusals")
        if r.status_code == 403:
            pytest.skip("sidecar not visible to the test role")
        assert r.status_code == 200, r.text
        rows = r.json()
        # Find the row with our reason.
        matches = [
            row for row in rows
            if row.get("reason", "").startswith("policy")
        ]
        assert matches, (
            f"compute_refusals must record a row for the system_refuse "
            f"call; got {rows!r}"
        )
        row = matches[-1]
        # The reason on the sidecar is the exact string passed to
        # system_refuse — not an LLM-rephrased version.
        assert row["reason"] == "policy: cannot answer", row

        # Cross-check the audit by invocation_id.
        ra = session.get("/api/v1/compute_audit_log_reply")
        assert ra.status_code == 200
        ar = [
            r for r in ra.json()
            if r.get("invocation_id") == row.get("invocation_id")
        ]
        assert ar, (
            f"sidecar row's invocation_id {row.get('invocation_id')!r} "
            f"must join to an audit row"
        )
