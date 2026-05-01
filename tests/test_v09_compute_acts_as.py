"""Conformance — v0.9 Compute Acts-as principal substitution
(compute-contract.md §7).

Adapter-agnostic IR-shape and behavior tests for the two agent
execution modes:

  - Delegate mode (default): the agent acts on behalf of the
    triggering caller; audit invoked_by stamps from the actual
    caller's principal.
  - Service mode (`Acts as service`): the agent is its own
    principal with its own roles via the deploy config's identity
    role_mappings; audit invoked_by stamps from the synthesized
    service principal, on_behalf_of is empty/null.

The IR's `identity_mode` field on each ComputeSpec is the canonical
declaration. The runtime stamps audit rows accordingly.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
_WAIT = 1.5


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


def _compute(ir: dict, snake: str) -> dict | None:
    for c in ir.get("computes", []):
        name = c.get("name", {})
        # Compute names are dicts in the IR ({snake, display, pascal});
        # tolerate string-shaped names from older runtimes.
        if isinstance(name, dict):
            if name.get("snake") == snake:
                return c
        elif isinstance(name, str) and name == snake:
            return c
    return None


# ──────────────────────────────────────────────────────────────────────
# § 7 — Default identity_mode is delegate
# ──────────────────────────────────────────────────────────────────────


class TestIdentityModeDeclaration:
    """Per compute-contract.md §7 — `identity_mode` defaults to
    `delegate`. The IR carries the value declared in source (or the
    default when absent). Conforming runtimes consume this field
    when stamping audit records."""

    def test_agent_chatbot_default_is_delegate(self, agent_chatbot, agent_chatbot_ir):
        """agent_chatbot's `reply` has no Acts as line; its
        identity_mode must default to delegate.

        IR-only fixtures don't close the cached TestClient on
        session teardown; we pair them with the session-scoped app
        fixture so cleanup runs and pytest exits cleanly.
        """
        reply = _compute(agent_chatbot_ir, "reply")
        assert reply is not None
        assert reply.get("identity_mode") == "delegate", (
            f"default identity_mode must be 'delegate'; "
            f"got {reply.get('identity_mode')!r}"
        )

    def test_agent_simple_default_is_delegate(self, agent_simple, agent_simple_ir):
        complete = _compute(agent_simple_ir, "complete")
        assert complete is not None
        assert complete.get("identity_mode") == "delegate"

    def test_security_agent_scanner_is_service(self, security_agent, security_agent_ir):
        """security_agent declares `Identity: service` (or
        `Acts as service`) on its scanner compute. The IR's
        identity_mode is `service`."""
        scanner = _compute(security_agent_ir, "scanner")
        assert scanner is not None, (
            "security_agent should declare a `scanner` compute"
        )
        assert scanner.get("identity_mode") == "service", (
            f"scanner declared service mode in source; identity_mode "
            f"must be 'service' in the IR. Got {scanner.get('identity_mode')!r}"
        )

    def test_security_agent_remediator_is_service(self, security_agent, security_agent_ir):
        remediator = _compute(security_agent_ir, "remediator")
        assert remediator is not None
        assert remediator.get("identity_mode") == "service"


# ──────────────────────────────────────────────────────────────────────
# § 7.1 — Delegate-mode audit stamping (observed via audit row)
# ──────────────────────────────────────────────────────────────────────


def _require_agent_mock():
    if not hasattr(_adapter, "deploy_with_agent_mock"):
        pytest.skip("adapter does not expose deploy_with_agent_mock")
    pkg = FIXTURES_DIR / "agent_chatbot.termin.pkg"
    if not pkg.exists():
        pytest.skip("agent_chatbot fixture not found")
    return pkg


@pytest.fixture(scope="module")
def delegate_mode_app():
    """Run a delegate-mode agent (agent_chatbot's `reply`) once and
    capture the resulting audit rows."""
    pkg = _require_agent_mock()
    info, results = _adapter.deploy_with_agent_mock(
        pkg, "acts_as_delegate",
        [("content_query", {"content_name": "messages"})],
    )
    session = _adapter.create_session(info)
    yield session, info, results
    if info.cleanup:
        info.cleanup()


class TestDelegateModeStamping:
    """Per compute-contract.md §7.1 — for delegate-mode invocations,
    the audit's invoked_by_principal_id reflects the principal that
    triggered the compute (here: the user who created the message).

    Anonymous principals get a synthesized ``anonymous:<short>`` id
    rather than an empty string — anonymous is a *type*, not a
    null. Every audit row carries an identifiable principal value so
    operators can filter ``invoked_by_principal_id LIKE 'anonymous:%'``
    to find anonymous-caller activity. v0.9.1 reference runtime
    implements this synthesis in ``write_audit_trace``.
    """

    def test_audit_principal_columns_present(self, delegate_mode_app):
        session, _info, _results = delegate_mode_app
        session.set_role("anonymous", user_name="DelegateTester")
        r = session.post("/api/v1/messages",
                         json={"role": "user", "body": "trigger delegate"})
        assert r.status_code == 201
        time.sleep(_WAIT)

        ra = session.get("/api/v1/compute_audit_log_reply")
        if ra.status_code == 403:
            pytest.skip("audit content not visible to the test role")
        assert ra.status_code == 200, ra.text
        rows = ra.json()
        assert rows, "expected at least one audit row after triggering reply"
        row = rows[-1]
        # Both columns are present.
        assert "invoked_by_principal_id" in row
        assert "on_behalf_of_principal_id" in row
        # Per spec §7.1: on_behalf_of is the *chain target*. For a
        # principal acting as themselves (delegate-mode human or
        # anonymous, no agent in the chain), on_behalf_of MUST
        # NOT name a different principal than invoked_by — it is
        # either empty (no chain) or equal to invoked_by (mirror,
        # an alternate spelling of no-chain). Either form is
        # conformant; what matters is the absence of an
        # X-acting-for-Y divergence.
        invoked_by = row.get("invoked_by_principal_id", "")
        on_behalf_of = row.get("on_behalf_of_principal_id", "")
        assert on_behalf_of in ("", invoked_by), (
            f"delegate mode (no agent chain): on_behalf_of must be "
            f"empty or mirror invoked_by; got "
            f"invoked_by={invoked_by!r}, on_behalf_of={on_behalf_of!r}"
        )

    def test_anonymous_principal_synthesizes_typed_id(self, delegate_mode_app):
        """v0.9.1: when the upstream caller is anonymous (or there is
        no authenticated subject), the audit row's
        invoked_by_principal_id MUST be a synthesized
        ``anonymous:<short>`` value rather than an empty string.

        Operators rely on the prefix to filter audit logs for
        anonymous-caller activity; the suffix gives uniqueness within
        the audit trail so anonymous rows don't collide on a single
        opaque value."""
        session, _info, _results = delegate_mode_app
        session.set_role("anonymous", user_name="AnonAuditTester")
        r = session.post("/api/v1/messages",
                         json={"role": "user", "body": "anonymous synth check"})
        assert r.status_code == 201
        time.sleep(_WAIT)

        ra = session.get("/api/v1/compute_audit_log_reply")
        if ra.status_code == 403:
            pytest.skip("audit content not visible to the test role")
        assert ra.status_code == 200, ra.text
        rows = ra.json()
        assert rows, "expected at least one audit row"
        row = rows[-1]
        invoked_by = row.get("invoked_by_principal_id", "")
        # Either a real authenticated id (some adapter setups) OR
        # the synthesized anonymous form. Empty string is no longer
        # conformant in v0.9.1.
        assert invoked_by, (
            "invoked_by_principal_id is empty — anonymous principals "
            "must synthesize a typed id per §7.1"
        )
        if invoked_by.startswith("anonymous:"):
            # Anonymous form: prefix + non-empty suffix.
            suffix = invoked_by.split(":", 1)[1]
            assert suffix and suffix != "anonymous", (
                f"anonymous prefix must carry a non-empty suffix; "
                f"got {invoked_by!r}"
            )
