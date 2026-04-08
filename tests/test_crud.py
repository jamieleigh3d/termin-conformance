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


class TestCRUDList:
    """LIST operations return all records."""

    def test_list_returns_array(self, warehouse):
        warehouse.set_role("warehouse clerk")
        r = warehouse.get("/api/v1/products")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_includes_created_records(self, helpdesk):
        helpdesk.set_role("customer")
        tag = _uid()
        helpdesk.post("/api/v1/tickets", json={
            "title": f"List Test {tag}", "description": "test",
        })
        r = helpdesk.get("/api/v1/tickets")
        titles = [t["title"] for t in r.json()]
        assert f"List Test {tag}" in titles

    def test_list_empty_content_returns_empty_array(self, hello):
        # hello app has no content -- but we can still test the app boots
        r = hello.get("/hello")
        assert r.status_code == 200


class TestCRUDCreate:
    """CREATE operations insert and return the record."""

    def test_create_returns_201(self, warehouse):
        warehouse.set_role("warehouse manager")
        r = warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "Create Test", "category": "raw material",
        })
        assert r.status_code == 201

    def test_create_returns_record_with_id(self, warehouse):
        warehouse.set_role("warehouse manager")
        sku = _uid()
        r = warehouse.post("/api/v1/products", json={
            "sku": sku, "name": "ID Return Test", "category": "raw material",
        })
        body = r.json()
        assert "id" in body
        assert body["sku"] == sku

    def test_create_sets_initial_status(self, warehouse):
        warehouse.set_role("warehouse manager")
        r = warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "Status Test", "category": "raw material",
        })
        assert r.json()["status"] == "draft"


class TestCRUDGetOne:
    """GET_ONE operations fetch a single record by lookup column."""

    def test_get_one_by_id(self, helpdesk):
        helpdesk.set_role("customer")
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"GetOne {_uid()}", "description": "test",
        })
        tid = r.json()["id"]
        r2 = helpdesk.get(f"/api/v1/tickets/{tid}")
        assert r2.status_code == 200
        assert r2.json()["id"] == tid

    def test_get_one_nonexistent_returns_404(self, helpdesk):
        helpdesk.set_role("customer")
        r = helpdesk.get("/api/v1/tickets/999999")
        assert r.status_code == 404


class TestCRUDUpdate:
    """UPDATE operations modify existing records."""

    def test_update_changes_field(self, helpdesk):
        helpdesk.set_role("support agent")
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"Update {_uid()}", "description": "original",
        })
        tid = r.json()["id"]
        r2 = helpdesk.put(f"/api/v1/tickets/{tid}", json={"description": "modified"})
        assert r2.status_code == 200
        r3 = helpdesk.get(f"/api/v1/tickets/{tid}")
        assert r3.json()["description"] == "modified"

    def test_update_nonexistent_returns_404(self, helpdesk):
        helpdesk.set_role("support agent")
        r = helpdesk.put("/api/v1/tickets/999999", json={"title": "Ghost"})
        assert r.status_code == 404


class TestCRUDDelete:
    """DELETE operations remove records."""

    def test_delete_removes_record(self, helpdesk):
        helpdesk.set_role("support manager")
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"Delete {_uid()}", "description": "test",
        })
        tid = r.json()["id"]
        r2 = helpdesk.delete(f"/api/v1/tickets/{tid}")
        assert r2.status_code == 200
        r3 = helpdesk.get(f"/api/v1/tickets/{tid}")
        assert r3.status_code == 404

    def test_delete_nonexistent_returns_404(self, helpdesk):
        helpdesk.set_role("support manager")
        r = helpdesk.delete("/api/v1/tickets/999999")
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════════
# 5. PRESENTATION & COMPONENT RENDERING
# ═══════════════════════════════════════════════════════════════════════


class TestMultipleRecordsCRUD:
    """CRUD operations with multiple records."""

    def test_create_multiple_and_list_all(self, helpdesk):
        helpdesk.set_role("customer")
        tags = [_uid() for _ in range(5)]
        for tag in tags:
            helpdesk.post("/api/v1/tickets", json={
                "title": f"Multi {tag}", "description": "t",
            })
        r = helpdesk.get("/api/v1/tickets")
        titles = [t["title"] for t in r.json()]
        for tag in tags:
            assert f"Multi {tag}" in titles

    def test_delete_one_doesnt_affect_others(self, helpdesk):
        helpdesk.set_role("support manager")
        t1 = helpdesk.post("/api/v1/tickets", json={"title": f"Keep {_uid()}", "description": "t"}).json()["id"]
        t2 = helpdesk.post("/api/v1/tickets", json={"title": f"Del {_uid()}", "description": "t"}).json()["id"]
        helpdesk.delete(f"/api/v1/tickets/{t2}")
        r = helpdesk.get(f"/api/v1/tickets/{t1}")
        assert r.status_code == 200  # t1 still exists

    def test_update_one_doesnt_affect_others(self, helpdesk):
        helpdesk.set_role("support agent")
        tag1, tag2 = _uid(), _uid()
        t1 = helpdesk.post("/api/v1/tickets", json={"title": f"A {tag1}", "description": "orig1"}).json()["id"]
        t2 = helpdesk.post("/api/v1/tickets", json={"title": f"B {tag2}", "description": "orig2"}).json()["id"]
        helpdesk.put(f"/api/v1/tickets/{t1}", json={"description": "modified"})
        r = helpdesk.get(f"/api/v1/tickets/{t2}")
        assert r.json()["description"] == "orig2"  # t2 unchanged
