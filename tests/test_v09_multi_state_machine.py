"""Conformance — v0.9: multi-state machine per content.

A content type may declare multiple state machines, each as an inline
state-typed field. Each state machine is independent: its own column,
its own transition table, its own scope gates, its own audit trail.

Concrete contract every conforming runtime must satisfy:

  1. **Schema**: One column per state machine, named after the field
     (snake_case). The legacy implicit `status` column does not exist.
     Each column has the machine's initial state as its SQL default.

  2. **Independence**: Transitioning machine A does not change the value
     of machine B's column on the same record.

  3. **Scope isolation**: A scope that gates transitions on machine A
     does not authorize transitions on machine B (unless explicitly
     declared).

  4. **Route shape**: The transition endpoint is
     `POST /_transition/{content}/{machine_name}/{record_id}/{target_state}`.
     The legacy single-SM shape `POST /_transition/{content}/{id}/{state}`
     is no longer accepted (404).

  5. **Response shape**: The successful transition response key is the
     machine's column name (e.g. `"lifecycle"`), not the legacy `"status"`.

  6. **Self-transitions**: `(state_X, state_X)` may be declared. When
     fired, the event still publishes; the state value stays the same.

  7. **Edit modal**: Renders one `<select>` per state machine on the
     content, each filtered to the transitions valid from the current
     state for the current user's scopes.

The fixture for these tests is `approval_workflow`, a documents content
with two state machines:

  * `lifecycle`        — draft → published → archived
  * `approval status`  — pending ⇄ rejected (via revision); pending → approved

Roles in the fixture:

  * Editor   — docs.edit
  * Approver — docs.approve
  * Admin    — docs.edit + docs.approve + docs.admin

Test ID convention: each class declares one or more tests prefixed with
`v09_sm_NN_` matching the design doc Appendix B tracking IDs. Use
`pytest tests/test_v09_multi_state_machine.py -k v09_sm_06` to run a
specific contract.
"""

import uuid
import pytest


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────

def _title(prefix="DOC"):
    return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"


@pytest.fixture
def fresh_document(approval_workflow):
    """Create a fresh document as the editor and return its id.
    Both state columns are at their declared initial values:
      lifecycle == "draft", approval_status == "pending"
    """
    approval_workflow.set_role("editor")
    r = approval_workflow.post("/api/v1/documents", json={
        "title": _title(),
        "body": "conformance fixture body",
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ─────────────────────────────────────────────────────────────────────
# Schema (v09_sm_01..03)
# ─────────────────────────────────────────────────────────────────────

class TestSchema:
    """The compiled schema must reflect both state machines as
    independent columns. The legacy `status` column must not exist."""

    def test_v09_sm_01_no_legacy_status_column(self, approval_workflow,
                                               fresh_document):
        """v09_sm_01: GET on a document must NOT include a `status` key."""
        approval_workflow.set_role("editor")
        r = approval_workflow.get(f"/api/v1/documents/{fresh_document}")
        assert r.status_code == 200
        body = r.json()
        assert "status" not in body, (
            f"document response has legacy 'status' key: {body}")

    def test_v09_sm_02_lifecycle_initial_default(self, approval_workflow,
                                                 fresh_document):
        """v09_sm_02: New document has lifecycle == 'draft'."""
        approval_workflow.set_role("editor")
        r = approval_workflow.get(f"/api/v1/documents/{fresh_document}")
        assert r.json()["lifecycle"] == "draft"

    def test_v09_sm_03_approval_initial_default(self, approval_workflow,
                                                fresh_document):
        """v09_sm_03: New document has approval_status == 'pending'."""
        approval_workflow.set_role("editor")
        r = approval_workflow.get(f"/api/v1/documents/{fresh_document}")
        assert r.json()["approval_status"] == "pending"


# ─────────────────────────────────────────────────────────────────────
# Independence (v09_sm_04..05)
# ─────────────────────────────────────────────────────────────────────

class TestMachineIndependence:
    """Transitions on one machine must not affect the other."""

    def test_v09_sm_04_lifecycle_does_not_touch_approval(
            self, approval_workflow, fresh_document):
        """v09_sm_04: Advancing lifecycle leaves approval_status unchanged."""
        approval_workflow.set_role("editor")
        r = approval_workflow.post(
            f"/_transition/documents/lifecycle/{fresh_document}/published")
        assert r.status_code == 200, r.text

        approval_workflow.set_role("admin")
        r2 = approval_workflow.get(f"/api/v1/documents/{fresh_document}")
        body = r2.json()
        assert body["lifecycle"] == "published"
        assert body["approval_status"] == "pending"  # unchanged

    def test_v09_sm_05_approval_does_not_touch_lifecycle(
            self, approval_workflow, fresh_document):
        """v09_sm_05: Advancing approval_status leaves lifecycle unchanged."""
        approval_workflow.set_role("approver")
        r = approval_workflow.post(
            f"/_transition/documents/approval_status/{fresh_document}/approved")
        assert r.status_code == 200, r.text

        approval_workflow.set_role("admin")
        r2 = approval_workflow.get(f"/api/v1/documents/{fresh_document}")
        body = r2.json()
        assert body["approval_status"] == "approved"
        assert body["lifecycle"] == "draft"  # unchanged


# ─────────────────────────────────────────────────────────────────────
# Scope isolation (v09_sm_06..07)
# ─────────────────────────────────────────────────────────────────────

class TestScopeIsolation:
    """A scope that gates one machine must not authorize transitions on
    another machine. Each machine's transitions enforce only their own
    declared scopes."""

    def test_v09_sm_06_edit_scope_cannot_drive_approval(
            self, approval_workflow, fresh_document):
        """v09_sm_06: Editor (docs.edit only) cannot transition
        approval_status. Required scope is docs.approve."""
        approval_workflow.set_role("editor")
        r = approval_workflow.post(
            f"/_transition/documents/approval_status/{fresh_document}/approved")
        assert r.status_code == 403, r.text

        approval_workflow.set_role("admin")
        r2 = approval_workflow.get(f"/api/v1/documents/{fresh_document}")
        assert r2.json()["approval_status"] == "pending"

    def test_v09_sm_07_approve_scope_cannot_drive_lifecycle(
            self, approval_workflow, fresh_document):
        """v09_sm_07: Approver (docs.approve only) cannot transition
        lifecycle. Required scope for draft→published is docs.edit."""
        approval_workflow.set_role("approver")
        r = approval_workflow.post(
            f"/_transition/documents/lifecycle/{fresh_document}/published")
        assert r.status_code == 403, r.text

        approval_workflow.set_role("admin")
        r2 = approval_workflow.get(f"/api/v1/documents/{fresh_document}")
        assert r2.json()["lifecycle"] == "draft"


# ─────────────────────────────────────────────────────────────────────
# Transition validity (v09_sm_08)
# ─────────────────────────────────────────────────────────────────────

class TestTransitionValidity:
    """Undeclared transitions on each machine must return 409
    independently. Validity is per-machine."""

    def test_v09_sm_08a_lifecycle_invalid_transition(
            self, approval_workflow, fresh_document):
        """v09_sm_08a: draft→archived is undeclared on lifecycle.
        Must 409 even with a privileged scope."""
        approval_workflow.set_role("admin")
        r = approval_workflow.post(
            f"/_transition/documents/lifecycle/{fresh_document}/archived")
        assert r.status_code == 409, r.text

    def test_v09_sm_08b_approval_invalid_transition(
            self, approval_workflow, fresh_document):
        """v09_sm_08b: approved→pending is undeclared on approval_status.
        Must 409."""
        approval_workflow.set_role("approver")
        approval_workflow.post(
            f"/_transition/documents/approval_status/{fresh_document}/approved")
        approval_workflow.set_role("admin")
        r = approval_workflow.post(
            f"/_transition/documents/approval_status/{fresh_document}/pending")
        assert r.status_code == 409, r.text


# ─────────────────────────────────────────────────────────────────────
# Route shape (v09_sm_09..10)
# ─────────────────────────────────────────────────────────────────────

class TestRouteShape:
    """The new route includes the machine name. The legacy single-SM
    route is no longer mounted."""

    def test_v09_sm_09_new_route_succeeds(self, approval_workflow,
                                          fresh_document):
        """v09_sm_09: POST to the four-segment route succeeds."""
        approval_workflow.set_role("editor")
        r = approval_workflow.post(
            f"/_transition/documents/lifecycle/{fresh_document}/published")
        assert r.status_code == 200, r.text

    def test_v09_sm_10_legacy_route_returns_404(self, approval_workflow,
                                                fresh_document):
        """v09_sm_10: POST to the legacy three-segment route returns 404
        (the route is not registered, not 405 method-not-allowed)."""
        approval_workflow.set_role("editor")
        r = approval_workflow.post(
            f"/_transition/documents/{fresh_document}/published")
        assert r.status_code == 404, r.text


# ─────────────────────────────────────────────────────────────────────
# Response shape (v09_sm_11)
# ─────────────────────────────────────────────────────────────────────

class TestResponseShape:
    """AJAX-shape responses must use the machine's column name as the
    state key, not the legacy 'status'."""

    def test_v09_sm_11_ajax_response_key_is_machine_name(
            self, approval_workflow, fresh_document):
        """v09_sm_11: AJAX response carries `lifecycle`, not `status`."""
        approval_workflow.set_role("editor")
        r = approval_workflow.post(
            f"/_transition/documents/lifecycle/{fresh_document}/published",
            headers={"X-Requested-With": "XMLHttpRequest"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "lifecycle" in body, f"AJAX response missing 'lifecycle': {body}"
        assert body["lifecycle"] == "published"
        assert "status" not in body, (
            f"AJAX response has legacy 'status' key: {body}")


# ─────────────────────────────────────────────────────────────────────
# WebSocket push (v09_sm_12)
# ─────────────────────────────────────────────────────────────────────

class TestWebSocketPush:
    """The `content.{table}.updated` push must include all state
    columns on the record, not just the one being transitioned."""

    def test_v09_sm_12_websocket_push_carries_both_state_columns(
            self, approval_workflow, fresh_document):
        """v09_sm_12: After a lifecycle transition, the WS event payload
        contains both `lifecycle` (new value) and `approval_status`
        (unchanged value).

        Implementation note: the WS subscriber API on TerminSession is
        adapter-provided. If the adapter does not expose WS, this test
        skips. This is intentional — the WS contract is in scope but
        the adapter may not surface it in all environments.
        """
        if not hasattr(approval_workflow, "subscribe"):
            pytest.skip("adapter does not expose WS subscription")

        with approval_workflow.subscribe(
                f"content.documents.updated") as sub:
            approval_workflow.set_role("editor")
            r = approval_workflow.post(
                f"/_transition/documents/lifecycle/{fresh_document}/published")
            assert r.status_code == 200, r.text

            event = sub.get(timeout=2.0)
            data = event.get("data", {})
            assert data.get("lifecycle") == "published"
            assert data.get("approval_status") == "pending"


# ─────────────────────────────────────────────────────────────────────
# Edit modal — browser only (v09_sm_13)
# ─────────────────────────────────────────────────────────────────────

class TestEditModal:
    """The edit modal must render one <select> per state machine on the
    content. This is a browser-only test — see CLAUDE.md note on
    Tier 2 selector discipline (data-termin-* only, never English text).
    """

    @pytest.mark.browser
    def test_v09_sm_13_edit_modal_has_two_state_selects(
            self, approval_workflow, fresh_document, browser_page):
        """v09_sm_13: The edit modal exposes one <select> per machine.
        Each is identified by its data-termin-field marker."""
        from conftest import _require_served_url
        _require_served_url(approval_workflow)

        approval_workflow.set_role("admin")
        page = browser_page
        page.goto(approval_workflow.base_url + "/documents")
        page.click(f'[data-termin-row-id="{fresh_document}"] '
                   f'[data-termin-edit]')
        page.wait_for_selector('[data-termin-edit-modal]')

        lifecycle_select = page.query_selector(
            '[data-termin-edit-modal] select[data-termin-field="lifecycle"]')
        approval_select = page.query_selector(
            '[data-termin-edit-modal] '
            'select[data-termin-field="approval_status"]')

        assert lifecycle_select is not None, (
            "edit modal missing lifecycle <select>")
        assert approval_select is not None, (
            "edit modal missing approval_status <select>")


# ─────────────────────────────────────────────────────────────────────
# Self-transitions (v09_sm_14)
# ─────────────────────────────────────────────────────────────────────

class TestSelfTransition:
    """A declared self-transition (state_X → state_X) must succeed,
    leave the column value unchanged, and still publish the WS event.

    Note: the approval_workflow fixture does not currently include a
    self-transition. This test depends on a self-transition being
    added during fixture authoring. If the fixture exposes none, the
    test skips cleanly with a message — fix the fixture, don't suppress
    the test.
    """

    def test_v09_sm_14_self_transition_succeeds(self, approval_workflow,
                                                approval_workflow_ir,
                                                fresh_document):
        """v09_sm_14: A declared self-transition leaves state unchanged
        and returns 200."""
        # Discover a self-transition from the IR. Skip if none exists
        # so the test is honest about its dependency on the fixture.
        self_transition = None
        for sm in approval_workflow_ir.get("state_machines", []):
            for t in sm.get("transitions", []):
                if t["from_state"] == t["to_state"]:
                    self_transition = (
                        sm["machine_name"], t["from_state"],
                        t.get("required_scope", ""))
                    break
            if self_transition:
                break

        if self_transition is None:
            pytest.skip(
                "approval_workflow fixture has no self-transition declared")

        machine, state, scope = self_transition
        # Pick a role with the required scope. Admin always qualifies.
        approval_workflow.set_role("admin")

        # Position the record in the from-state if it isn't already.
        # (For a draft→draft self-transition on lifecycle, no setup needed.)
        # General case: this test assumes the initial state is the from-state
        # of the self-transition. If not, the fixture should expose one that
        # is — keep this simple.
        machine_col = machine.replace(" ", "_")
        approval_workflow.set_role("admin")
        r0 = approval_workflow.get(f"/api/v1/documents/{fresh_document}")
        if r0.json().get(machine_col) != state:
            pytest.skip(
                f"fresh document is not in from-state '{state}' of the "
                f"self-transition on '{machine}'; fixture authoring detail")

        r = approval_workflow.post(
            f"/_transition/documents/{machine_col}/{fresh_document}/{state}")
        assert r.status_code == 200, r.text

        r2 = approval_workflow.get(f"/api/v1/documents/{fresh_document}")
        assert r2.json()[machine_col] == state  # unchanged
