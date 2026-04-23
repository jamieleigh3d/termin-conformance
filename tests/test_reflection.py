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


class TestReflectionEndpoints:
    """Reflection endpoints expose application metadata."""

    def test_reflect_root(self, warehouse):
        r = warehouse.get("/api/reflect")
        assert r.status_code == 200
        data = r.json()
        assert data["ir_version"] == "0.9.0"
        assert data["name"] == "Warehouse Inventory Manager"

    def test_reflect_content(self, warehouse):
        r = warehouse.get("/api/reflect/content")
        assert r.status_code == 200
        data = r.json()
        # Reflection returns content schemas -- check 'products' appears
        text = json.dumps(data)
        assert "products" in text
        assert "stock" in text  # stock_levels or stock levels

    def test_reflect_compute(self, compute_demo):
        r = compute_demo.get("/api/reflect/compute")
        assert r.status_code == 200

    def test_errors_endpoint(self, warehouse):
        r = warehouse.get("/api/errors")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestRuntimeBootstrap:
    """Runtime bootstrap endpoints for client initialization."""

    def test_registry_endpoint(self, warehouse):
        r = warehouse.get("/runtime/registry")
        assert r.status_code == 200

    def test_bootstrap_endpoint(self, warehouse):
        r = warehouse.get("/runtime/bootstrap")
        assert r.status_code == 200
        data = r.json()
        assert "identity" in data
        # Bootstrap returns content_names (list of snake names)
        assert "content_names" in data or "content" in data

    def test_termin_js_served(self, warehouse):
        r = warehouse.get("/runtime/termin.js")
        assert r.status_code == 200
        assert "TERMIN_VERSION" in r.text

    def test_set_role_endpoint(self, warehouse):
        r = warehouse.post("/set-role", data={"role": "executive"})
        assert r.status_code == 200  # follows redirect


# ═══════════════════════════════════════════════════════════════════════
# 12. ADDITIONAL PARAMETRIZED COVERAGE
# ═══════════════════════════════════════════════════════════════════════
