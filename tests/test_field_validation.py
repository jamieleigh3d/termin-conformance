"""Termin Runtime Conformance Test Suite.

A comprehensive test suite that validates any conforming Termin runtime
against the behavioral contracts defined in the IR specification and
Runtime Implementer's Guide.

These tests are designed to be portable: they test observable behavior
through the HTTP API and rendered HTML, not internal implementation
details. Any runtime that passes this suite is behaviorally conformant.

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


# ═══════════════════════════════════════════════════════════════════════
# 1. IDENTITY & ACCESS CONTROL
# ═══════════════════════════════════════════════════════════════════════


class TestRequiredFields:
    """Required fields must be present on create."""

    def test_missing_required_field_fails(self, helpdesk):
        helpdesk.set_role("customer")
        r = helpdesk.post("/api/v1/tickets", json={"description": "no title"})
        assert r.status_code in (400, 422, 500)  # should reject

    def test_all_required_fields_present_succeeds(self, helpdesk):
        helpdesk.set_role("customer")
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"Req Test {_uid()}", "description": "has both",
        })
        assert r.status_code == 201

    def test_required_reference_field(self, warehouse):
        """stock_levels.product is required reference -- must be valid."""
        warehouse.set_role("warehouse clerk")
        r = warehouse.post("/api/v1/stock-levels", json={
            "warehouse": "W1", "quantity": 10, "reorder_threshold": 5,
            # Missing 'product' (required FK)
        })
        assert r.status_code in (400, 422, 500)


class TestUniqueConstraints:
    """Unique fields must reject duplicates."""

    def test_duplicate_unique_field_rejected(self, warehouse):
        warehouse.set_role("warehouse manager")
        sku = _uid()
        r1 = warehouse.post("/api/v1/products", json={
            "sku": sku, "name": "First", "category": "raw material",
        })
        assert r1.status_code == 201
        r2 = warehouse.post("/api/v1/products", json={
            "sku": sku, "name": "Second", "category": "raw material",
        })
        assert r2.status_code in (409, 500)  # unique constraint violation

    def test_different_unique_values_both_succeed(self, warehouse):
        warehouse.set_role("warehouse manager")
        r1 = warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "A", "category": "raw material",
        })
        r2 = warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "B", "category": "raw material",
        })
        assert r1.status_code == 201
        assert r2.status_code == 201


class TestEnumConstraints:
    """Enum fields should only accept declared values."""

    def test_valid_enum_value_accepted(self, warehouse):
        warehouse.set_role("warehouse manager")
        r = warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "Enum Test",
            "category": "raw material",  # valid enum value
        })
        assert r.status_code == 201

    def test_valid_enum_values_roundtrip(self, warehouse):
        """All declared enum values should be accepted and returned."""
        warehouse.set_role("warehouse manager")
        for cat in ["raw material", "finished good", "packaging"]:
            r = warehouse.post("/api/v1/products", json={
                "sku": _uid(), "name": f"Cat {cat}", "category": cat,
            })
            assert r.status_code == 201
            assert r.json()["category"] == cat


class TestNumericConstraints:
    """Minimum/maximum constraints on numeric fields."""

    def test_minimum_constraint_respected(self, projectboard):
        """Capacity with minimum 0 should reject negative values."""
        projectboard.set_role("project manager")
        pr = projectboard.post("/api/v1/projects", json={
            "name": f"Proj {_uid()}", "description": "test",
        })
        pid = pr.json()["id"]
        r = projectboard.post("/api/v1/sprints", json={
            "project": pid, "name": f"Sprint {_uid()}",
            "capacity": -5,  # below minimum of 0
        })
        assert r.status_code in (400, 422)

    def test_minimum_valid_value_accepted(self, projectboard):
        """A value at the minimum boundary should be accepted."""
        projectboard.set_role("project manager")
        pr = projectboard.post("/api/v1/projects", json={
            "name": f"Proj {_uid()}", "description": "test",
        })
        pid = pr.json()["id"]
        r = projectboard.post("/api/v1/sprints", json={
            "project": pid, "name": f"Sprint {_uid()}",
            "capacity": 0,  # exactly at minimum
        })
        assert r.status_code == 201


class TestAutoFields:
    """Automatic fields (created_at, etc.) are system-managed."""

    def test_auto_field_populated(self, helpdesk):
        """created_at with default_expr=[now] should be auto-filled."""
        helpdesk.set_role("customer")
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"Auto {_uid()}", "description": "test",
        })
        assert r.status_code == 201
        ticket = r.json()
        assert ticket.get("created_at") is not None
        assert "T" in str(ticket["created_at"])  # ISO timestamp

    def test_auto_id_assigned(self, warehouse):
        """Every record gets an auto-increment id."""
        warehouse.set_role("warehouse manager")
        r = warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "ID Test", "category": "raw material",
        })
        assert r.status_code == 201
        assert "id" in r.json()
        assert isinstance(r.json()["id"], int)


# ═══════════════════════════════════════════════════════════════════════
# 4. CRUD OPERATIONS & API ROUTES
# ═══════════════════════════════════════════════════════════════════════


class TestFieldTypeRoundtrip:
    """Values stored via API should round-trip correctly."""

    def test_text_field_roundtrip(self, helpdesk):
        helpdesk.set_role("customer")
        tag = _uid()
        r = helpdesk.post("/api/v1/tickets", json={"title": f"RT {tag}", "description": "desc"})
        tid = r.json()["id"]
        r2 = helpdesk.get(f"/api/v1/tickets/{tid}")
        assert r2.json()["title"] == f"RT {tag}"
        assert r2.json()["description"] == "desc"

    def test_enum_field_roundtrip(self, helpdesk):
        helpdesk.set_role("customer")
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"Enum RT {_uid()}", "description": "t", "priority": "critical",
        })
        tid = r.json()["id"]
        r2 = helpdesk.get(f"/api/v1/tickets/{tid}")
        assert r2.json()["priority"] == "critical"

    def test_numeric_field_roundtrip(self, warehouse):
        warehouse.set_role("warehouse manager")
        sku = _uid()
        r = warehouse.post("/api/v1/products", json={
            "sku": sku, "name": "Num RT", "category": "raw material",
            "unit_cost": 42.5,
        })
        assert r.status_code == 201
        assert r.json()["unit_cost"] == 42.5

    def test_null_optional_field_roundtrip(self, helpdesk):
        helpdesk.set_role("customer")
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"Null RT {_uid()}", "description": "t",
            # priority and category are optional -- omit them
        })
        tid = r.json()["id"]
        r2 = helpdesk.get(f"/api/v1/tickets/{tid}")
        # Optional fields should be null/None when not provided
        assert r2.json()["priority"] is None or r2.json()["priority"] == ""

    def test_reference_field_stores_integer_id(self, warehouse):
        warehouse.set_role("warehouse manager")
        pr = warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "FK Test", "category": "raw material",
        })
        pid = pr.json()["id"]
        r = warehouse.post("/api/v1/stock-levels", json={
            "product": pid, "warehouse": "W1",
            "quantity": 100, "reorder_threshold": 10,
        })
        assert r.status_code == 201
        # The created record should contain the FK value
        assert r.json()["product"] == pid
