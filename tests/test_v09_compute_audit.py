"""Conformance — v0.9 Compute audit-record shape (compute-contract.md §5).

This is the load-bearing portability piece for Compute conformance.
Every conforming runtime must produce an audit record with the exact
field set documented in BRD §6.3.4 and §5.2/§5.3 of the contract spec.

Strategy:
  - Inspect the auto-generated `compute_audit_log_<name>` Content
    type via the IR exposed through app_info.ir. The IR shape is the
    canonical schema declaration and is available regardless of
    whether any invocations have run yet.
  - For computes that we can actually invoke through the conformance
    adapter (default-CEL via manual trigger), trigger an invocation
    and read the audit record back through the standard CRUD surface.
    Verify the runtime populates the documented fields.

This file does NOT import termin_server. The tests run against any
conforming runtime via the adapter pattern.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

# Per compute-contract.md §5.2 — base-shape audit columns required
# for every contract (default-CEL, llm, ai-agent).
_BASE_AUDIT_FIELDS = {
    "compute_name",
    "invocation_id",
    "trigger",
    "started_at",
    "completed_at",
    "latency_ms",
    "outcome",
    "trace",
    "error_message",
    "invoked_by_principal_id",
    "invoked_by_display_name",
    "on_behalf_of_principal_id",
}

# Per compute-contract.md §5.3 / BRD §6.3.4 — extra columns required
# for llm and ai-agent contracts only. NOT present on default-CEL.
_LLM_EXTRA_FIELDS = {
    "provider_product",
    "model_identifier",
    "provider_config_hash",
    "prompt_as_sent",
    "sampling_params",
    "tool_calls",
    "refusal_reason",
    "cost_units",
    "cost_unit_type",
    "cost_currency_amount",
}


# ──────────────────────────────────────────────────────────────────────
# Helpers — extract audit Content schema from IR
# ──────────────────────────────────────────────────────────────────────


def _audit_content(ir: dict, audit_snake: str) -> dict | None:
    """Find the audit Content schema by snake name."""
    for cs in ir.get("content", []):
        name = cs.get("name", {})
        if isinstance(name, dict) and name.get("snake") == audit_snake:
            return cs
    return None


def _field_names(content_schema: dict) -> set[str]:
    return {f["name"] for f in content_schema.get("fields", [])}


def _outcome_field(content_schema: dict) -> dict | None:
    for f in content_schema.get("fields", []):
        if f.get("name") == "outcome":
            return f
    return None


# ──────────────────────────────────────────────────────────────────────
# § 5.2 — Base shape (every contract)
# ──────────────────────────────────────────────────────────────────────


class TestBaseAuditShape:
    """Per compute-contract.md §5.2 — every audit Content carries the
    base column set regardless of which contract the compute uses."""

    def test_cel_audit_has_base_fields(self, compute_demo, compute_demo_ir):
        """compute_demo's `calculate order total` is a default-CEL
        compute with audit_level=actions. Its audit Content must
        carry the full base shape.

        IR-only fixtures (``*_ir``) don't close the cached TestClient
        on teardown; we pair them with the session-scoped app
        fixtures (``compute_demo``, ``agent_simple``, etc.) whose
        cleanup runs at session end so pytest exits cleanly.
        """
        audit = _audit_content(
            compute_demo_ir, "compute_audit_log_calculate_order_total")
        assert audit is not None, (
            "compute_audit_log_calculate_order_total Content "
            "must be auto-generated for an audit_level=actions CEL "
            "compute"
        )
        names = _field_names(audit)
        missing = _BASE_AUDIT_FIELDS - names
        assert not missing, f"missing base audit fields on CEL audit: {missing}"

    def test_llm_audit_has_base_fields(self, agent_simple, agent_simple_ir):
        audit = _audit_content(
            agent_simple_ir, "compute_audit_log_complete")
        assert audit is not None, (
            "agent_simple's `complete` (llm) compute must auto-generate "
            "compute_audit_log_complete"
        )
        names = _field_names(audit)
        missing = _BASE_AUDIT_FIELDS - names
        assert not missing, f"missing base audit fields on llm audit: {missing}"

    def test_agent_audit_has_base_fields(self, agent_chatbot, agent_chatbot_ir):
        audit = _audit_content(
            agent_chatbot_ir, "compute_audit_log_reply")
        assert audit is not None, (
            "agent_chatbot's `reply` (ai-agent) compute must auto-"
            "generate compute_audit_log_reply"
        )
        names = _field_names(audit)
        missing = _BASE_AUDIT_FIELDS - names
        assert not missing, f"missing base audit fields on agent audit: {missing}"


# ──────────────────────────────────────────────────────────────────────
# § 5.2 — latency_ms rename (no duration_ms residue)
# ──────────────────────────────────────────────────────────────────────


class TestLatencyMsRename:
    """Per compute-contract.md §5.2 — v0.9 renamed `duration_ms` to
    `latency_ms`. The old column must NOT appear on any v0.9 audit
    Content."""

    def test_cel_audit_uses_latency_ms(self, compute_demo, compute_demo_ir):
        audit = _audit_content(
            compute_demo_ir, "compute_audit_log_calculate_order_total")
        names = _field_names(audit)
        assert "latency_ms" in names
        assert "duration_ms" not in names, (
            "v0.9 audit must use `latency_ms`, not the v0.8 `duration_ms`"
        )

    def test_llm_audit_uses_latency_ms(self, agent_simple, agent_simple_ir):
        audit = _audit_content(
            agent_simple_ir, "compute_audit_log_complete")
        names = _field_names(audit)
        assert "latency_ms" in names
        assert "duration_ms" not in names

    def test_agent_audit_uses_latency_ms(self, agent_chatbot, agent_chatbot_ir):
        audit = _audit_content(
            agent_chatbot_ir, "compute_audit_log_reply")
        names = _field_names(audit)
        assert "latency_ms" in names
        assert "duration_ms" not in names


# ──────────────────────────────────────────────────────────────────────
# § 5.2 — outcome enum widened with `refused`
# ──────────────────────────────────────────────────────────────────────


class TestOutcomeEnum:
    """Per compute-contract.md §5.2 — the `outcome` enum widened in
    v0.9 to include `refused` alongside `success` and `error`."""

    def test_llm_outcome_includes_refused(self, agent_simple, agent_simple_ir):
        audit = _audit_content(
            agent_simple_ir, "compute_audit_log_complete")
        outcome = _outcome_field(audit)
        assert outcome is not None
        values = set(outcome.get("enum_values") or [])
        assert "success" in values
        assert "error" in values
        assert "refused" in values, (
            f"v0.9 outcome enum must include `refused`; got {values}"
        )

    def test_agent_outcome_includes_refused(self, agent_chatbot, agent_chatbot_ir):
        audit = _audit_content(
            agent_chatbot_ir, "compute_audit_log_reply")
        outcome = _outcome_field(audit)
        assert outcome is not None
        values = set(outcome.get("enum_values") or [])
        assert "refused" in values

    def test_cel_outcome_includes_refused(self, compute_demo, compute_demo_ir):
        """CEL computes can't invoke system_refuse, but the audit
        enum is uniform across contracts so v0.9 readers don't need
        contract-specific enum logic."""
        audit = _audit_content(
            compute_demo_ir, "compute_audit_log_calculate_order_total")
        outcome = _outcome_field(audit)
        assert outcome is not None
        values = set(outcome.get("enum_values") or [])
        assert "refused" in values


# ──────────────────────────────────────────────────────────────────────
# § 5.3 — LLM/agent extras present (BRD §6.3.4 reproducibility)
# ──────────────────────────────────────────────────────────────────────


class TestLlmAgentExtras:
    """Per compute-contract.md §5.3 — llm and ai-agent audit Contents
    carry the BRD §6.3.4 reproducibility columns; default-CEL
    audits do NOT."""

    def test_llm_audit_has_extras(self, agent_simple, agent_simple_ir):
        audit = _audit_content(
            agent_simple_ir, "compute_audit_log_complete")
        names = _field_names(audit)
        missing = _LLM_EXTRA_FIELDS - names
        assert not missing, (
            f"llm audit missing BRD §6.3.4 columns: {missing}"
        )

    def test_agent_audit_has_extras(self, agent_chatbot, agent_chatbot_ir):
        audit = _audit_content(
            agent_chatbot_ir, "compute_audit_log_reply")
        names = _field_names(audit)
        missing = _LLM_EXTRA_FIELDS - names
        assert not missing, (
            f"ai-agent audit missing BRD §6.3.4 columns: {missing}"
        )

    def test_cel_audit_lacks_extras(self, compute_demo, compute_demo_ir):
        """default-CEL audits MUST NOT carry the LLM extras —
        provider_product, model_identifier etc. don't apply.
        Negative case is part of the contract."""
        audit = _audit_content(
            compute_demo_ir, "compute_audit_log_calculate_order_total")
        names = _field_names(audit)
        leaked = _LLM_EXTRA_FIELDS & names
        assert not leaked, (
            f"default-CEL audit should not carry LLM extras; got {leaked}"
        )


# ──────────────────────────────────────────────────────────────────────
# § 5.2 — Round-trip: invoke a CEL compute, read its audit row
# ──────────────────────────────────────────────────────────────────────


class TestCelAuditRoundTrip:
    """Per compute-contract.md §5.2 — when a default-CEL compute
    invokes successfully via the manual ``/trigger`` endpoint, the
    runtime MUST write an audit row with the base shape populated.

    v0.9.1 reference runtime added the ``_execute_cel_compute``
    helper that runs the CEL body and writes the audit row from
    the manual-trigger path. Previously this branch printed
    ``provider 'None' not supported for event triggers`` and
    silently dropped the audit, leaving §5.2 unsatisfied.
    """

    def test_calculate_order_total_audit_row_shape(
        self, compute_demo,
    ):
        compute_demo.set_role("order manager")
        # Seed an order; trigger the compute; read the audit log.
        r_create = compute_demo.post(
            "/api/v1/orders",
            json={"customer": "AuditAcme", "total": 100, "priority": "medium"},
        )
        assert r_create.status_code == 201, r_create.text

        r_trig = compute_demo.post(
            "/api/v1/compute/calculate_order_total/trigger",
            json={"record": r_create.json(), "content_name": "orders"},
        )
        assert r_trig.status_code == 200, r_trig.text
        # Allow the audit write to land.
        time.sleep(0.5)

        r_audit = compute_demo.get(
            "/api/v1/compute_audit_log_calculate_order_total")
        assert r_audit.status_code == 200, r_audit.text
        rows = r_audit.json()
        assert isinstance(rows, list)
        # v0.9.1: the manual-trigger path MUST produce an audit row.
        assert rows, (
            "manual trigger of a default-CEL compute MUST write an "
            "audit row per spec §5.2 — empty list indicates the "
            "runtime is skipping audit on the manual path"
        )
        row = rows[-1]
        assert row.get("compute_name")
        assert row.get("latency_ms") is not None
        assert row.get("outcome") in (
            "success", "error", "refused", "timeout", "cancelled",
        )
        # Trigger MUST be the manual marker, not an event trigger.
        assert row.get("trigger") == "manual"
