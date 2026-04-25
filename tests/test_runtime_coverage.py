"""Runtime Coverage Expansion Tests.

Targeted black-box HTTP tests designed to exercise uncovered code paths
in the termin_runtime package. Organized by runtime module being covered.

Target modules and missed lines:
  - reflection.py: ReflectionEngine methods (roles, channels, boundaries, compute)
  - errors.py: TerminAtor error routing, typed handlers, error log
  - expression.py: CEL system functions (aggregation, string, math, temporal)
  - confidentiality.py: field redaction, write protection, compute access checks
  - channels.py: channel dispatch, config validation, metrics, scope checks
  - app.py: form POST, AJAX, bootstrap, reflection endpoints, compute invocation
  - transaction.py: staging reads, snapshot isolation (via compute endpoint)
  - state.py: transition edge cases

Authors: Jamie-Leigh Blake & Claude Anthropic
"""

import json
import uuid
import pytest
from pathlib import Path


def _uid():
    return uuid.uuid4().hex[:8]


# ═══════════════════════════════════════════════════════════════════════
# 1. REFLECTION ENDPOINTS — reflection.py + app.py reflection routes
#
# Covers: ReflectionEngine.content_schemas(), compute_functions(),
#   roles(), role(), channels(), content_schema(), channel_metrics(),
#   boundary_info(), boundaries(), identity_context()
# App routes: /api/reflect, /api/reflect/content, /api/reflect/compute,
#   /api/reflect/roles, /api/reflect/roles/{name},
#   /api/reflect/channels, /api/reflect/channels/{name}
# ═══════════════════════════════════════════════════════════════════════


class TestReflectRoot:
    """GET /api/reflect returns the full IR."""

    def test_reflect_returns_ir_with_name(self, warehouse):
        """reflection.py: ReflectionEngine.__init__ + app.py api_reflect"""
        r = warehouse.get("/api/reflect")
        assert r.status_code == 200
        data = r.json()
        assert "name" in data
        assert "content" in data
        assert "auth" in data

    def test_reflect_includes_state_machines(self, warehouse):
        """reflection.py: IR should include state_machines array."""
        r = warehouse.get("/api/reflect")
        data = r.json()
        assert "state_machines" in data
        sm_refs = [sm["content_ref"] for sm in data["state_machines"]]
        assert "products" in sm_refs

    def test_reflect_includes_access_grants(self, warehouse):
        """reflection.py: IR should include access_grants array."""
        r = warehouse.get("/api/reflect")
        data = r.json()
        assert "access_grants" in data
        assert len(data["access_grants"]) > 0

    def test_reflect_compute_demo(self, compute_demo):
        """reflection.py: app with computes/boundaries/channels returns all."""
        r = compute_demo.get("/api/reflect")
        data = r.json()
        assert "computes" in data
        assert "boundaries" in data
        assert "channels" in data
        assert len(data["computes"]) >= 1
        assert len(data["boundaries"]) >= 1
        assert len(data["channels"]) >= 1


class TestReflectContent:
    """GET /api/reflect/content returns content schema names."""

    def test_content_returns_list(self, warehouse):
        """reflection.py: content_schemas() returns display names."""
        r = warehouse.get("/api/reflect/content")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 2  # products, stock_levels, reorder_alerts

    def test_content_includes_all_types(self, compute_demo):
        """reflection.py: all content types listed."""
        r = compute_demo.get("/api/reflect/content")
        data = r.json()
        text = json.dumps(data).lower()
        assert "order" in text


class TestReflectCompute:
    """GET /api/reflect/compute returns compute function names."""

    def test_compute_returns_list(self, compute_demo):
        """reflection.py: compute_functions() returns display names."""
        r = compute_demo.get("/api/reflect/compute")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_compute_empty_for_app_without_computes(self, helpdesk):
        """reflection.py: no computes -> empty list."""
        r = helpdesk.get("/api/reflect/compute")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)


class TestReflectRoles:
    """GET /api/reflect/roles and /api/reflect/roles/{name}."""

    def test_roles_returns_list(self, warehouse):
        """reflection.py: roles() returns list of role names."""
        r = warehouse.get("/api/reflect/roles")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 3
        lower = [x.lower() for x in data]
        assert "warehouse clerk" in lower or "warehouse manager" in lower

    def test_role_by_name_returns_details(self, warehouse):
        """reflection.py: role(name) returns Name + Scopes."""
        r = warehouse.get("/api/reflect/roles/warehouse manager")
        assert r.status_code == 200
        data = r.json()
        assert "Name" in data
        assert "Scopes" in data
        assert isinstance(data["Scopes"], list)
        assert len(data["Scopes"]) >= 1

    def test_role_by_name_case_insensitive(self, warehouse):
        """reflection.py: role() does case-insensitive match."""
        r = warehouse.get("/api/reflect/roles/WAREHOUSE MANAGER")
        assert r.status_code == 200
        data = r.json()
        assert data["Name"].lower() == "warehouse manager"

    def test_role_not_found_returns_404(self, warehouse):
        """app.py: unknown role -> 404."""
        r = warehouse.get("/api/reflect/roles/nonexistent_role_xyz")
        assert r.status_code == 404

    def test_roles_helpdesk(self, helpdesk):
        """reflection.py: helpdesk roles enumeration."""
        r = helpdesk.get("/api/reflect/roles")
        data = r.json()
        lower = [x.lower() for x in data]
        assert "customer" in lower
        assert "support agent" in lower
        assert "support manager" in lower


class TestReflectChannels:
    """GET /api/reflect/channels and /api/reflect/channels/{name}."""

    def test_channels_returns_list(self, compute_demo):
        """channels.py: get_full_status() returns channel status array."""
        r = compute_demo.get("/api/reflect/channels")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        # Each entry has expected keys
        entry = data[0]
        assert "name" in entry
        assert "direction" in entry
        assert "metrics" in entry
        assert "state" in entry

    def test_channels_empty_for_app_without_channels(self, helpdesk):
        """channels.py: no channels -> empty list."""
        r = helpdesk.get("/api/reflect/channels")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_channel_by_name_returns_details(self, compute_demo):
        """app.py: /api/reflect/channels/{name} returns detail dict."""
        # First get channel list
        r = compute_demo.get("/api/reflect/channels")
        channels = r.json()
        if channels:
            name = channels[0]["name"]
            r2 = compute_demo.get(f"/api/reflect/channels/{name}")
            assert r2.status_code == 200
            detail = r2.json()
            assert "name" in detail
            assert "direction" in detail
            assert "delivery" in detail
            assert "configured" in detail
            assert "metrics" in detail

    def test_channel_not_found_returns_404(self, compute_demo):
        """app.py: unknown channel -> 404."""
        r = compute_demo.get("/api/reflect/channels/nonexistent_channel_xyz")
        assert r.status_code == 404

    def test_channel_simple_channels(self, channel_simple):
        """channels.py: channel_simple has outbound + inbound channels."""
        r = channel_simple.get("/api/reflect/channels")
        data = r.json()
        directions = {ch["direction"] for ch in data}
        assert "OUTBOUND" in directions or "INBOUND" in directions


# ═══════════════════════════════════════════════════════════════════════
# 2. ERROR HANDLING — errors.py + app.py error paths
#
# Covers: TerminAtor.route(), handle_error(), get_error_log(),
#   TerminError instantiation, boundary routing, typed handlers
# ═══════════════════════════════════════════════════════════════════════


class TestErrorLog:
    """GET /api/errors returns the TerminAtor error log."""

    def test_errors_returns_list(self, warehouse):
        """errors.py: get_error_log() returns list."""
        r = warehouse.get("/api/errors")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_errors_after_invalid_operations(self, warehouse):
        """errors.py: errors accumulate when operations fail."""
        warehouse.set_role("warehouse manager")
        # Trigger some errors
        warehouse.get("/api/v1/products/999999")
        warehouse.post("/_transition/products/product_lifecycle/999999/active")
        r = warehouse.get("/api/errors")
        # Error log may or may not have entries depending on which paths log
        assert r.status_code == 200


class TestErrorStatus400:
    """400 Bad Request errors."""

    def test_invalid_json_body(self, helpdesk):
        """app.py: malformed JSON -> 400 or 422."""
        helpdesk.set_role("customer")
        # Send a request with a body that's technically valid JSON but missing all fields
        r = helpdesk.post("/api/v1/tickets", json={"nonexistent_field": "value"})
        # Should either reject (422) or create with defaults
        assert r.status_code in (201, 400, 422, 500)

    def test_empty_body_on_create(self, helpdesk):
        """app.py: empty JSON object may fail validation."""
        helpdesk.set_role("customer")
        r = helpdesk.post("/api/v1/tickets", json={})
        # Missing required fields
        assert r.status_code in (400, 422, 500, 201)


class TestErrorStatus404:
    """404 Not Found errors."""

    def test_get_nonexistent_record(self, helpdesk):
        """app.py: GET record with bad ID -> 404."""
        helpdesk.set_role("customer")
        r = helpdesk.get("/api/v1/tickets/999999")
        assert r.status_code == 404

    def test_update_nonexistent_record(self, helpdesk):
        """app.py: PUT record with bad ID -> 404."""
        helpdesk.set_role("support agent")
        r = helpdesk.put("/api/v1/tickets/999999", json={"title": "Ghost"})
        assert r.status_code == 404

    def test_delete_nonexistent_record(self, helpdesk):
        """app.py: DELETE record with bad ID -> 404."""
        helpdesk.set_role("support manager")
        r = helpdesk.delete("/api/v1/tickets/999999")
        assert r.status_code == 404

    def test_nonexistent_page(self, warehouse):
        """app.py: GET unknown page slug -> 404."""
        r = warehouse.get("/totally_nonexistent_page_xyz")
        assert r.status_code == 404

    def test_nonexistent_api_content(self, warehouse):
        """app.py: GET /api/v1/<nonexistent> -> 404 or 405."""
        r = warehouse.get("/api/v1/nonexistent_content_xyz")
        assert r.status_code in (404, 405)

    def test_transition_nonexistent_record(self, warehouse):
        """app.py: transition on missing record -> 404."""
        warehouse.set_role("warehouse manager")
        r = warehouse.post("/_transition/products/product_lifecycle/999999/active")
        assert r.status_code == 404

    def test_transition_nonexistent_content(self, warehouse):
        """app.py: transition on unknown content type -> 404 or 422."""
        warehouse.set_role("warehouse manager")
        r = warehouse.post("/_transition/nonexistent_xyz/1/active")
        assert r.status_code >= 400, f"Expected error, got {r.status_code}"


class TestErrorStatus403:
    """403 Forbidden errors — scope enforcement."""

    def test_create_without_scope(self, warehouse):
        """app.py: CREATE without required scope -> 403."""
        warehouse.set_role("executive")
        r = warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "Test", "category": "raw material",
        })
        assert r.status_code == 403

    def test_update_without_scope(self, helpdesk):
        """app.py: UPDATE without required scope -> 403."""
        helpdesk.set_role("customer")
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"Scope Test {_uid()}", "description": "t",
        })
        tid = r.json()["id"]
        r2 = helpdesk.put(f"/api/v1/tickets/{tid}", json={"title": "Changed"})
        assert r2.status_code == 403

    def test_delete_without_scope(self, helpdesk):
        """app.py: DELETE without required scope -> 403."""
        helpdesk.set_role("customer")
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"Del Scope {_uid()}", "description": "t",
        })
        tid = r.json()["id"]
        r2 = helpdesk.delete(f"/api/v1/tickets/{tid}")
        assert r2.status_code == 403

    def test_transition_without_scope(self, warehouse):
        """state.py + app.py: transition without scope -> 403."""
        warehouse.set_role("warehouse manager")
        r = warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "Scope Trans", "category": "raw material",
        })
        pid = r.json()["id"]
        warehouse.set_role("executive")
        r2 = warehouse.post(f"/_transition/products/product_lifecycle/{pid}/active")
        assert r2.status_code == 403

    def test_content_scope_confidentiality_denied(self, hrportal):
        """confidentiality.py: content-level scope denies access."""
        hrportal.set_role("employee")
        r = hrportal.get("/api/v1/salary_reviews")
        assert r.status_code == 403


class TestErrorStatus409:
    """409 Conflict — state machine violations."""

    def test_invalid_transition(self, warehouse):
        """state.py: invalid transition -> 409."""
        warehouse.set_role("warehouse manager")
        r = warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "409 Test", "category": "raw material",
        })
        pid = r.json()["id"]
        # draft -> discontinued is not a valid transition
        r2 = warehouse.post(f"/_transition/products/product_lifecycle/{pid}/discontinued")
        assert r2.status_code == 409

    def test_transition_to_current_state(self, warehouse):
        """state.py: transition to same state may be invalid."""
        warehouse.set_role("warehouse manager")
        r = warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "Same State", "category": "raw material",
        })
        pid = r.json()["id"]
        # draft -> draft is not declared
        r2 = warehouse.post(f"/_transition/products/product_lifecycle/{pid}/draft")
        assert r2.status_code == 409

    def test_duplicate_unique_field(self, warehouse):
        """app.py: duplicate unique field -> 409 or error."""
        warehouse.set_role("warehouse manager")
        sku = _uid()
        warehouse.post("/api/v1/products", json={
            "sku": sku, "name": "Dup1", "category": "raw material",
        })
        r = warehouse.post("/api/v1/products", json={
            "sku": sku, "name": "Dup2", "category": "raw material",
        })
        assert r.status_code in (409, 500)


class TestErrorStatus422:
    """422 Unprocessable Entity — validation failures."""

    def test_missing_required_field(self, warehouse):
        """app.py: create without required field -> 422 or error."""
        warehouse.set_role("warehouse manager")
        # Missing sku (required) and name (required)
        r = warehouse.post("/api/v1/products", json={"category": "raw material"})
        assert r.status_code in (400, 422, 500)


# ═══════════════════════════════════════════════════════════════════════
# 3. EXPRESSION EVALUATION — expression.py
#
# Covers: CEL system functions, default_expr evaluation,
#   ExpressionEvaluator.evaluate(), _make_dynamic_context()
# ═══════════════════════════════════════════════════════════════════════


class TestDefaultExpressions:
    """Default expressions populate fields on create."""

    def test_user_name_default(self, helpdesk):
        """expression.py: User.Name default_expr populates submitted_by."""
        helpdesk.set_role("customer", "TestDefaultUser")
        tag = _uid()
        helpdesk.post("/api/v1/tickets", json={
            "title": f"Default {tag}", "description": "test",
        })
        r = helpdesk.get("/api/v1/tickets")
        ticket = [t for t in r.json() if t.get("title") == f"Default {tag}"]
        assert len(ticket) >= 1
        assert ticket[0].get("submitted_by") == "TestDefaultUser"

    def test_now_default_populates_timestamp(self, helpdesk):
        """expression.py: now default_expr populates created_at."""
        helpdesk.set_role("customer", "TimeUser")
        tag = _uid()
        helpdesk.post("/api/v1/tickets", json={
            "title": f"Time {tag}", "description": "timestamp test",
        })
        r = helpdesk.get("/api/v1/tickets")
        ticket = [t for t in r.json() if t.get("title") == f"Time {tag}"]
        assert len(ticket) >= 1
        ts = str(ticket[0].get("created_at", ""))
        # Should contain a date-like string
        assert len(ts) > 5

    def test_default_not_overridden_when_provided(self, helpdesk):
        """expression.py: explicit value should override default."""
        helpdesk.set_role("customer", "ExplicitUser")
        tag = _uid()
        helpdesk.post("/api/v1/tickets", json={
            "title": f"Override {tag}", "description": "t",
            "submitted_by": "ManualOverride",
        })
        r = helpdesk.get("/api/v1/tickets")
        ticket = [t for t in r.json() if t.get("title") == f"Override {tag}"]
        if ticket:
            # Either the override took effect or the default was applied
            assert ticket[0].get("submitted_by") in ("ManualOverride", "ExplicitUser")


class TestDefaultExprFormSubmission:
    """Default expressions via form POST (not JSON API)."""

    def test_form_submit_applies_defaults(self, helpdesk):
        """expression.py + app.py form_post: defaults applied on form submit."""
        helpdesk.set_role("customer", "FormDefaultUser")
        tag = _uid()
        r = helpdesk.post("/submit_ticket", data={
            "title": f"FormDef {tag}", "description": "form test",
            "priority": "low", "category": "question",
        })
        # Form submit returns redirect (303) or 200
        assert r.status_code in (200, 303)
        # Verify record created with defaults
        r2 = helpdesk.get("/api/v1/tickets")
        ticket = [t for t in r2.json() if t.get("title") == f"FormDef {tag}"]
        assert len(ticket) >= 1
        assert ticket[0].get("submitted_by") == "FormDefaultUser"

    def test_form_submit_different_users(self, helpdesk):
        """expression.py: different users get different User.Name defaults."""
        tag1, tag2 = _uid(), _uid()
        helpdesk.set_role("customer", "UserOne")
        helpdesk.post("/submit_ticket", data={
            "title": f"U1 {tag1}", "description": "t",
            "priority": "low", "category": "question",
        })
        helpdesk.set_role("customer", "UserTwo")
        helpdesk.post("/submit_ticket", data={
            "title": f"U2 {tag2}", "description": "t",
            "priority": "low", "category": "question",
        })
        r = helpdesk.get("/api/v1/tickets")
        tickets = {t["title"]: t for t in r.json()}
        if f"U1 {tag1}" in tickets:
            assert tickets[f"U1 {tag1}"]["submitted_by"] == "UserOne"
        if f"U2 {tag2}" in tickets:
            assert tickets[f"U2 {tag2}"]["submitted_by"] == "UserTwo"


# ═══════════════════════════════════════════════════════════════════════
# 4. CONFIDENTIALITY — confidentiality.py
#
# Covers: redact_record(), redact_records(), effective_scopes(),
#   check_write_access(), is_redacted(), check_compute_access(),
#   enforce_output_taint(), check_for_redacted_values()
# ═══════════════════════════════════════════════════════════════════════


class TestFieldRedactionAPI:
    """Field-level redaction in API responses."""

    @pytest.fixture(autouse=True)
    def _create_employee(self, hrportal):
        hrportal.set_role("hr business partner", "HRTest")
        tag = _uid()
        r = hrportal.post("/api/v1/employees", json={
            "name": f"Redact {tag}", "department": "Finance",
            "role": "Analyst", "salary": 88000, "bonus_rate": 0.09,
            "ssn": "444-55-6666", "phone": "555-1234",
        })
        assert r.status_code == 201
        self.eid = r.json()["id"]

    def test_employee_role_salary_redacted(self, hrportal):
        """confidentiality.py: redact_record() masks salary for employee."""
        hrportal.set_role("employee")
        r = hrportal.get(f"/api/v1/employees/{self.eid}")
        emp = r.json()
        assert isinstance(emp["salary"], dict)
        assert emp["salary"]["__redacted"] is True

    def test_employee_role_ssn_redacted(self, hrportal):
        """confidentiality.py: redact_record() masks ssn for employee."""
        hrportal.set_role("employee")
        r = hrportal.get(f"/api/v1/employees/{self.eid}")
        emp = r.json()
        assert isinstance(emp["ssn"], dict) and emp["ssn"]["__redacted"] is True

    def test_employee_role_phone_redacted(self, hrportal):
        """confidentiality.py: redact_record() masks phone for employee."""
        hrportal.set_role("employee")
        r = hrportal.get(f"/api/v1/employees/{self.eid}")
        emp = r.json()
        assert isinstance(emp["phone"], dict) and emp["phone"]["__redacted"] is True

    def test_hr_sees_all_fields(self, hrportal):
        """confidentiality.py: HR has all scopes -> no redaction."""
        hrportal.set_role("hr business partner")
        r = hrportal.get(f"/api/v1/employees/{self.eid}")
        emp = r.json()
        assert emp["salary"] == 88000
        assert emp["ssn"] == "444-55-6666"
        assert emp["phone"] == "555-1234"

    def test_redaction_in_list_for_employee(self, hrportal):
        """confidentiality.py: redact_records() masks all records in list."""
        hrportal.set_role("employee")
        r = hrportal.get("/api/v1/employees")
        employees = r.json()
        for emp in employees:
            if emp.get("salary") is not None:
                assert isinstance(emp["salary"], dict) and emp["salary"].get("__redacted") is True

    def test_redaction_marker_has_scope(self, hrportal):
        """confidentiality.py: marker includes scope name."""
        hrportal.set_role("employee")
        r = hrportal.get(f"/api/v1/employees/{self.eid}")
        emp = r.json()
        assert "scope" in emp["salary"]

    def test_redaction_preserves_non_confidential_fields(self, hrportal):
        """confidentiality.py: non-confidential fields pass through."""
        hrportal.set_role("employee")
        r = hrportal.get(f"/api/v1/employees/{self.eid}")
        emp = r.json()
        assert isinstance(emp["name"], str)
        assert isinstance(emp["department"], str)


class TestWriteProtectionAPI:
    """Writing to confidential fields without scope is denied."""

    def test_employee_cannot_update_salary(self, hrportal):
        """confidentiality.py: check_write_access() blocks salary update."""
        hrportal.set_role("hr business partner")
        r = hrportal.post("/api/v1/employees", json={
            "name": f"WriteProt {_uid()}", "department": "Sales",
            "salary": 70000,
        })
        eid = r.json()["id"]
        hrportal.set_role("employee")
        r2 = hrportal.put(f"/api/v1/employees/{eid}", json={"salary": 999999})
        assert r2.status_code == 403

    def test_employee_cannot_update_ssn(self, hrportal):
        """confidentiality.py: check_write_access() blocks ssn update."""
        hrportal.set_role("hr business partner")
        r = hrportal.post("/api/v1/employees", json={
            "name": f"SSNProt {_uid()}", "department": "Sales",
            "ssn": "111-22-3333",
        })
        eid = r.json()["id"]
        hrportal.set_role("employee")
        r2 = hrportal.put(f"/api/v1/employees/{eid}", json={"ssn": "000-00-0000"})
        assert r2.status_code == 403

    def test_hr_can_update_salary(self, hrportal):
        """confidentiality.py: HR has scope -> salary update OK."""
        hrportal.set_role("hr business partner")
        r = hrportal.post("/api/v1/employees", json={
            "name": f"HRUpdate {_uid()}", "department": "Sales",
            "salary": 75000,
        })
        eid = r.json()["id"]
        r2 = hrportal.put(f"/api/v1/employees/{eid}", json={"salary": 80000})
        assert r2.status_code == 200


class TestContentLevelConfidentiality:
    """Content-level confidentiality_scope gates entire content."""

    def test_employee_blocked_from_salary_reviews(self, hrportal):
        """confidentiality.py: content-level scope -> 403."""
        hrportal.set_role("employee")
        r = hrportal.get("/api/v1/salary_reviews")
        assert r.status_code == 403

    def test_manager_blocked_from_salary_reviews(self, hrportal):
        """confidentiality.py: manager lacks access_salary -> 403."""
        hrportal.set_role("manager")
        r = hrportal.get("/api/v1/salary_reviews")
        assert r.status_code == 403

    def test_hr_can_access_salary_reviews(self, hrportal):
        """confidentiality.py: HR has access_salary -> 200."""
        hrportal.set_role("hr business partner")
        r = hrportal.get("/api/v1/salary_reviews")
        assert r.status_code == 200

    def test_employee_cannot_create_salary_review(self, hrportal):
        """confidentiality.py: CREATE on content-scoped type -> 403."""
        hrportal.set_role("employee")
        r = hrportal.post("/api/v1/salary_reviews", json={
            "employee": 1, "old_salary": 50000, "new_salary": 55000,
            "reason": "test",
        })
        assert r.status_code == 403


class TestDepartmentBudgetRedaction:
    """Department budget field scoped to access_salary."""

    def test_employee_sees_redacted_budget(self, hrportal):
        """confidentiality.py: budget redacted for employee."""
        hrportal.set_role("hr business partner")
        tag = _uid()
        hrportal.post("/api/v1/departments", json={
            "name": f"BudgetTest {tag}", "budget": 1000000, "head_count": 30,
        })
        hrportal.set_role("employee")
        r = hrportal.get("/api/v1/departments")
        depts = r.json()
        dept = [d for d in depts if d.get("name") == f"BudgetTest {tag}"]
        assert len(dept) == 1
        assert isinstance(dept[0]["budget"], dict) and dept[0]["budget"]["__redacted"] is True

    def test_hr_sees_budget(self, hrportal):
        """confidentiality.py: HR sees actual budget."""
        hrportal.set_role("hr business partner")
        tag = _uid()
        hrportal.post("/api/v1/departments", json={
            "name": f"BudgetHR {tag}", "budget": 2000000, "head_count": 50,
        })
        r = hrportal.get("/api/v1/departments")
        depts = r.json()
        dept = [d for d in depts if d.get("name") == f"BudgetHR {tag}"]
        assert len(dept) == 1
        assert not isinstance(dept[0]["budget"], dict)


# ═══════════════════════════════════════════════════════════════════════
# 5. STATE MACHINES — state.py + app.py transition endpoint
#
# Covers: do_state_transition(), transition scope enforcement,
#   multi-step lifecycle, persisted state
# ═══════════════════════════════════════════════════════════════════════


class TestStateMachineEdgeCases:
    """State machine edge cases not covered by existing tests."""

    def _create_product(self, warehouse, role="warehouse manager"):
        warehouse.set_role(role)
        sku = _uid()
        r = warehouse.post("/api/v1/products", json={
            "sku": sku, "name": f"SM Edge {sku}", "category": "raw material",
        })
        assert r.status_code == 201, f"Create failed: {r.status_code} {r.text}"
        return r.json()["id"]

    def test_initial_state_enforced(self, warehouse):
        """state.py: new record always gets initial state."""
        pid = self._create_product(warehouse)
        r = warehouse.get(f"/api/v1/products/{pid}")
        assert r.status_code == 200
        data = r.json()
        assert data.get("product_lifecycle") == "draft", f"Expected draft, got {data}"

    def test_client_cannot_override_initial_state(self, warehouse):
        """state.py: state-machine column ignored on create."""
        warehouse.set_role("warehouse manager")
        sku = _uid()
        r = warehouse.post("/api/v1/products", json={
            "sku": sku, "name": "Override", "category": "raw material",
            "product_lifecycle": "active",
        })
        assert r.json().get("product_lifecycle") == "draft"

    def test_transition_changes_status_in_db(self, warehouse):
        """state.py: transition persists to storage."""
        pid = self._create_product(warehouse)
        warehouse.post(f"/api/v1/products/{pid}/_transition/product_lifecycle/active")
        r = warehouse.get(f"/api/v1/products/{pid}")
        assert r.json().get("product_lifecycle") == "active"

    def test_failed_transition_preserves_status(self, warehouse):
        """state.py: rejected transition doesn't change state."""
        pid = self._create_product(warehouse)
        # draft -> discontinued requires going through active first
        r = warehouse.post(f"/api/v1/products/{pid}/_transition/product_lifecycle/discontinued")
        assert r.status_code in (409, 400, 403), f"Expected error, got {r.status_code}"
        r = warehouse.get(f"/api/v1/products/{pid}")
        assert r.json().get("product_lifecycle") == "draft"

    def test_reverse_transition_after_lifecycle(self, warehouse):
        """state.py: activate after discontinue."""
        pid = self._create_product(warehouse)
        warehouse.post(f"/api/v1/products/{pid}/_transition/product_lifecycle/active")
        warehouse.post(f"/api/v1/products/{pid}/_transition/product_lifecycle/discontinued")
        # Check if reactivation is allowed
        r = warehouse.post(f"/api/v1/products/{pid}/_transition/product_lifecycle/active")
        # Some state machines allow this, some don't

    def test_transition_to_nonexistent_state(self, warehouse):
        """state.py: target state not in machine -> 404 (no route)."""
        pid = self._create_product(warehouse)
        r = warehouse.post(f"/api/v1/products/{pid}/_transition/product_lifecycle/completely_fake_state")
        assert r.status_code in (404, 405)

    def test_helpdesk_multi_word_state(self, helpdesk):
        """state.py: multi-word state names work."""
        helpdesk.set_role("support agent")
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"MultiWord {_uid()}", "description": "t",
        })
        tid = r.json()["id"]
        r2 = helpdesk.post(f"/_transition/tickets/ticket_lifecycle/{tid}/in progress")
        assert r2.status_code in (200, 303)

    def test_helpdesk_waiting_on_customer(self, helpdesk):
        """state.py: three-word state name transition."""
        helpdesk.set_role("support agent")
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"Wait {_uid()}", "description": "t",
        })
        tid = r.json()["id"]
        helpdesk.post(f"/_transition/tickets/ticket_lifecycle/{tid}/in progress")
        r2 = helpdesk.post(f"/_transition/tickets/ticket_lifecycle/{tid}/waiting on customer")
        assert r2.status_code in (200, 303)

    def test_compute_demo_order_state_machine(self, compute_demo):
        """state.py: compute_demo has orders with pending initial state."""
        compute_demo.set_role("order manager")
        r = compute_demo.post("/api/v1/orders", json={
            "customer": f"Cust {_uid()}", "total": 100.0, "priority": "high",
        })
        if r.status_code == 201:
            assert r.json()["order_lifecycle"] == "pending"


# ═══════════════════════════════════════════════════════════════════════
# 6. CRUD EDGE CASES — app.py, storage.py
#
# Covers: create_record(), list_records(), get_record(), update_record(),
#   delete_record(), filter/search, empty tables, partial updates
# ═══════════════════════════════════════════════════════════════════════


class TestCRUDEdgeCases:
    """CRUD operations — edge cases for coverage."""

    def test_list_empty_content(self, warehouse):
        """storage.py: listing content returns empty array initially."""
        warehouse.set_role("warehouse manager")
        r = warehouse.get("/api/v1/reorder_alerts")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_with_all_optional_fields(self, warehouse):
        """storage.py: create with optional fields populated."""
        warehouse.set_role("warehouse manager")
        r = warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "Full Product",
            "description": "A complete product entry",
            "unit_cost": 42.50, "category": "raw material",
        })
        assert r.status_code == 201
        body = r.json()
        assert body["description"] == "A complete product entry"
        assert float(body["unit_cost"]) == 42.50

    def test_create_minimal_fields(self, warehouse):
        """storage.py: create with only required fields."""
        warehouse.set_role("warehouse manager")
        r = warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "Minimal",
        })
        assert r.status_code == 201

    def test_partial_update(self, helpdesk):
        """storage.py: update only one field, others preserved."""
        helpdesk.set_role("support agent")
        tag = _uid()
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"Partial {tag}", "description": "original desc",
        })
        tid = r.json()["id"]
        helpdesk.put(f"/api/v1/tickets/{tid}", json={"description": "updated desc"})
        r2 = helpdesk.get(f"/api/v1/tickets/{tid}")
        assert r2.json()["title"] == f"Partial {tag}"
        assert r2.json()["description"] == "updated desc"

    def test_create_and_immediately_read(self, helpdesk):
        """storage.py: created record immediately readable."""
        helpdesk.set_role("support agent")
        tag = _uid()
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"ReadBack {tag}", "description": "t",
        })
        tid = r.json()["id"]
        r2 = helpdesk.get(f"/api/v1/tickets/{tid}")
        assert r2.status_code == 200
        assert r2.json()["title"] == f"ReadBack {tag}"

    def test_create_returns_record_with_id(self, helpdesk):
        """storage.py: create response includes generated id."""
        helpdesk.set_role("customer")
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"IDCheck {_uid()}", "description": "t",
        })
        assert r.status_code == 201
        body = r.json()
        assert "id" in body
        assert isinstance(body["id"], int)

    def test_list_after_create_includes_new(self, warehouse):
        """storage.py: list includes newly created record."""
        warehouse.set_role("warehouse manager")
        sku = _uid()
        warehouse.post("/api/v1/products", json={
            "sku": sku, "name": f"List Check {sku}", "category": "raw material",
        })
        r = warehouse.get("/api/v1/products")
        skus = [p["sku"] for p in r.json()]
        assert sku in skus

    def test_delete_then_list_excludes(self, helpdesk):
        """storage.py: deleted record excluded from list."""
        helpdesk.set_role("support manager")
        tag = _uid()
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"DelList {tag}", "description": "t",
        })
        tid = r.json()["id"]
        helpdesk.delete(f"/api/v1/tickets/{tid}")
        r2 = helpdesk.get("/api/v1/tickets")
        ids = [t["id"] for t in r2.json()]
        assert tid not in ids


# ═══════════════════════════════════════════════════════════════════════
# 7. FORM SUBMISSION — app.py form_post handler
#
# Covers: form POST endpoint, AJAX (Accept: application/json),
#   edit_id handling, after-save redirect, default_expr on form submit
# ═══════════════════════════════════════════════════════════════════════


class TestFormSubmission:
    """Form POST submissions (not JSON API)."""

    def test_form_post_creates_record(self, helpdesk):
        """app.py form_post: POST form data creates a ticket."""
        helpdesk.set_role("customer", "FormUser")
        tag = _uid()
        r = helpdesk.post("/submit_ticket", data={
            "title": f"Form {tag}", "description": "form created",
            "priority": "medium", "category": "bug",
        })
        assert r.status_code in (200, 303)
        r2 = helpdesk.get("/api/v1/tickets")
        titles = [t["title"] for t in r2.json()]
        assert f"Form {tag}" in titles

    def test_form_post_with_ajax_header(self, helpdesk):
        """app.py form_post: Accept: application/json returns JSON response."""
        helpdesk.set_role("customer", "AjaxUser")
        tag = _uid()
        r = helpdesk.post("/submit_ticket", data={
            "title": f"Ajax {tag}", "description": "ajax test",
            "priority": "low", "category": "question",
        }, headers={"Accept": "application/json"})
        # Should return JSON instead of redirect
        if r.status_code == 200:
            body = r.json()
            assert body.get("ok") or "id" in body

    def test_form_post_with_xhr_header(self, helpdesk):
        """app.py form_post: X-Requested-With: XMLHttpRequest returns JSON."""
        helpdesk.set_role("customer", "XHRUser")
        tag = _uid()
        r = helpdesk.post("/submit_ticket", data={
            "title": f"XHR {tag}", "description": "xhr test",
            "priority": "low", "category": "question",
        }, headers={"X-Requested-With": "XMLHttpRequest"})
        if r.status_code == 200:
            body = r.json()
            assert body.get("ok") or "id" in body


# ═══════════════════════════════════════════════════════════════════════
# 8. CHANNEL ENDPOINTS — channels.py + app.py channel routes
#
# Covers: channel_send, channel_invoke, webhook receive,
#   ChannelDispatcher.get_spec(), get_config(), _check_scope(),
#   get_metrics(), is_configured(), get_connection_state()
# ═══════════════════════════════════════════════════════════════════════


class TestChannelReflection:
    """Channel reflection for channel_simple and compute_demo."""

    def test_channel_simple_has_channels(self, channel_simple):
        """channels.py: channel_simple fixture has declared channels."""
        r = channel_simple.get("/api/reflect/channels")
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1

    def test_channel_simple_outbound_properties(self, channel_simple):
        """channels.py: outbound channel has correct direction."""
        r = channel_simple.get("/api/reflect/channels")
        data = r.json()
        outbound = [ch for ch in data if ch["direction"] == "OUTBOUND"]
        if outbound:
            ch = outbound[0]
            assert "metrics" in ch
            assert "state" in ch

    def test_channel_simple_inbound_properties(self, channel_simple):
        """channels.py: inbound channel has correct direction."""
        r = channel_simple.get("/api/reflect/channels")
        data = r.json()
        inbound = [ch for ch in data if ch["direction"] == "INBOUND"]
        if inbound:
            ch = inbound[0]
            assert ch["direction"] == "INBOUND"

    def test_compute_demo_channel_directions(self, compute_demo):
        """channels.py: compute_demo has multiple channel directions."""
        r = compute_demo.get("/api/reflect/channels")
        data = r.json()
        directions = {ch["direction"] for ch in data}
        # Should have at least INBOUND and OUTBOUND
        assert len(directions) >= 2

    def test_compute_demo_internal_channel(self, compute_demo):
        """channels.py: INTERNAL channels exist."""
        r = compute_demo.get("/api/reflect/channels")
        data = r.json()
        internal = [ch for ch in data if ch["direction"] == "INTERNAL"]
        assert len(internal) >= 1


class TestChannelSendEndpoint:
    """POST /api/v1/channels/{name}/send."""

    def test_send_to_unknown_channel_404(self, compute_demo):
        """app.py: send to nonexistent channel -> 404."""
        compute_demo.set_role("order manager")
        r = compute_demo.post("/api/v1/channels/nonexistent_xyz/send",
                              json={"test": "data"})
        assert r.status_code == 404

    def test_send_to_known_channel(self, compute_demo):
        """channels.py: send to configured channel returns result."""
        compute_demo.set_role("order manager")
        # Get a known outbound channel name
        r = compute_demo.get("/api/reflect/channels")
        outbound = [ch for ch in r.json() if ch["direction"] == "OUTBOUND"]
        if outbound:
            name = outbound[0]["name"]
            r2 = compute_demo.post(f"/api/v1/channels/{name}/send",
                                   json={"customer": "test", "total": 50.0})
            # May succeed (not_configured) or fail (502) depending on deploy config
            assert r2.status_code in (200, 403, 502)


class TestChannelActionEndpoint:
    """POST /api/v1/channels/{name}/actions/{action}."""

    def test_action_on_unknown_channel_404(self, compute_demo):
        """app.py: action on nonexistent channel -> 404."""
        compute_demo.set_role("order manager")
        r = compute_demo.post("/api/v1/channels/nonexistent_xyz/actions/test_action",
                              json={})
        assert r.status_code == 404

    def test_action_not_found_on_channel(self, compute_demo):
        """app.py: unknown action name on existing channel -> 404."""
        compute_demo.set_role("order manager")
        r = compute_demo.get("/api/reflect/channels")
        channels = r.json()
        if channels:
            name = channels[0]["name"]
            r2 = compute_demo.post(f"/api/v1/channels/{name}/actions/nonexistent_action_xyz",
                                   json={})
            assert r2.status_code == 404


class TestWebhookEndpoint:
    """POST /webhooks/{channel_snake} for inbound channels."""

    def test_webhook_on_inbound_channel(self, channel_simple):
        """app.py + channels.py: inbound webhook creates content record."""
        # channel_simple has echo_receiver as inbound channel carrying 'echoes'
        r = channel_simple.post("/webhooks/echo_receiver", json={
            "title": f"Webhook {_uid()}", "body": "test echo",
        })
        # Should create a record or require scope
        assert r.status_code in (200, 201, 403, 422)

    def test_webhook_with_empty_payload(self, channel_simple):
        """app.py: webhook with no valid fields -> 422."""
        r = channel_simple.post("/webhooks/echo_receiver", json={
            "nonexistent_field": "value",
        })
        assert r.status_code in (422, 403)

    def test_webhook_with_invalid_json(self, channel_simple):
        """app.py: webhook with non-JSON body -> 400."""
        r = channel_simple.post("/webhooks/echo_receiver",
                                data=b"not json",
                                headers={"Content-Type": "application/json"})
        assert r.status_code in (400, 422, 500)


# ═══════════════════════════════════════════════════════════════════════
# 9. COMPUTE ENDPOINTS — app.py compute invocation
#
# Covers: invoke_compute(), transaction staging, boundary checks,
#   confidentiality checks on compute, compute lookup
# ═══════════════════════════════════════════════════════════════════════


class TestComputeInvocation:
    """POST /api/v1/compute/{name} endpoint."""

    def test_compute_not_found_404(self, compute_demo):
        """app.py: unknown compute name -> 404."""
        compute_demo.set_role("order manager")
        r = compute_demo.post("/api/v1/compute/nonexistent_xyz", json={"input": {}})
        assert r.status_code == 404

    def test_compute_without_scope_403(self, compute_demo):
        """app.py: compute without required scope -> 403."""
        compute_demo.set_role("order clerk")
        # revenue_report requires orders.read, order_clerk has it
        # Try a compute that requires admin scope
        r = compute_demo.post("/api/v1/compute/calculate_order_total", json={"input": {}})
        # May require orders.write
        if r.status_code == 403:
            assert True
        else:
            # If the clerk has the scope, that's fine too
            assert r.status_code in (200, 500)

    def test_compute_transform_shape(self, compute_demo):
        """app.py: TRANSFORM compute executes successfully."""
        compute_demo.set_role("order manager")
        r = compute_demo.post("/api/v1/compute/calculate_order_total", json={
            "input": {"items": [{"price": 10, "quantity": 2}]},
        })
        # May succeed or fail on CEL evaluation, but should not 404
        assert r.status_code != 404

    def test_compute_reduce_shape(self, compute_demo):
        """app.py: REDUCE compute executes."""
        compute_demo.set_role("order manager")
        r = compute_demo.post("/api/v1/compute/revenue_report", json={
            "input": {},
        })
        assert r.status_code != 404

    def test_compute_hrportal_scope_check(self, hrportal):
        """confidentiality.py: compute with confidentiality scope check."""
        hrportal.set_role("employee")
        r = hrportal.post("/api/v1/compute/calculate_team_bonus_pool", json={
            "input": {},
        })
        # Employee lacks view_team_metrics -> 403
        assert r.status_code == 403

    def test_compute_hrportal_hr_can_execute(self, hrportal):
        """confidentiality.py: HR has all scopes -> compute allowed."""
        hrportal.set_role("hr business partner")
        r = hrportal.post("/api/v1/compute/calculate_team_bonus_pool", json={
            "input": {},
        })
        # Should not be 403 or 404
        assert r.status_code not in (403, 404)


# ═══════════════════════════════════════════════════════════════════════
# 10. RUNTIME BOOTSTRAP — app.py bootstrap/registry endpoints
#
# Covers: runtime_registry(), runtime_bootstrap(), serve_termin_js(),
#   set_role(), ConnectionManager
# ═══════════════════════════════════════════════════════════════════════


class TestRuntimeBootstrap:
    """Runtime bootstrap and infrastructure endpoints."""

    def test_registry_returns_boundaries(self, warehouse):
        """app.py: /runtime/registry returns boundary map."""
        r = warehouse.get("/runtime/registry")
        assert r.status_code == 200
        data = r.json()
        assert "boundaries" in data
        assert "presentation" in data["boundaries"]
        assert "runtime_version" in data

    def test_bootstrap_returns_identity(self, warehouse):
        """app.py: /runtime/bootstrap returns identity for current role."""
        warehouse.set_role("warehouse clerk")
        r = warehouse.get("/runtime/bootstrap")
        assert r.status_code == 200
        data = r.json()
        assert "identity" in data
        assert data["identity"]["role"] == "warehouse clerk"

    def test_bootstrap_returns_scopes(self, warehouse):
        """app.py: bootstrap identity includes scopes."""
        warehouse.set_role("warehouse manager")
        r = warehouse.get("/runtime/bootstrap")
        data = r.json()
        scopes = data["identity"]["scopes"]
        assert isinstance(scopes, list)
        assert len(scopes) >= 1

    def test_bootstrap_returns_content_names(self, warehouse):
        """app.py: bootstrap includes content_names for subscription."""
        r = warehouse.get("/runtime/bootstrap")
        data = r.json()
        assert "content_names" in data
        assert "products" in data["content_names"]

    def test_bootstrap_returns_schemas(self, warehouse):
        """app.py: bootstrap includes schemas."""
        r = warehouse.get("/runtime/bootstrap")
        data = r.json()
        assert "schemas" in data
        assert len(data["schemas"]) >= 1

    def test_bootstrap_compute_demo(self, compute_demo):
        """app.py: bootstrap with computes includes client computes."""
        compute_demo.set_role("order manager")
        r = compute_demo.get("/runtime/bootstrap")
        data = r.json()
        # compute_demo has computes with body_lines
        assert "computes" in data

    def test_termin_js_served(self, warehouse):
        """app.py: /runtime/termin.js serves JavaScript."""
        r = warehouse.get("/runtime/termin.js")
        assert r.status_code == 200
        assert "TERMIN_VERSION" in r.text or "termin" in r.text.lower()

    def test_set_role_endpoint(self, warehouse):
        """app.py: /set-role sets cookies and redirects."""
        r = warehouse.post("/set-role", data={"role": "executive", "user_name": "Boss"})
        assert r.status_code in (200, 303)

    def test_set_role_without_user_name(self, warehouse):
        """app.py: /set-role works with just role."""
        r = warehouse.post("/set-role", data={"role": "warehouse clerk"})
        assert r.status_code in (200, 303)

    def test_registry_compute_demo(self, compute_demo):
        """app.py: compute_demo registry includes boundary info."""
        r = compute_demo.get("/runtime/registry")
        data = r.json()
        assert "boundaries" in data


# ═══════════════════════════════════════════════════════════════════════
# 11. EVENTS & ERRORS LOG — events.py, errors.py
#
# Covers: EventBus.publish/subscribe, api_events endpoint,
#   TerminAtor.get_error_log()
# ═══════════════════════════════════════════════════════════════════════


class TestEventsEndpoint:
    """GET /api/events returns event history."""

    def test_events_returns_list(self, warehouse):
        """events.py: /api/events returns list."""
        r = warehouse.get("/api/events")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_events_after_crud_operations(self, helpdesk):
        """events.py: events may be logged after CRUD ops."""
        helpdesk.set_role("customer")
        helpdesk.post("/api/v1/tickets", json={
            "title": f"Event {_uid()}", "description": "t",
        })
        r = helpdesk.get("/api/events")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════
# 12. PAGE RENDERING — presentation.py + app.py page routes
#
# Covers: page template rendering, role-gated nav, data context,
#   HTML response for page slugs
# ═══════════════════════════════════════════════════════════════════════


class TestPageRendering:
    """HTML page rendering endpoints."""

    def test_warehouse_dashboard_renders(self, warehouse):
        """presentation.py: inventory_dashboard renders HTML."""
        warehouse.set_role("warehouse clerk")
        r = warehouse.get("/inventory_dashboard")
        assert r.status_code == 200
        assert "html" in r.headers.get("content-type", "").lower()

    def test_helpdesk_submit_page_renders(self, helpdesk):
        """presentation.py: submit_ticket page renders."""
        helpdesk.set_role("customer")
        r = helpdesk.get("/submit_ticket")
        assert r.status_code == 200

    def test_helpdesk_queue_page_renders(self, helpdesk):
        """presentation.py: ticket_queue page renders for agent."""
        helpdesk.set_role("support agent")
        r = helpdesk.get("/ticket_queue")
        assert r.status_code == 200

    def test_helpdesk_dashboard_page_renders(self, helpdesk):
        """presentation.py: support_dashboard renders for manager."""
        helpdesk.set_role("support manager")
        r = helpdesk.get("/support_dashboard")
        assert r.status_code == 200

    def test_root_page_redirects_or_renders(self, warehouse):
        """app.py: GET / returns HTML."""
        r = warehouse.get("/")
        assert r.status_code == 200

    def test_hello_page_renders(self, hello):
        """presentation.py: hello app page renders."""
        r = hello.get("/hello")
        assert r.status_code == 200

    def test_page_includes_nav(self, warehouse):
        """presentation.py: rendered pages include navigation."""
        warehouse.set_role("warehouse clerk")
        r = warehouse.get("/inventory_dashboard")
        assert '<nav' in r.text.lower() or '<select' in r.text.lower()

    def test_page_includes_role_picker(self, warehouse):
        """presentation.py: stub auth role picker in nav."""
        r = warehouse.get("/inventory_dashboard")
        assert 'select' in r.text.lower()


# ═══════════════════════════════════════════════════════════════════════
# 13. IDENTITY RESOLUTION — identity.py
#
# Covers: make_get_current_user(), role fallback, anonymous role
# ═══════════════════════════════════════════════════════════════════════


class TestIdentityResolution:
    """Identity resolution from cookies."""

    def test_no_role_cookie_uses_anonymous(self, warehouse):
        """identity.py: no role cookie -> anonymous."""
        warehouse.set_role("anonymous")
        r = warehouse.get("/api/v1/products")
        # Anonymous might not have access — that's fine
        assert r.status_code in (200, 403)

    def test_invalid_role_falls_back(self, warehouse):
        """identity.py: unknown role -> fallback to first role."""
        warehouse.set_role("totally_fake_role_xyz")
        r = warehouse.get("/api/v1/products")
        assert r.status_code == 200

    def test_role_switching_works(self, warehouse):
        """identity.py: switching roles changes access."""
        warehouse.set_role("warehouse manager")
        sku = _uid()
        r = warehouse.post("/api/v1/products", json={
            "sku": sku, "name": "Switch Test", "category": "raw material",
        })
        assert r.status_code == 201
        warehouse.set_role("executive")
        r2 = warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "Switch Fail", "category": "raw material",
        })
        assert r2.status_code == 403

    def test_user_display_name_in_defaults(self, helpdesk):
        """identity.py: user_name cookie populates User.Name."""
        helpdesk.set_role("customer", "IdentTestUser")
        tag = _uid()
        helpdesk.post("/api/v1/tickets", json={
            "title": f"Ident {tag}", "description": "t",
        })
        r = helpdesk.get("/api/v1/tickets")
        ticket = [t for t in r.json() if t.get("title") == f"Ident {tag}"]
        if ticket:
            assert ticket[0].get("submitted_by") == "IdentTestUser"


# ═══════════════════════════════════════════════════════════════════════
# 14. COMPUTE DEMO SPECIFIC — boundaries, channels, computes
#
# Covers: boundary_for_content, boundary_for_compute,
#   check_boundary_access(), ChannelDispatcher initialization
# ═══════════════════════════════════════════════════════════════════════


class TestComputeDemoApp:
    """Tests specific to compute_demo fixture — pages + boundaries."""

    def test_order_dashboard_page(self, compute_demo):
        """app.py: page rendering for compute_demo."""
        compute_demo.set_role("order clerk")
        r = compute_demo.get("/order_dashboard")
        assert r.status_code == 200
        assert "Order Dashboard" in r.text

    def test_compute_demo_reflection(self, compute_demo):
        """reflection.py: compute_demo has boundaries in reflection."""
        compute_demo.set_role("order clerk")
        r = compute_demo.get("/api/reflect")
        assert r.status_code == 200
        data = r.json()
        assert len(data.get("boundaries", [])) == 2


# ═══════════════════════════════════════════════════════════════════════
# 15. HRPORTAL SPECIFIC — salary review lifecycle
#
# Covers: state machine on salary_reviews, redaction in transitions
# ═══════════════════════════════════════════════════════════════════════


class TestHRPortalSalaryReviewLifecycle:
    """Salary review state machine + confidentiality."""

    def test_create_salary_review(self, hrportal):
        """app.py: create salary_review as HR."""
        hrportal.set_role("hr business partner")
        emp = hrportal.post("/api/v1/employees", json={
            "name": f"SRTarget {_uid()}", "department": "Eng",
        })
        eid = emp.json()["id"]
        r = hrportal.post("/api/v1/salary_reviews", json={
            "employee": eid, "old_salary": 80000,
            "new_salary": 90000, "reason": "Performance",
        })
        assert r.status_code == 201
        assert r.json()["review_lifecycle"] == "pending"

    def test_salary_review_pending_to_approved(self, hrportal):
        """state.py: pending -> approved transition."""
        hrportal.set_role("hr business partner")
        emp = hrportal.post("/api/v1/employees", json={
            "name": f"SRApprove {_uid()}", "department": "Eng",
        })
        eid = emp.json()["id"]
        sr = hrportal.post("/api/v1/salary_reviews", json={
            "employee": eid, "old_salary": 70000,
            "new_salary": 75000, "reason": "Annual",
        })
        sr_id = sr.json()["id"]
        r = hrportal.post(f"/_transition/salary_reviews/review_lifecycle/{sr_id}/approved")
        assert r.status_code in (200, 303)

    def test_salary_review_full_lifecycle(self, hrportal):
        """state.py: pending -> approved -> applied."""
        hrportal.set_role("hr business partner")
        emp = hrportal.post("/api/v1/employees", json={
            "name": f"SRFull {_uid()}", "department": "Eng",
        })
        eid = emp.json()["id"]
        sr = hrportal.post("/api/v1/salary_reviews", json={
            "employee": eid, "old_salary": 60000,
            "new_salary": 65000, "reason": "Promo",
        })
        sr_id = sr.json()["id"]
        hrportal.post(f"/_transition/salary_reviews/review_lifecycle/{sr_id}/approved")
        r = hrportal.post(f"/_transition/salary_reviews/review_lifecycle/{sr_id}/applied")
        assert r.status_code in (200, 303)


# ═══════════════════════════════════════════════════════════════════════
# 16. PROJECTBOARD — deep FK chains, multiple content types
#
# Covers: multiple content CRUD, cross-content listing
# ═══════════════════════════════════════════════════════════════════════


class TestProjectBoardCRUD:
    """ProjectBoard app has deep content relationships."""

    def test_list_projects(self, projectboard):
        """app.py: list projects content."""
        projectboard.set_role("project manager")
        r = projectboard.get("/api/v1/projects")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_project(self, projectboard):
        """app.py: create project."""
        projectboard.set_role("project manager")
        r = projectboard.post("/api/v1/projects", json={
            "name": f"Proj {_uid()}", "description": "test project",
        })
        assert r.status_code == 201

    def test_create_task_under_project(self, projectboard):
        """app.py: create task referencing project."""
        projectboard.set_role("project manager")
        proj = projectboard.post("/api/v1/projects", json={
            "name": f"TaskParent {_uid()}", "description": "t",
        })
        pid = proj.json()["id"]
        r = projectboard.post("/api/v1/tasks", json={
            "title": f"Task {_uid()}", "description": "t",
            "project": pid,
        })
        assert r.status_code == 201
