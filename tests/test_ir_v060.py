"""IR introspection tests for v0.6.0 features.

Tests the IR structure for:
- D-18: Audit levels (actions/debug/none)
- D-19: Dependent field values and one_of constraints
- Block C: Boundary declarations
- G2: Before/After (postconditions exist in IR)
"""

import json
import pytest
from pathlib import Path


# ── Helpers ──

def _get_content(ir, snake_name):
    matches = [c for c in ir.get("content", [])
               if c["name"]["snake"] == snake_name]
    assert len(matches) == 1, f"Expected 1 content '{snake_name}', found {len(matches)}"
    return matches[0]


def _get_compute(ir, snake_name):
    matches = [c for c in ir.get("computes", [])
               if c["name"]["snake"] == snake_name]
    assert len(matches) == 1, f"Expected 1 compute '{snake_name}', found {len(matches)}"
    return matches[0]


def _get_boundary(ir, snake_name):
    matches = [b for b in ir.get("boundaries", [])
               if b["name"]["snake"] == snake_name]
    assert len(matches) == 1, f"Expected 1 boundary '{snake_name}', found {len(matches)}"
    return matches[0]


def _get_field(content, field_name):
    matches = [f for f in content.get("fields", [])
               if f["name"] == field_name]
    assert len(matches) == 1, f"Expected 1 field '{field_name}', found {len(matches)}"
    return matches[0]


# ── D-18: Audit levels ──

class TestAuditLevels:
    """Every ContentSchema must have an 'audit' field with a valid level."""

    VALID_LEVELS = {"actions", "debug", "none"}

    def test_audit_field_present_on_all_content(self, compute_demo_ir):
        """All Content types must declare an audit level."""
        for content in compute_demo_ir.get("content", []):
            assert "audit" in content, (
                f"Content '{content['name']['snake']}' missing 'audit' field"
            )

    def test_audit_field_valid_values(self, compute_demo_ir):
        """Audit level must be one of: actions, debug, none."""
        for content in compute_demo_ir.get("content", []):
            level = content["audit"]
            assert level in self.VALID_LEVELS, (
                f"Content '{content['name']['snake']}' has invalid audit "
                f"level '{level}'. Must be one of: {self.VALID_LEVELS}"
            )

    def test_default_audit_is_actions(self, warehouse_ir):
        """Default audit level should be 'actions' (pit of success)."""
        for content in warehouse_ir.get("content", []):
            assert content.get("audit") == "actions", (
                f"Content '{content['name']['snake']}' default audit "
                f"should be 'actions', got '{content.get('audit')}'"
            )

    @pytest.mark.parametrize("fixture_name", [
        "warehouse_ir", "helpdesk_ir", "projectboard_ir",
        "hello_user_ir", "hrportal_ir",
    ])
    def test_audit_present_across_all_apps(self, fixture_name, request):
        """All apps should have audit levels on all content types."""
        ir = request.getfixturevalue(fixture_name)
        for content in ir.get("content", []):
            assert "audit" in content, (
                f"[{fixture_name}] Content '{content['name']['snake']}' "
                f"missing 'audit' field"
            )
            assert content["audit"] in self.VALID_LEVELS


# ── Block C: Boundaries ──

class TestBoundaryIR:
    """Boundary declarations in IR structure."""

    def test_boundaries_array_exists(self, compute_demo_ir):
        """IR must have a 'boundaries' top-level array."""
        assert "boundaries" in compute_demo_ir
        assert isinstance(compute_demo_ir["boundaries"], list)

    def test_boundary_has_required_fields(self, compute_demo_ir):
        """Each boundary must have name, contains_content, identity_mode."""
        for bnd in compute_demo_ir["boundaries"]:
            assert "name" in bnd
            assert "display" in bnd["name"]
            assert "snake" in bnd["name"]
            assert "contains_content" in bnd
            assert isinstance(bnd["contains_content"], list)
            assert "identity_mode" in bnd

    def test_compute_demo_has_two_boundaries(self, compute_demo_ir):
        """compute_demo declares two boundaries."""
        assert len(compute_demo_ir["boundaries"]) == 2

    def test_order_processing_boundary(self, compute_demo_ir):
        bnd = _get_boundary(compute_demo_ir, "order_processing")
        assert "orders" in bnd["contains_content"]
        assert "order_lines" in bnd["contains_content"]
        assert bnd["identity_mode"] == "inherit"

    def test_order_reporting_boundary(self, compute_demo_ir):
        bnd = _get_boundary(compute_demo_ir, "order_reporting")
        assert "reports" in bnd["contains_content"]
        assert bnd["identity_mode"] == "restrict"

    def test_content_not_in_multiple_boundaries(self, compute_demo_ir):
        """No content type should appear in more than one boundary."""
        seen = {}
        for bnd in compute_demo_ir["boundaries"]:
            for ct in bnd["contains_content"]:
                assert ct not in seen, (
                    f"Content '{ct}' in both '{seen[ct]}' and "
                    f"'{bnd['name']['snake']}'"
                )
                seen[ct] = bnd["name"]["snake"]

    def test_boundary_properties(self, compute_demo_ir):
        """Boundaries can expose typed properties."""
        for bnd in compute_demo_ir["boundaries"]:
            assert "properties" in bnd
            assert isinstance(bnd["properties"], list)

    def test_apps_without_boundaries_have_empty_array(self, warehouse_ir):
        """Apps that don't declare boundaries should have an empty array."""
        boundaries = warehouse_ir.get("boundaries", [])
        assert isinstance(boundaries, list)
        assert len(boundaries) == 0


# ── D-19: Dependent values and one_of ──

class TestDependentValuesIR:
    """Dependent values and field-level one_of constraints in IR."""

    def test_one_of_values_on_field_spec(self, compute_demo_ir):
        """FieldSpec should have 'one_of_values' array (may be empty)."""
        for content in compute_demo_ir.get("content", []):
            for field in content.get("fields", []):
                assert "one_of_values" in field, (
                    f"Field '{field['name']}' in '{content['name']['snake']}' "
                    f"missing 'one_of_values'"
                )
                assert isinstance(field["one_of_values"], list)

    @pytest.mark.parametrize("fixture_name", [
        "warehouse_ir", "helpdesk_ir", "hello_user_ir",
    ])
    def test_one_of_values_present_across_apps(self, fixture_name, request):
        """All apps should have one_of_values on field specs."""
        ir = request.getfixturevalue(fixture_name)
        for content in ir.get("content", []):
            for field in content.get("fields", []):
                assert "one_of_values" in field, (
                    f"[{fixture_name}] Field '{field['name']}' missing 'one_of_values'"
                )

    def test_dependent_values_array_on_content(self, compute_demo_ir):
        """ContentSchema should have 'dependent_values' array (may be empty)."""
        for content in compute_demo_ir.get("content", []):
            # dependent_values may not be present on all content types
            # but if present, must be a list
            dv = content.get("dependent_values", [])
            assert isinstance(dv, list)


# ── G2: Postconditions ──

class TestPostconditionsIR:
    """Computes can declare preconditions and postconditions."""

    def test_postconditions_field_exists(self, agent_simple_ir):
        """All Computes should have a postconditions field."""
        for compute in agent_simple_ir.get("computes", []):
            assert "postconditions" in compute
            assert isinstance(compute["postconditions"], list)

    def test_preconditions_field_exists(self, agent_simple_ir):
        """All Computes should have a preconditions field."""
        for compute in agent_simple_ir.get("computes", []):
            assert "preconditions" in compute
            assert isinstance(compute["preconditions"], list)


# ── Cross-cutting: all IR fixtures pass basic schema checks ──

class TestAllFixturesV060:
    """Verify all fixture IRs have v0.6 fields."""

    ALL_FIXTURES = [
        "warehouse_ir", "helpdesk_ir", "projectboard_ir",
        "hello_user_ir", "hrportal_ir", "compute_demo_ir",
        "agent_simple_ir", "agent_chatbot_ir",
        "channel_simple_ir", "channel_demo_ir",
        "security_agent_ir",
    ]

    @pytest.mark.parametrize("fixture_name", ALL_FIXTURES)
    def test_boundaries_array_present(self, fixture_name, request):
        ir = request.getfixturevalue(fixture_name)
        assert "boundaries" in ir
        assert isinstance(ir["boundaries"], list)

    @pytest.mark.parametrize("fixture_name", ALL_FIXTURES)
    def test_audit_on_all_content(self, fixture_name, request):
        ir = request.getfixturevalue(fixture_name)
        for ct in ir.get("content", []):
            assert "audit" in ct, (
                f"[{fixture_name}] Content '{ct['name']['snake']}' missing audit"
            )

    @pytest.mark.parametrize("fixture_name", ALL_FIXTURES)
    def test_one_of_values_on_all_fields(self, fixture_name, request):
        ir = request.getfixturevalue(fixture_name)
        for ct in ir.get("content", []):
            for f in ct.get("fields", []):
                assert "one_of_values" in f, (
                    f"[{fixture_name}] Field '{f['name']}' missing one_of_values"
                )


# ═══════════════════════════════════════════════════════════════
# TRANSITION FEEDBACK (Issue #006)
# ═══════════════════════════════════════════════════════════════


class TestTransitionFeedback:
    """Test that transition feedback (toast/banner) appears correctly in the IR."""

    def test_warehouse_activate_has_feedback(self, warehouse_ir):
        """Warehouse draft→active should have success toast + error banner."""
        sm = [s for s in warehouse_ir["state_machines"]
              if s["machine_name"] == "product lifecycle"][0]
        t = [t for t in sm["transitions"]
             if t["from_state"] == "draft" and t["to_state"] == "active"][0]
        assert "feedback" in t
        assert len(t["feedback"]) == 2
        assert t["feedback"][0]["trigger"] == "success"
        assert t["feedback"][0]["style"] == "toast"
        assert t["feedback"][0]["is_expr"] is True
        assert t["feedback"][1]["trigger"] == "error"
        assert t["feedback"][1]["style"] == "banner"
        assert t["feedback"][1]["is_expr"] is False

    def test_helpdesk_resolve_has_banner_with_dismiss(self, helpdesk_ir):
        """Helpdesk in progress→resolved should have banner with 10s dismiss."""
        sm = [s for s in helpdesk_ir["state_machines"]
              if s["machine_name"] == "ticket lifecycle"][0]
        t = [t for t in sm["transitions"]
             if t["from_state"] == "in progress" and t["to_state"] == "resolved"][0]
        assert len(t["feedback"]) == 1
        fb = t["feedback"][0]
        assert fb["style"] == "banner"
        assert fb["dismiss_seconds"] == 10
        assert fb["is_expr"] is True

    def test_transitions_without_feedback_have_empty_array(self, compute_demo_ir):
        """Transitions without feedback should have feedback: []."""
        for sm in compute_demo_ir.get("state_machines", []):
            for t in sm["transitions"]:
                assert "feedback" in t
                assert isinstance(t["feedback"], list)

    @pytest.mark.parametrize("fixture_name", TestAllFixturesV060.ALL_FIXTURES)
    def test_feedback_field_present_on_all_transitions(self, fixture_name, request):
        """Every transition in every fixture must have a feedback field."""
        ir = request.getfixturevalue(fixture_name)
        for sm in ir.get("state_machines", []):
            for t in sm["transitions"]:
                assert "feedback" in t, (
                    f"[{fixture_name}] Transition {t['from_state']}→{t['to_state']} "
                    f"in '{sm['machine_name']}' missing feedback field"
                )
