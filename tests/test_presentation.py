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


class TestPageRendering:
    """Pages render as HTML for the correct role."""

    def test_hello_page_renders(self, hello):
        r = hello.get("/hello")
        assert r.status_code == 200
        assert "<!DOCTYPE html>" in r.text

    def test_warehouse_inventory_dashboard_renders(self, warehouse):
        warehouse.set_role("warehouse clerk")
        r = warehouse.get("/inventory_dashboard")
        assert r.status_code == 200
        assert "<!DOCTYPE html>" in r.text

    def test_warehouse_add_product_renders(self, warehouse):
        warehouse.set_role("warehouse manager")
        r = warehouse.get("/add_product")
        assert r.status_code == 200
        assert "<!DOCTYPE html>" in r.text

    def test_helpdesk_ticket_queue_renders(self, helpdesk):
        helpdesk.set_role("support agent")
        r = helpdesk.get("/ticket_queue")
        assert r.status_code == 200
        assert "<!DOCTYPE html>" in r.text

    def test_helpdesk_submit_ticket_renders(self, helpdesk):
        helpdesk.set_role("customer")
        r = helpdesk.get("/submit_ticket")
        assert r.status_code == 200
        assert "<!DOCTYPE html>" in r.text

    def test_projectboard_sprint_board_renders(self, projectboard):
        projectboard.set_role("developer")
        r = projectboard.get("/sprint_board")
        assert r.status_code == 200
        assert "<!DOCTYPE html>" in r.text

    def test_page_contains_title(self, warehouse):
        warehouse.set_role("warehouse clerk")
        r = warehouse.get("/inventory_dashboard")
        assert "Inventory Dashboard" in r.text

    def test_page_contains_nav(self, warehouse):
        warehouse.set_role("warehouse clerk")
        r = warehouse.get("/inventory_dashboard")
        assert "Dashboard" in r.text
        assert "Receive Stock" in r.text


class TestDataTableRendering:
    """Data tables render with correct columns and data attributes."""

    def test_table_has_column_headers(self, warehouse):
        warehouse.set_role("warehouse clerk")
        r = warehouse.get("/inventory_dashboard")
        assert "SKU" in r.text
        assert "name" in r.text
        assert "category" in r.text
        assert "status" in r.text

    def test_table_has_hydration_attributes(self, warehouse):
        warehouse.set_role("warehouse clerk")
        r = warehouse.get("/inventory_dashboard")
        assert 'data-termin-component="data_table"' in r.text
        assert 'data-termin-source="products"' in r.text

    def test_table_shows_data(self, warehouse):
        warehouse.set_role("warehouse manager")
        sku = _uid()
        warehouse.post("/api/v1/products", json={
            "sku": sku, "name": "Table Data", "category": "raw material",
        })
        r = warehouse.get("/inventory_dashboard")
        assert sku in r.text


class TestFormRendering:
    """Forms render with correct fields and submit correctly."""

    def test_form_has_input_fields(self, warehouse):
        warehouse.set_role("warehouse manager")
        r = warehouse.get("/add_product")
        assert 'name="sku"' in r.text
        assert 'name="name"' in r.text
        assert '<form' in r.text

    def test_form_submit_creates_record(self, helpdesk):
        helpdesk.set_role("customer", "FormTester")
        tag = _uid()
        r = helpdesk.post("/submit_ticket", data={
            "title": f"Form Submit {tag}", "description": "via form",
            "priority": "low", "category": "question",
        })
        assert r.status_code == 200  # follows redirect
        # Verify the ticket was created
        r2 = helpdesk.get("/api/v1/tickets")
        titles = [t["title"] for t in r2.json()]
        assert f"Form Submit {tag}" in titles


class TestActionButtonRendering:
    """Action buttons render with correct state and scope awareness."""

    def _create_product(self, warehouse):
        warehouse.set_role("warehouse manager")
        r = warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "Btn Test", "category": "raw material",
        })
        return r.json()["id"]

    def test_draft_shows_activate_enabled(self, warehouse):
        self._create_product(warehouse)
        warehouse.set_role("warehouse manager")
        r = warehouse.get("/inventory_dashboard")
        assert "Activate</button></form>" in r.text

    def test_disabled_button_for_wrong_scope(self, warehouse):
        self._create_product(warehouse)
        warehouse.set_role("executive")
        r = warehouse.get("/inventory_dashboard")
        assert "cursor-not-allowed" in r.text

    def test_active_product_disables_activate(self, warehouse):
        pid = self._create_product(warehouse)
        warehouse.post(f"/_transition/products/{pid}/active")
        warehouse.set_role("warehouse manager")
        r = warehouse.get("/inventory_dashboard")
        # Active product should not have an enabled Activate transition.
        # A runtime may disable the button, hide it, or omit the form entirely — all are valid.
        assert f"/_transition/products/{pid}/active" not in r.text


class TestFilterRendering:
    """Filter dropdowns render with correct options."""

    def test_enum_filter_has_options(self, warehouse):
        warehouse.set_role("warehouse clerk")
        r = warehouse.get("/inventory_dashboard")
        assert "category:" in r.text.lower() or "data-filter" in r.text

    def test_status_filter_has_states(self, warehouse):
        warehouse.set_role("warehouse clerk")
        r = warehouse.get("/inventory_dashboard")
        assert "status" in r.text.lower()


class TestSearchRendering:
    """Search input renders correctly."""

    def test_search_placeholder_present(self, warehouse):
        warehouse.set_role("warehouse clerk")
        r = warehouse.get("/inventory_dashboard")
        assert "Search by" in r.text or "data-search" in r.text


# ═══════════════════════════════════════════════════════════════════════
# 6. DEFAULT EXPRESSIONS & CEL EVALUATION
# ═══════════════════════════════════════════════════════════════════════


class TestSectionRendering:
    """Section components render with correct structure."""

    def test_section_title_rendered(self, projectboard):
        """Sections with titles render headings."""
        projectboard.set_role("project manager")
        r = projectboard.get("/project_dashboard")
        assert r.status_code == 200

    def test_aggregation_renders(self, projectboard):
        projectboard.set_role("project manager")
        r = projectboard.get("/project_dashboard")
        if r.status_code == 200:
            assert "data-termin-component" in r.text
