"""Conformance — v0.8 row action primitives: Delete, Edit, Inline edit.

DSL forms (inside a "For each X, show actions:" block):

  "Delete" deletes if available, hide otherwise
  "Edit"   edits   if available, hide otherwise
  Allow inline editing of <field>, <field>

Plus supporting DSL (outside the actions block):
  Anyone with "<scope>" can delete <content>   # required for Delete
  Anyone with "<scope>" can update <content>   # required for Edit + Inline

This test file validates the full conformance contract each runtime
must satisfy:

  1. IR shape — action_button components carry action="delete"/"edit",
     inline-editable data_tables carry inline_editable_fields +
     inline_edit_scope.
  2. Rendered HTML markup — scoped data-termin-* attributes enable
     DOM-level behavioral testing without English-string matching.
  3. Server-side route behavior — DELETE /api/v1/{content}/{id} is
     scope-gated; PUT /api/v1/{content}/{id} is also scope-gated
     (defense in depth — hiding the button is not the only defense).
  4. Semantics — 409 on FK-violation, 403 on missing scope, 200 on
     success.

Uses the warehouse fixture. warehouse.termin declares:
  Anyone with "inventory.admin" can delete products
  Anyone with "inventory.write" can update products
  "Edit" edits if available, hide otherwise
  "Delete" deletes if available, hide otherwise
  Allow inline editing of name, description
"""

import uuid
import pytest


def _sku(prefix="TST"):
    return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"


def _create_product(warehouse, **overrides):
    """Seed a product as the manager (has all scopes)."""
    warehouse.set_role("warehouse manager")
    body = {
        "sku": _sku(),
        "name": "Conformance test product",
        "category": "raw material",
        "unit_cost": 1.0,
    }
    body.update(overrides)
    r = warehouse.post("/api/v1/products", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── IR shape — structural (runtime-agnostic via reflection) ─────────

class TestActionButtonIRShape:
    """Check the IR carries the expected component types. This is a
    structural check on the published IR contract; any runtime that
    reads the IR must recognize these shapes."""

    def test_warehouse_ir_has_delete_action_button(self, warehouse_ir):
        found = False
        for page in warehouse_ir.get("pages", []):
            for ch in page.get("children", []):
                if ch.get("type") != "data_table":
                    continue
                for btn in ch.get("props", {}).get("row_actions", []):
                    if btn.get("props", {}).get("action") == "delete":
                        assert btn["props"].get("required_scope"), \
                            "Delete button must carry required_scope from `can delete` rule"
                        found = True
        assert found, "No delete action_button found in warehouse IR"

    def test_warehouse_ir_has_edit_action_button(self, warehouse_ir):
        found = False
        for page in warehouse_ir.get("pages", []):
            for ch in page.get("children", []):
                if ch.get("type") != "data_table":
                    continue
                for btn in ch.get("props", {}).get("row_actions", []):
                    if btn.get("props", {}).get("action") == "edit":
                        assert btn["props"].get("required_scope"), \
                            "Edit button must carry required_scope from `can update` rule"
                        found = True
        assert found, "No edit action_button found in warehouse IR"

    def test_warehouse_ir_has_edit_modal_component(self, warehouse_ir):
        found = False
        for page in warehouse_ir.get("pages", []):
            for ch in page.get("children", []):
                if ch.get("type") == "edit_modal":
                    assert ch.get("props", {}).get("content"), \
                        "edit_modal must have a content prop"
                    found = True
        assert found, "No edit_modal component found in warehouse IR"

    def test_warehouse_ir_has_inline_editable_fields(self, warehouse_ir):
        found = False
        for page in warehouse_ir.get("pages", []):
            for ch in page.get("children", []):
                if ch.get("type") != "data_table":
                    continue
                fields = ch.get("props", {}).get("inline_editable_fields") or []
                if fields:
                    assert ch["props"].get("inline_edit_scope"), \
                        "data_table with inline_editable_fields must carry inline_edit_scope"
                    found = True
        assert found, "No inline-editable fields found in warehouse IR"


# ── Rendered HTML — automation markers (DOM-level behavioral) ───────

class TestRenderedMarkupContract:
    """The runtime's rendered pages must carry data-termin-* attributes
    that behavioral test tooling (Playwright, Cypress, programmatic
    HTML scraping) can target without depending on English strings.

    This is the HTML-level behavioral contract for row actions.
    """

    def test_manager_page_carries_edit_markers(self, warehouse):
        _create_product(warehouse)
        warehouse.set_role("warehouse manager")
        r = warehouse.get("/inventory_dashboard")
        assert r.status_code == 200
        assert "data-termin-edit" in r.text, "Edit marker missing from rendered page"
        assert "data-termin-edit-modal" in r.text, "Edit modal markup missing"

    def test_manager_page_carries_delete_markers(self, warehouse):
        _create_product(warehouse)
        warehouse.set_role("warehouse manager")
        r = warehouse.get("/inventory_dashboard")
        assert r.status_code == 200
        assert "data-termin-delete" in r.text, "Delete marker missing"

    def test_edit_modal_has_save_and_cancel_buttons(self, warehouse):
        warehouse.set_role("warehouse manager")
        r = warehouse.get("/inventory_dashboard")
        assert r.status_code == 200
        assert 'data-termin-action="save"' in r.text
        assert 'data-termin-action="cancel"' in r.text

    def test_edit_modal_has_field_inputs_for_schema_fields(self, warehouse):
        warehouse.set_role("warehouse manager")
        r = warehouse.get("/inventory_dashboard")
        # Every non-system field in products should render as a form input.
        for field in ("sku", "name", "category", "unit_cost"):
            assert f'data-termin-field="{field}"' in r.text, \
                f"Modal missing input for {field}"

    def test_inline_editable_cells_carry_marker(self, warehouse):
        _create_product(warehouse)
        warehouse.set_role("warehouse manager")
        r = warehouse.get("/inventory_dashboard")
        assert "data-termin-inline-editable" in r.text

    def test_non_editable_column_has_no_inline_marker(self, warehouse):
        """SKU is not declared inline-editable. Its cells must not carry
        the marker even for a user with update scope."""
        _create_product(warehouse)
        warehouse.set_role("warehouse manager")
        r = warehouse.get("/inventory_dashboard")
        import re
        assert re.search(
            r'data-termin-field="sku"[^>]*data-termin-inline-editable',
            r.text,
        ) is None, "SKU column should not be inline-editable"


# ── HTML visibility gated by scope ──────────────────────────────────

class TestScopeGatedVisibility:
    """hide-otherwise semantics — the Delete and Edit buttons must not
    render for users lacking the required scope. The marker <span>
    wrapper may still be present (for client-side re-evaluation on
    live updates), but the <button> element itself must not render."""

    def test_executive_does_not_see_delete_button(self, warehouse):
        _create_product(warehouse)
        warehouse.set_role("executive")
        r = warehouse.get("/inventory_dashboard")
        assert ">Delete</button>" not in r.text, \
            "Executive (no inventory.admin) must not see rendered Delete button"

    def test_executive_does_not_see_edit_button(self, warehouse):
        _create_product(warehouse)
        warehouse.set_role("executive")
        r = warehouse.get("/inventory_dashboard")
        assert ">Edit</button>" not in r.text


# ── Server-side route behavior — defense in depth ───────────────────

class TestDeleteRouteBehavior:
    def test_manager_can_delete_own_created_product(self, warehouse):
        pid = _create_product(warehouse)
        warehouse.set_role("warehouse manager")
        r = warehouse.delete(f"/api/v1/products/{pid}")
        assert r.status_code in (200, 204)
        r2 = warehouse.get(f"/api/v1/products/{pid}")
        assert r2.status_code == 404

    def test_executive_delete_rejected_with_403(self, warehouse):
        pid = _create_product(warehouse)
        warehouse.set_role("executive")
        r = warehouse.delete(f"/api/v1/products/{pid}")
        assert r.status_code == 403

    def test_delete_blocked_by_foreign_key_returns_409(self, warehouse):
        """Deleting a product that has stock_levels referencing it
        violates SQL RESTRICT. Must surface as 409, not 500."""
        pid = _create_product(warehouse)
        warehouse.set_role("warehouse manager")
        r_stock = warehouse.post("/api/v1/stock_levels", json={
            "product": pid, "warehouse": "Main",
            "quantity": 10, "reorder_threshold": 5,
        })
        assert r_stock.status_code == 201

        r = warehouse.delete(f"/api/v1/products/{pid}")
        assert r.status_code == 409, r.text
        body = r.json()
        # Message should explain the FK conflict in human English.
        assert "reference" in body.get("detail", "").lower()

        # Sanity: product still exists.
        r2 = warehouse.get(f"/api/v1/products/{pid}")
        assert r2.status_code == 200


class TestEditRouteBehavior:
    """The Edit modal ultimately fires PUT /api/v1/<content>/<id> for
    non-state field changes. This route must be scope-gated."""

    def test_manager_put_succeeds(self, warehouse):
        pid = _create_product(warehouse)
        warehouse.set_role("warehouse manager")
        r = warehouse.put(f"/api/v1/products/{pid}", json={"name": "Renamed"})
        assert r.status_code == 200
        r2 = warehouse.get(f"/api/v1/products/{pid}")
        assert r2.json()["name"] == "Renamed"

    def test_executive_put_rejected_with_403(self, warehouse):
        pid = _create_product(warehouse)
        warehouse.set_role("executive")
        r = warehouse.put(f"/api/v1/products/{pid}", json={"name": "Hacked"})
        assert r.status_code == 403


class TestInlineEditRouteBehavior:
    """Inline edit commits via a single-field PUT. Same scope gate
    as Edit — the inline cell rendering just wires the PUT."""

    def test_single_field_put_succeeds_for_manager(self, warehouse):
        pid = _create_product(warehouse)
        warehouse.set_role("warehouse manager")
        r = warehouse.put(f"/api/v1/products/{pid}",
                          json={"description": "inline updated"})
        assert r.status_code == 200
        r2 = warehouse.get(f"/api/v1/products/{pid}")
        assert r2.json().get("description") == "inline updated"

    def test_inline_put_rejected_for_executive(self, warehouse):
        pid = _create_product(warehouse)
        warehouse.set_role("executive")
        r = warehouse.put(f"/api/v1/products/{pid}",
                          json={"description": "hacked"})
        assert r.status_code == 403
