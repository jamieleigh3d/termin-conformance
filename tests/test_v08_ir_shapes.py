"""Conformance — v0.8 IR structural shapes.

Every conforming runtime consumes the IR JSON produced by the Termin
compiler. v0.8 adds new component types and props that every runtime
must recognize (even if they emit different markup in response).

This file enumerates the v0.8 IR additions and asserts the published
IR schema accepts them. Runtimes that reject these shapes as invalid
IR are non-conforming.

v0.8 additions:
  - Component type "edit_modal" with props {content, singular}
  - action_button props: action in {"transition", "delete", "edit"}
    with corresponding required_scope and visible_when
  - field_input input_type="state" with all_states list
  - data_table props: inline_editable_fields (list), inline_edit_scope
"""

import json
from pathlib import Path

import pytest


SCHEMA_PATH = Path(__file__).parent.parent / "specs" / "termin-ir-schema.json"


@pytest.fixture(scope="module")
def schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


class TestComponentTypesAcceptV08Additions:
    def test_edit_modal_is_a_valid_component_type(self, schema):
        """The IR schema's component type enum must include edit_modal."""
        comp_def = schema["$defs"]["ComponentNode"]
        type_enum = comp_def["properties"]["type"]["enum"]
        assert "edit_modal" in type_enum, (
            "v0.8 added 'edit_modal' component type. "
            "Update specs/termin-ir-schema.json accordingly."
        )

    def test_known_component_types_preserved(self, schema):
        """Regression — v0.7 and earlier types must still be accepted."""
        comp_def = schema["$defs"]["ComponentNode"]
        type_enum = comp_def["properties"]["type"]["enum"]
        for expected in ("data_table", "form", "field_input",
                         "action_button", "chat", "section"):
            assert expected in type_enum


class TestFixtureIRMatchesV08Shape:
    """The warehouse fixture demonstrates every v0.8 addition.
    Conforming runtimes that can deploy the fixture successfully
    necessarily handle these shapes. Validate the fixture's IR
    contains the expected additions."""

    def test_warehouse_has_edit_modal_with_fields(self, warehouse_ir):
        modals = []
        for page in warehouse_ir.get("pages", []):
            for ch in page.get("children", []):
                if ch.get("type") == "edit_modal":
                    modals.append(ch)
        assert len(modals) >= 1, "warehouse fixture must have an edit_modal"
        modal = modals[0]
        # Props: content + singular
        assert modal["props"].get("content") == "products"
        assert "singular" in modal["props"]
        # Children: field_inputs
        field_inputs = [c for c in modal.get("children", [])
                        if c.get("type") == "field_input"]
        assert len(field_inputs) >= 2, \
            "Edit modal must render inputs for the editable fields"

    def test_warehouse_action_buttons_cover_all_three_kinds(self, warehouse_ir):
        """The warehouse fixture shows all three action button kinds:
        transition (Activate, Discontinue), edit (Edit), delete (Delete)."""
        kinds_seen = set()
        for page in warehouse_ir.get("pages", []):
            for ch in page.get("children", []):
                if ch.get("type") != "data_table":
                    continue
                for btn in ch.get("props", {}).get("row_actions", []):
                    kinds_seen.add(btn.get("props", {}).get("action"))
        assert "transition" in kinds_seen
        assert "delete" in kinds_seen
        assert "edit" in kinds_seen

    def test_warehouse_inline_editable_fields_declared(self, warehouse_ir):
        for page in warehouse_ir.get("pages", []):
            for ch in page.get("children", []):
                if ch.get("type") != "data_table":
                    continue
                fields = ch.get("props", {}).get("inline_editable_fields")
                if fields:
                    assert isinstance(fields, list)
                    assert all(isinstance(f, str) for f in fields)
                    assert ch["props"].get("inline_edit_scope"), \
                        "inline_editable_fields implies inline_edit_scope"
                    return
        pytest.fail("No inline_editable_fields found in warehouse fixture")

    def test_edit_modal_includes_state_field_input_with_all_states(
            self, warehouse_ir):
        """The edit modal for a content with a state machine must
        include a field_input of input_type='state' with an all_states
        list populated from the state machine."""
        for page in warehouse_ir.get("pages", []):
            for ch in page.get("children", []):
                if ch.get("type") != "edit_modal":
                    continue
                for fi in ch.get("children", []):
                    if fi.get("props", {}).get("input_type") == "state":
                        states = fi["props"].get("all_states") or []
                        assert isinstance(states, list)
                        assert len(states) >= 2, \
                            "State field must have at least two states"
                        # warehouse has draft, active, discontinued
                        for expected in ("draft", "active", "discontinued"):
                            assert expected in states, \
                                f"Expected state {expected} in {states}"
                        return
        pytest.fail("No state field_input found in warehouse edit modal")
