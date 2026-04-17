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


class TestCrossContentIsolation:
    """Operations on one Content must not affect another."""

    def test_create_product_doesnt_affect_stock(self, warehouse):
        warehouse.set_role("warehouse manager")
        before = warehouse.get("/api/v1/stock_levels").json()
        warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "Iso Test", "category": "raw material",
        })
        after = warehouse.get("/api/v1/stock_levels").json()
        assert len(before) == len(after)

    def test_delete_product_doesnt_affect_alerts(self, warehouse):
        warehouse.set_role("warehouse manager")
        r = warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "Iso Del", "category": "raw material",
        })
        pid = r.json()["id"]
        alerts_before = warehouse.get("/api/v1/reorder_alerts").json()
        warehouse.delete(f"/api/v1/products/{pid}")
        alerts_after = warehouse.get("/api/v1/reorder_alerts").json()
        assert len(alerts_before) == len(alerts_after)


class TestCrossAppIsolation:
    """Different apps must not share data."""

    def test_warehouse_and_helpdesk_separate_data(self, warehouse, helpdesk):
        """Products created in warehouse must not appear in helpdesk."""
        warehouse.set_role("warehouse manager")
        warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "Cross App", "category": "raw material",
        })

        helpdesk.set_role("customer")
        r = helpdesk.get("/api/v1/tickets")
        # Tickets list should never contain product data
        for ticket in r.json():
            assert "sku" not in ticket

    def test_separate_app_types_separate_schemas(self, warehouse, helpdesk):
        """Different app types have completely separate Content schemas."""
        warehouse.set_role("warehouse manager")
        r1 = warehouse.get("/api/v1/products")
        if r1.json():
            # Products have 'sku' -- a warehouse-specific field
            assert "sku" in r1.json()[0]

        helpdesk.set_role("customer")
        r2 = helpdesk.get("/api/v1/tickets")
        # Tickets have no 'sku' -- schemas are separate
        for ticket in r2.json():
            assert "sku" not in ticket
            assert "unit_cost" not in ticket


class TestNoMassAssignment:
    """Unknown fields should be ignored or rejected, not stored."""

    def test_extra_fields_not_stored(self, helpdesk):
        """Unknown fields must be rejected (400) or silently ignored, never stored."""
        helpdesk.set_role("customer")
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"Mass {_uid()}", "description": "test",
            "secret_admin_flag": True, "internal_notes": "hacked",
        })
        # Acceptable: 400 (rejected) or 201 (extra fields stripped)
        assert r.status_code in (201, 400)
        if r.status_code == 201:
            ticket = r.json()
            assert "secret_admin_flag" not in ticket
            assert "internal_notes" not in ticket


# ═══════════════════════════════════════════════════════════════════════
# 8. NAVIGATION & ROLE VISIBILITY
# ═══════════════════════════════════════════════════════════════════════
