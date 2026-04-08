"""Tier 2: IR-Driven Presentation Contract Tests.

These tests walk the IR's component tree and verify that every declared
component, column, field, and filter appears in the rendered HTML.

The bridge between the IR and the rendered output is the data-termin-*
attribute contract:
  - data-termin-component: component type (data_table, form, etc.)
  - data-termin-source: Content name the component displays
  - data-termin-field: field name within a row or form
  - data-termin-row-id: record ID for a table row
  - data-termin-target: Content name a form submits to

Tests derive expectations entirely from the IR fixtures — no hardcoded
knowledge of what pages should contain.
"""

import json
import re
import uuid
import pytest
from pathlib import Path


def _uid():
    return uuid.uuid4().hex[:8]


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _get_pages_for_role(ir, role):
    """Get all pages in the IR that match a given role."""
    return [p for p in ir.get("pages", []) if p["role"].lower() == role.lower()]


def _walk_components(children, type_filter=None):
    """Recursively walk a component tree, optionally filtering by type."""
    results = []
    for child in (children or []):
        if type_filter is None or child.get("type") == type_filter:
            results.append(child)
        results.extend(_walk_components(child.get("children", []), type_filter))
        # Also check row_actions (action buttons inside data_table props)
        for action in child.get("props", {}).get("row_actions", []):
            if type_filter is None or action.get("type") == type_filter:
                results.append(action)
    return results


def _get_page_html(session, slug, role):
    """Fetch a page's HTML as a specific role."""
    session.set_role(role)
    r = session.get(f"/{slug}")
    assert r.status_code == 200, f"Page /{slug} returned {r.status_code} for role {role}"
    return r.text


# ═══════════════════════════════════════════════════════════════════════
# DATA TABLE CONTRACT
# ═══════════════════════════════════════════════════════════════════════

class TestDataTableContract:
    """Every data_table in the IR must appear in the rendered HTML
    with its declared source and columns."""

    def test_warehouse_data_table_source_annotated(self, warehouse, warehouse_ir):
        """data_table must have data-termin-component and data-termin-source."""
        for page in warehouse_ir["pages"]:
            tables = _walk_components(page["children"], "data_table")
            if not tables:
                continue
            html = _get_page_html(warehouse, page["slug"], page["role"])
            for table in tables:
                source = table["props"].get("source", "")
                assert f'data-termin-source="{source}"' in html, \
                    f"Page {page['slug']}: data_table source '{source}' not annotated in HTML"

    def test_helpdesk_data_table_source_annotated(self, helpdesk, helpdesk_ir):
        for page in helpdesk_ir["pages"]:
            tables = _walk_components(page["children"], "data_table")
            if not tables:
                continue
            html = _get_page_html(helpdesk, page["slug"], page["role"])
            for table in tables:
                source = table["props"].get("source", "")
                assert f'data-termin-source="{source}"' in html, \
                    f"Page {page['slug']}: data_table source '{source}' not annotated"

    def test_data_table_columns_present(self, warehouse, warehouse_ir):
        """Every declared column must appear in the HTML (as header or field attribute)."""
        for page in warehouse_ir["pages"]:
            tables = _walk_components(page["children"], "data_table")
            if not tables:
                continue
            html = _get_page_html(warehouse, page["slug"], page["role"])
            for table in tables:
                for col in table["props"].get("columns", []):
                    field = col.get("field", "")
                    label = col.get("label", "")
                    assert field in html or label in html, \
                        f"Page {page['slug']}: column '{field}'/'{label}' missing from HTML"

    def test_helpdesk_data_table_columns_present(self, helpdesk, helpdesk_ir):
        for page in helpdesk_ir["pages"]:
            tables = _walk_components(page["children"], "data_table")
            if not tables:
                continue
            html = _get_page_html(helpdesk, page["slug"], page["role"])
            for table in tables:
                for col in table["props"].get("columns", []):
                    field = col.get("field", "")
                    label = col.get("label", "")
                    assert field in html or label in html, \
                        f"Page {page['slug']}: column '{field}'/'{label}' missing"

    def test_data_table_has_component_annotation(self, warehouse, warehouse_ir):
        """data_table must be annotated with data-termin-component."""
        for page in warehouse_ir["pages"]:
            tables = _walk_components(page["children"], "data_table")
            if not tables:
                continue
            html = _get_page_html(warehouse, page["slug"], page["role"])
            assert 'data-termin-component="data_table"' in html, \
                f"Page {page['slug']}: data_table missing component annotation"


# ═══════════════════════════════════════════════════════════════════════
# FORM CONTRACT
# ═══════════════════════════════════════════════════════════════════════

class TestFormContract:
    """Every form in the IR must render with its declared field inputs."""

    def test_form_has_target_annotation(self, warehouse, warehouse_ir):
        """Forms must be annotated with data-termin-target or data-termin-component."""
        for page in warehouse_ir["pages"]:
            forms = _walk_components(page["children"], "form")
            if not forms:
                continue
            html = _get_page_html(warehouse, page["slug"], page["role"])
            for form in forms:
                target = form["props"].get("target", "")
                assert '<form' in html, \
                    f"Page {page['slug']}: form element missing"
                # Form should reference its target Content
                assert target in html, \
                    f"Page {page['slug']}: form target '{target}' not in HTML"

    def test_form_field_inputs_present(self, warehouse, warehouse_ir):
        """Every field_input declared in a form must have a corresponding input element."""
        for page in warehouse_ir["pages"]:
            forms = _walk_components(page["children"], "form")
            if not forms:
                continue
            html = _get_page_html(warehouse, page["slug"], page["role"])
            for form in forms:
                field_inputs = _walk_components(form.get("children", []), "field_input")
                for fi in field_inputs:
                    field_name = fi["props"].get("field", "")
                    # The HTML should have an input with name="field_name"
                    assert f'name="{field_name}"' in html, \
                        f"Page {page['slug']}: field_input '{field_name}' has no matching input element"

    def test_helpdesk_form_field_inputs_present(self, helpdesk, helpdesk_ir):
        for page in helpdesk_ir["pages"]:
            forms = _walk_components(page["children"], "form")
            if not forms:
                continue
            html = _get_page_html(helpdesk, page["slug"], page["role"])
            for form in forms:
                field_inputs = _walk_components(form.get("children", []), "field_input")
                for fi in field_inputs:
                    field_name = fi["props"].get("field", "")
                    assert f'name="{field_name}"' in html, \
                        f"Page {page['slug']}: field_input '{field_name}' missing"

    def test_required_field_inputs_have_required_attribute(self, helpdesk, helpdesk_ir):
        """field_inputs with required=true must render with the HTML required attribute."""
        for page in helpdesk_ir["pages"]:
            forms = _walk_components(page["children"], "form")
            if not forms:
                continue
            html = _get_page_html(helpdesk, page["slug"], page["role"])
            for form in forms:
                field_inputs = _walk_components(form.get("children", []), "field_input")
                for fi in field_inputs:
                    if fi["props"].get("required"):
                        field_name = fi["props"].get("field", "")
                        # Find the input and check for required attribute
                        # Look for name="field" ... required pattern
                        pattern = f'name="{field_name}"[^>]*required'
                        assert re.search(pattern, html), \
                            f"Page {page['slug']}: required field '{field_name}' missing required attribute"

    def test_enum_field_renders_as_select(self, warehouse, warehouse_ir):
        """field_inputs with input_type=enum should render as <select> with options."""
        for page in warehouse_ir["pages"]:
            forms = _walk_components(page["children"], "form")
            if not forms:
                continue
            html = _get_page_html(warehouse, page["slug"], page["role"])
            for form in forms:
                field_inputs = _walk_components(form.get("children", []), "field_input")
                for fi in field_inputs:
                    if fi["props"].get("input_type") == "enum":
                        field_name = fi["props"].get("field", "")
                        assert f'<select' in html and f'name="{field_name}"' in html, \
                            f"Page {page['slug']}: enum field '{field_name}' should be a <select>"
                        # Check that enum values appear as options
                        for val in fi["props"].get("enum_values", []):
                            assert val in html, \
                                f"Page {page['slug']}: enum option '{val}' missing for field '{field_name}'"


# ═══════════════════════════════════════════════════════════════════════
# FILTER CONTRACT
# ═══════════════════════════════════════════════════════════════════════

class TestFilterContract:
    """Every filter declared as a data_table child must render a filter control."""

    def test_filters_present_for_data_table(self, warehouse, warehouse_ir):
        """Each filter in the IR should produce a filter control in the HTML."""
        for page in warehouse_ir["pages"]:
            tables = _walk_components(page["children"], "data_table")
            if not tables:
                continue
            html = _get_page_html(warehouse, page["slug"], page["role"])
            for table in tables:
                filters = _walk_components(table.get("children", []), "filter")
                for filt in filters:
                    field = filt["props"].get("field", "")
                    assert f'data-filter="{field}"' in html or f'name="{field}"' in html, \
                        f"Page {page['slug']}: filter for '{field}' missing from HTML"

    def test_helpdesk_filters_present(self, helpdesk, helpdesk_ir):
        for page in helpdesk_ir["pages"]:
            tables = _walk_components(page["children"], "data_table")
            if not tables:
                continue
            html = _get_page_html(helpdesk, page["slug"], page["role"])
            for table in tables:
                filters = _walk_components(table.get("children", []), "filter")
                for filt in filters:
                    field = filt["props"].get("field", "")
                    assert f'data-filter="{field}"' in html or f'name="{field}"' in html, \
                        f"Page {page['slug']}: filter for '{field}' missing"

    def test_enum_filter_has_declared_options(self, warehouse, warehouse_ir):
        """Enum/state filters should render their declared option values."""
        for page in warehouse_ir["pages"]:
            tables = _walk_components(page["children"], "data_table")
            if not tables:
                continue
            html = _get_page_html(warehouse, page["slug"], page["role"])
            for table in tables:
                filters = _walk_components(table.get("children", []), "filter")
                for filt in filters:
                    options = filt["props"].get("options", [])
                    for opt in options:
                        assert opt in html, \
                            f"Page {page['slug']}: filter option '{opt}' missing"


# ═══════════════════════════════════════════════════════════════════════
# SEARCH CONTRACT
# ═══════════════════════════════════════════════════════════════════════

class TestSearchContract:
    """Search components must render a search input referencing their fields."""

    def test_search_present_when_declared(self, warehouse, warehouse_ir):
        for page in warehouse_ir["pages"]:
            tables = _walk_components(page["children"], "data_table")
            if not tables:
                continue
            html = _get_page_html(warehouse, page["slug"], page["role"])
            for table in tables:
                searches = _walk_components(table.get("children", []), "search")
                for search in searches:
                    fields = search["props"].get("fields", [])
                    # The search input should reference its fields somehow
                    assert 'data-search' in html or 'Search by' in html, \
                        f"Page {page['slug']}: search component missing"
                    # At least one search field should appear
                    for field in fields:
                        assert field in html, \
                            f"Page {page['slug']}: search field '{field}' not in HTML"


# ═══════════════════════════════════════════════════════════════════════
# ACTION BUTTON CONTRACT
# ═══════════════════════════════════════════════════════════════════════

class TestActionButtonContract:
    """Action buttons must render with correct labels and state awareness."""

    def test_action_buttons_labeled(self, warehouse, warehouse_ir):
        """Every row_action button's label must appear in the HTML."""
        for page in warehouse_ir["pages"]:
            tables = _walk_components(page["children"], "data_table")
            if not tables:
                continue
            # Need data in the table for buttons to render
            warehouse.set_role("warehouse manager")
            warehouse.post("/api/v1/products", json={
                "sku": _uid(), "name": "Btn Label Test", "category": "raw material",
            })
            html = _get_page_html(warehouse, page["slug"], page["role"])
            for table in tables:
                for action in table["props"].get("row_actions", []):
                    label = action["props"].get("label", "")
                    if label:
                        # Button label should appear either as enabled or disabled
                        assert label in html, \
                            f"Page {page['slug']}: action button '{label}' not in HTML"

    def test_disabled_buttons_when_unauthorized(self, warehouse, warehouse_ir):
        """Action buttons should be disabled when the user lacks the required scope."""
        # Create a product so buttons render
        warehouse.set_role("warehouse manager")
        warehouse.post("/api/v1/products", json={
            "sku": _uid(), "name": "Auth Btn Test", "category": "raw material",
        })
        # View as executive (read-only scope)
        warehouse.set_role("executive")
        for page in warehouse_ir["pages"]:
            tables = _walk_components(page["children"], "data_table")
            if not tables:
                continue
            for table in tables:
                if not table["props"].get("row_actions"):
                    continue
                html = _get_page_html(warehouse, page["slug"], page["role"])
                # All buttons should be disabled for executive
                assert "disabled" in html, \
                    f"Page {page['slug']}: buttons should be disabled for unauthorized role"


# ═══════════════════════════════════════════════════════════════════════
# AGGREGATION & SECTION CONTRACT
# ═══════════════════════════════════════════════════════════════════════

class TestAggregationContract:
    """Aggregation and stat_breakdown components must render."""

    def test_aggregation_annotated(self, projectboard, projectboard_ir):
        """Aggregation components should have data-termin-component annotation."""
        for page in projectboard_ir["pages"]:
            aggs = _walk_components(page["children"], "aggregation")
            aggs += _walk_components(page["children"], "stat_breakdown")
            if not aggs:
                continue
            html = _get_page_html(projectboard, page["slug"], page["role"])
            assert 'data-termin-component' in html, \
                f"Page {page['slug']}: aggregation components should be annotated"


class TestSectionContract:
    """Section components must render their titles."""

    def test_section_titles_rendered(self, projectboard, projectboard_ir):
        """Every section with a title should render that title as a heading."""
        for page in projectboard_ir["pages"]:
            sections = _walk_components(page["children"], "section")
            if not sections:
                continue
            html = _get_page_html(projectboard, page["slug"], page["role"])
            for section in sections:
                title = section["props"].get("title", "")
                if title:
                    assert title in html, \
                        f"Page {page['slug']}: section title '{title}' not rendered"


# ═══════════════════════════════════════════════════════════════════════
# SUBSCRIBE CONTRACT
# ═══════════════════════════════════════════════════════════════════════

class TestSubscribeContract:
    """Subscribe components should be indicated in the rendered output."""

    def test_subscribe_content_referenced(self, warehouse, warehouse_ir):
        """Pages with subscribe components should reference termin.js or equivalent."""
        for page in warehouse_ir["pages"]:
            subs = _walk_components(page["children"], "subscribe")
            if not subs:
                continue
            html = _get_page_html(warehouse, page["slug"], page["role"])
            # The page should load a client runtime for real-time updates
            assert "termin" in html.lower() or "ws" in html.lower() or "websocket" in html.lower(), \
                f"Page {page['slug']}: subscribe declared but no client runtime reference"


# ═══════════════════════════════════════════════════════════════════════
# ALL PAGES RENDER
# ═══════════════════════════════════════════════════════════════════════

class TestAllPagesRender:
    """Every page declared in the IR must render for its designated role."""

    def test_all_warehouse_pages_render(self, warehouse, warehouse_ir):
        for page in warehouse_ir["pages"]:
            html = _get_page_html(warehouse, page["slug"], page["role"])
            assert "<!DOCTYPE html>" in html or "<html" in html, \
                f"Page {page['slug']} did not return valid HTML"

    def test_all_helpdesk_pages_render(self, helpdesk, helpdesk_ir):
        for page in helpdesk_ir["pages"]:
            html = _get_page_html(helpdesk, page["slug"], page["role"])
            assert "<!DOCTYPE html>" in html or "<html" in html, \
                f"Page {page['slug']} did not return valid HTML"

    def test_all_projectboard_pages_render(self, projectboard, projectboard_ir):
        for page in projectboard_ir["pages"]:
            html = _get_page_html(projectboard, page["slug"], page["role"])
            assert "<!DOCTYPE html>" in html or "<html" in html, \
                f"Page {page['slug']} did not return valid HTML"

    def test_page_title_matches_ir(self, warehouse, warehouse_ir):
        """The page title from the IR should appear in the rendered HTML."""
        for page in warehouse_ir["pages"]:
            html = _get_page_html(warehouse, page["slug"], page["role"])
            assert page["name"] in html, \
                f"Page title '{page['name']}' not found in rendered HTML"
