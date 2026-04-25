"""Termin Runtime Conformance Test Suite.

A comprehensive test suite that validates any conforming Termin runtime
against the behavioral contracts defined in the IR specification and
Runtime Implementer's Guide.

These tests are designed to be portable: they test observable behavior
through the HTTP API and rendered HTML, not internal implementation
details. Any runtime that passes this suite is behaviorally conformant.

v0.9 update: state columns are named after the state-typed field on the
Content, not the legacy implicit `status`. Warehouse `products` now has
`product_lifecycle`; helpdesk `tickets` has `ticket_lifecycle`. The
transition route is `/_transition/{content}/{machine_name}/{id}/{state}`.

Test categories:
  1. Identity & Access Control (40+ tests)
  2. State Machine Enforcement (30+ tests)
  3. Field Validation & Constraints (30+ tests)
  4. CRUD Operations & API Routes (25+ tests)
  5. Presentation & Component Rendering (25+ tests)
  6. Default Expressions & CEL Evaluation (20+ tests)
  7. Data Isolation & Cross-Content Safety (20+ tests)
  8. Event Processing (10+ tests)
  9. Navigation & Role Visibility (10+ tests)
  10. Error Handling & Edge Cases (15+ tests)

Authors: Jamie-Leigh Blake & Claude Anthropic
"""

import json
import uuid
import pytest
from pathlib import Path


def _uid():
    return uuid.uuid4().hex[:8]


# v0.9: state column names are the snake_case field names declared on the
# Content, not the legacy implicit `status`.
WAREHOUSE_SM = "product_lifecycle"
HELPDESK_SM = "ticket_lifecycle"


# ═══════════════════════════════════════════════════════════════════════
# 1. IDENTITY & ACCESS CONTROL
# ═══════════════════════════════════════════════════════════════════════


class TestStateMachineInitialState:
    """New records must be created with the correct initial state."""

    def test_product_starts_as_draft(self, warehouse):
        warehouse.set_role("warehouse manager")
        r = warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "Init Test", "category": "raw material",
        })
        assert r.status_code == 201
        assert r.json()[WAREHOUSE_SM] == "draft"

    def test_ticket_starts_as_open(self, helpdesk):
        helpdesk.set_role("customer")
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"Init {_uid()}", "description": "test",
        })
        assert r.status_code == 201
        assert r.json()[HELPDESK_SM] == "open"

    def test_cannot_set_initial_status_directly(self, warehouse):
        """Clients should not be able to override the initial state.

        v0.9 contract: the SQL DEFAULT on the state column is the initial
        state. A POST body carrying the state column with a different
        value must not take effect — the runtime must either strip the
        field on create or reject the request. Either is conformant.
        """
        warehouse.set_role("warehouse manager")
        r = warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "Override Test",
            "category": "raw material", WAREHOUSE_SM: "active",
        })
        assert r.status_code == 201
        # State should be "draft" regardless of what client sent
        assert r.json()[WAREHOUSE_SM] == "draft"


class TestStateMachineValidTransitions:
    """Only declared transitions are allowed."""

    def _create_product(self, warehouse):
        sku = _uid()
        warehouse.set_role("warehouse manager")
        r = warehouse.post("/api/v1/products", json={
            "sku": sku, "name": f"SM Test {sku}", "category": "raw material",
        })
        return r.json()["id"], sku

    def test_valid_transition_succeeds(self, warehouse):
        pid, _ = self._create_product(warehouse)
        r = warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/active")
        assert r.status_code in (200, 303)

    def test_invalid_transition_rejected_409(self, warehouse):
        """Transition not in the state machine -> 409."""
        pid, _ = self._create_product(warehouse)
        # draft -> discontinued is not declared
        r = warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/discontinued")
        assert r.status_code == 409

    def test_transition_from_wrong_state(self, warehouse):
        """Can't transition active -> draft (no such transition)."""
        pid, _ = self._create_product(warehouse)
        warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/active")  # draft -> active
        r = warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/draft")  # active -> draft: invalid
        assert r.status_code == 409

    def test_full_lifecycle(self, warehouse):
        """draft -> active -> discontinued -> active (full cycle)."""
        pid, _ = self._create_product(warehouse)
        r1 = warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/active")
        assert r1.status_code in (200, 303)
        r2 = warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/discontinued")
        assert r2.status_code in (200, 303)
        r3 = warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/active")
        assert r3.status_code in (200, 303)


class TestStateMachineScopeEnforcement:
    """Transitions require the correct scope."""

    def _create_product(self, warehouse):
        warehouse.set_role("warehouse manager")
        r = warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "Scope Test", "category": "raw material",
        })
        return r.json()["id"]

    def test_transition_with_sufficient_scope(self, warehouse):
        pid = self._create_product(warehouse)
        warehouse.set_role("warehouse clerk")  # has write inventory
        r = warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/active")
        assert r.status_code in (200, 303)

    def test_transition_without_scope_is_403(self, warehouse):
        pid = self._create_product(warehouse)
        warehouse.set_role("executive")  # only read inventory
        r = warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/active")
        assert r.status_code == 403

    def test_admin_transition_requires_admin_scope(self, warehouse):
        """active -> discontinued requires admin inventory."""
        pid = self._create_product(warehouse)
        warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/active")  # clerk can do this
        warehouse.set_role("warehouse clerk")
        r = warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/discontinued")
        assert r.status_code == 403  # clerk lacks admin inventory
        warehouse.set_role("warehouse manager")
        r2 = warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/discontinued")
        assert r2.status_code in (200, 303)  # manager has admin inventory

    @pytest.mark.parametrize("role,from_state,to_state,expected", [
        ("warehouse clerk", "draft", "active", 200),
        ("warehouse manager", "draft", "active", 200),
        ("executive", "draft", "active", 403),
        ("warehouse clerk", "active", "discontinued", 403),
        ("warehouse manager", "active", "discontinued", 200),
        ("executive", "active", "discontinued", 403),
        ("warehouse manager", "discontinued", "active", 200),
        ("warehouse clerk", "discontinued", "active", 403),
    ])
    def test_transition_scope_matrix(self, warehouse, role, from_state, to_state, expected):
        """Parametrized: every role x transition combination."""
        pid = self._create_product(warehouse)
        # Walk to from_state
        if from_state == "active":
            warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/active")
        elif from_state == "discontinued":
            warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/active")
            warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/discontinued")
        warehouse.set_role(role)
        r = warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/{to_state}")
        actual = r.status_code
        # Accept both 200 and 303 (redirect) as success
        if expected == 200:
            assert actual in (200, 303), f"{role}: {from_state}->{to_state} expected success, got {actual}"
        else:
            assert actual == expected, f"{role}: {from_state}->{to_state} expected {expected}, got {actual}"


class TestStateMachineHelpdesk:
    """Helpdesk ticket lifecycle with multi-word states."""

    def _create_ticket(self, helpdesk, role="support agent"):
        helpdesk.set_role(role)
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"SM Test {_uid()}", "description": "test",
        })
        return r.json()["id"]

    def test_multi_word_state_transition(self, helpdesk):
        """open -> in progress (multi-word target state)."""
        tid = self._create_ticket(helpdesk)
        r = helpdesk.post(f"/_transition/tickets/{HELPDESK_SM}/{tid}/in progress")
        assert r.status_code in (200, 303)

    def test_full_ticket_lifecycle(self, helpdesk):
        """open -> in progress -> resolved -> closed."""
        tid = self._create_ticket(helpdesk)
        helpdesk.set_role("support agent")
        helpdesk.post(f"/_transition/tickets/{HELPDESK_SM}/{tid}/in progress")
        helpdesk.post(f"/_transition/tickets/{HELPDESK_SM}/{tid}/resolved")
        helpdesk.set_role("support manager")
        r = helpdesk.post(f"/_transition/tickets/{HELPDESK_SM}/{tid}/closed")
        assert r.status_code in (200, 303)

    def test_customer_can_reopen(self, helpdesk):
        """resolved -> in progress requires create tickets (customer has this)."""
        tid = self._create_ticket(helpdesk)
        helpdesk.set_role("support agent")
        helpdesk.post(f"/_transition/tickets/{HELPDESK_SM}/{tid}/in progress")
        helpdesk.post(f"/_transition/tickets/{HELPDESK_SM}/{tid}/resolved")
        helpdesk.set_role("customer")
        r = helpdesk.post(f"/_transition/tickets/{HELPDESK_SM}/{tid}/in progress")
        assert r.status_code in (200, 303)

    def test_customer_cannot_resolve(self, helpdesk):
        """in progress -> resolved requires manage tickets (customer lacks it)."""
        tid = self._create_ticket(helpdesk)
        helpdesk.set_role("support agent")
        helpdesk.post(f"/_transition/tickets/{HELPDESK_SM}/{tid}/in progress")
        helpdesk.set_role("customer")
        r = helpdesk.post(f"/_transition/tickets/{HELPDESK_SM}/{tid}/resolved")
        assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════════
# 3. FIELD VALIDATION & CONSTRAINTS
# ═══════════════════════════════════════════════════════════════════════


class TestHelpdeskTransitionMatrix:
    """Exhaustive role x transition matrix for helpdesk tickets."""

    def _create_ticket_in_state(self, helpdesk, target_state):
        """Create a ticket and walk it to the target state."""
        helpdesk.set_role("support manager")
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"Trans {_uid()}", "description": "t",
        })
        tid = r.json()["id"]
        # Walk to target state
        path_to = {
            "open": [],
            "in progress": ["in progress"],
            "waiting on customer": ["in progress", "waiting on customer"],
            "resolved": ["in progress", "resolved"],
            "closed": ["in progress", "resolved", "closed"],
        }
        for state in path_to.get(target_state, []):
            helpdesk.post(f"/_transition/tickets/{HELPDESK_SM}/{tid}/{state}")
        return tid

    @pytest.mark.parametrize("from_state,to_state,role,expected", [
        # open -> in progress: manage tickets
        ("open", "in progress", "support agent", 200),
        ("open", "in progress", "customer", 403),
        # in progress -> waiting: manage tickets
        ("in progress", "waiting on customer", "support agent", 200),
        ("in progress", "waiting on customer", "customer", 403),
        # waiting -> in progress: create tickets
        ("waiting on customer", "in progress", "customer", 200),
        ("waiting on customer", "in progress", "support agent", 200),
        # in progress -> resolved: manage tickets
        ("in progress", "resolved", "support agent", 200),
        ("in progress", "resolved", "customer", 403),
        # resolved -> closed: admin tickets
        ("resolved", "closed", "support manager", 200),
        ("resolved", "closed", "support agent", 403),
        ("resolved", "closed", "customer", 403),
        # resolved -> in progress: create tickets (reopen)
        ("resolved", "in progress", "customer", 200),
        ("resolved", "in progress", "support agent", 200),
        # Invalid transitions
        ("open", "resolved", "support manager", 409),
        ("open", "closed", "support manager", 409),
        ("closed", "open", "support manager", 409),
    ])
    def test_helpdesk_transition_matrix(self, helpdesk, from_state, to_state, role, expected):
        tid = self._create_ticket_in_state(helpdesk, from_state)
        helpdesk.set_role(role)
        r = helpdesk.post(f"/_transition/tickets/{HELPDESK_SM}/{tid}/{to_state}")
        actual = r.status_code
        if expected == 200:
            assert actual in (200, 303), \
                f"{from_state}->{to_state} as {role}: expected success, got {actual}"
        else:
            assert actual == expected, \
                f"{from_state}->{to_state} as {role}: expected {expected}, got {actual}"


class TestStateMachineStatusPersistence:
    """State changes persist across requests."""

    def test_status_persists_after_transition(self, warehouse):
        warehouse.set_role("warehouse manager")
        sku = _uid()
        r = warehouse.post("/api/v1/products", json={
            "sku": sku, "name": "Persist", "category": "raw material",
        })
        pid = r.json()["id"]
        warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/active")
        # List all and find our product by SKU
        products = warehouse.get("/api/v1/products").json()
        match = [p for p in products if p["sku"] == sku]
        assert len(match) == 1
        assert match[0][WAREHOUSE_SM] == "active"

    def test_double_transition(self, warehouse):
        """Two consecutive valid transitions both persist."""
        warehouse.set_role("warehouse manager")
        sku = _uid()
        r = warehouse.post("/api/v1/products", json={
            "sku": sku, "name": "Double", "category": "raw material",
        })
        pid = r.json()["id"]
        warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/active")
        warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/discontinued")
        products = warehouse.get("/api/v1/products").json()
        match = [p for p in products if p["sku"] == sku]
        assert match[0][WAREHOUSE_SM] == "discontinued"

    def test_failed_transition_doesnt_change_status(self, warehouse):
        """A rejected transition leaves the state unchanged."""
        warehouse.set_role("warehouse manager")
        sku = _uid()
        r = warehouse.post("/api/v1/products", json={
            "sku": sku, "name": "NoChange", "category": "raw material",
        })
        pid = r.json()["id"]
        # Try invalid transition (draft -> discontinued)
        warehouse.post(f"/_transition/products/{WAREHOUSE_SM}/{pid}/discontinued")
        products = warehouse.get("/api/v1/products").json()
        match = [p for p in products if p["sku"] == sku]
        assert match[0][WAREHOUSE_SM] == "draft"  # unchanged
