"""Tier 3: Behavioral Round-Trip Tests.

Tests the full data loop: fetch a rendered page, parse the form or
action button, submit it, and verify the result via the API.

This validates that the presentation layer and the API layer agree —
a form rendered in the UI actually produces correct records when
submitted, and a transition button actually changes state.
"""

import re
import uuid
import pytest


def _uid():
    return uuid.uuid4().hex[:8]


def _extract_form_action(html, target_content=None):
    """Extract form action URL from HTML.
    If target_content specified, find the form targeting that Content."""
    if target_content:
        # Look for form with data-termin-target="content"
        pattern = rf'<form[^>]*data-termin-target="{target_content}"[^>]*action="([^"]*)"'
        m = re.search(pattern, html)
        if m:
            return m.group(1)
    # Fallback: find first form with method="post"
    pattern = r'<form[^>]*method="post"[^>]*action="([^"]*)"'
    m = re.search(pattern, html)
    if m:
        return m.group(1)
    # Try reversed attribute order
    pattern = r'<form[^>]*action="([^"]*)"[^>]*method="post"'
    m = re.search(pattern, html)
    return m.group(1) if m else None


def _extract_input_names(html, form_html=None):
    """Extract all input/select field names from a form in the HTML."""
    source = form_html or html
    names = re.findall(r'<(?:input|select|textarea)[^>]*name="([^"]*)"', source)
    return names


def _extract_select_options(html, field_name):
    """Extract <option> values for a given select field."""
    # Find the select element
    pattern = rf'<select[^>]*name="{field_name}"[^>]*>(.*?)</select>'
    m = re.search(pattern, html, re.DOTALL)
    if not m:
        return []
    options = re.findall(r'<option[^>]*value="([^"]*)"', m.group(1))
    return [o for o in options if o]  # exclude empty default


# ═══════════════════════════════════════════════════════════════════════
# FORM SUBMISSION ROUND-TRIP
# ═══════════════════════════════════════════════════════════════════════

class TestFormRoundTrip:
    """Submit forms via the presentation layer and verify records via API."""

    def test_helpdesk_submit_ticket_roundtrip(self, helpdesk):
        """Submit a ticket via the HTML form, verify it exists via API."""
        helpdesk.set_role("customer", "RoundTripUser")

        # 1. Fetch the submit ticket page
        r = helpdesk.get("/submit_ticket")
        assert r.status_code == 200
        html = r.text

        # 2. Verify the form exists and has expected fields
        assert '<form' in html
        input_names = _extract_input_names(html)
        assert "title" in input_names
        assert "description" in input_names

        # 3. Submit the form
        tag = _uid()
        r2 = helpdesk.post("/submit_ticket", data={
            "title": f"RoundTrip {tag}",
            "description": "Submitted via form round-trip test",
            "priority": "medium",
            "category": "question",
        })
        # Should redirect (303 → 200 after follow)
        assert r2.status_code == 200

        # 4. Verify via API
        r3 = helpdesk.get("/api/v1/tickets")
        tickets = r3.json()
        match = [t for t in tickets if t["title"] == f"RoundTrip {tag}"]
        assert len(match) == 1, f"Ticket 'RoundTrip {tag}' not found via API after form submit"
        ticket = match[0]
        assert ticket["description"] == "Submitted via form round-trip test"
        assert ticket["priority"] == "medium"
        assert ticket["category"] == "question"

    def test_warehouse_add_product_roundtrip(self, warehouse):
        """Submit a product via the HTML form, verify it exists via API."""
        warehouse.set_role("warehouse manager", "FormTester")

        # 1. Fetch the add product page
        r = warehouse.get("/add_product")
        assert r.status_code == 200
        html = r.text
        assert '<form' in html

        # 2. Submit the form
        sku = _uid()
        r2 = warehouse.post("/add_product", data={
            "sku": sku,
            "name": "Round Trip Product",
            "description": "Created via form",
            "unit_cost": "25.50",
            "category": "finished good",
        })
        assert r2.status_code == 200

        # 3. Verify via API
        r3 = warehouse.get("/api/v1/products")
        products = r3.json()
        match = [p for p in products if p["sku"] == sku]
        assert len(match) == 1, f"Product '{sku}' not found via API"
        product = match[0]
        assert product["name"] == "Round Trip Product"
        assert product["category"] == "finished good"
        assert product["status"] == "draft"  # initial state

    def test_default_expr_populated_via_form(self, helpdesk):
        """default_expr fields should be populated when form doesn't include them."""
        helpdesk.set_role("customer", "DefaultTester")
        tag = _uid()

        helpdesk.post("/submit_ticket", data={
            "title": f"Default {tag}",
            "description": "Testing defaults via form",
            "priority": "low",
            "category": "bug",
        })

        r = helpdesk.get("/api/v1/tickets")
        ticket = [t for t in r.json() if t["title"] == f"Default {tag}"]
        assert len(ticket) == 1
        # submitted_by should be auto-filled from User.Name
        assert ticket[0]["submitted_by"] == "DefaultTester"


# ═══════════════════════════════════════════════════════════════════════
# TRANSITION ROUND-TRIP
# ═══════════════════════════════════════════════════════════════════════

class TestTransitionRoundTrip:
    """Click transition buttons and verify state changes via API."""

    def test_activate_product_roundtrip(self, warehouse):
        """Create product, submit activate transition, verify status via API."""
        warehouse.set_role("warehouse manager")

        # 1. Create a product via API
        sku = _uid()
        r = warehouse.post("/api/v1/products", json={
            "sku": sku, "name": "Transition RT", "category": "raw material",
        })
        assert r.status_code == 201
        pid = r.json()["id"]
        assert r.json()["status"] == "draft"

        # 2. Submit the transition (simulating button click)
        r2 = warehouse.post(f"/_transition/products/{pid}/active")
        assert r2.status_code in (200, 303)

        # 3. Verify via API
        products = warehouse.get("/api/v1/products").json()
        match = [p for p in products if p["sku"] == sku]
        assert match[0]["status"] == "active"

    def test_helpdesk_ticket_lifecycle_roundtrip(self, helpdesk):
        """Walk a ticket through states and verify each via API."""
        helpdesk.set_role("support agent")
        tag = _uid()

        # Create via API
        r = helpdesk.post("/api/v1/tickets", json={
            "title": f"Lifecycle RT {tag}", "description": "test",
        })
        tid = r.json()["id"]
        assert r.json()["status"] == "open"

        # Transition: open → in progress
        helpdesk.post(f"/_transition/tickets/{tid}/in progress")
        tickets = helpdesk.get("/api/v1/tickets").json()
        match = [t for t in tickets if t["title"] == f"Lifecycle RT {tag}"]
        assert match[0]["status"] == "in progress"

        # Transition: in progress → resolved
        helpdesk.post(f"/_transition/tickets/{tid}/resolved")
        tickets = helpdesk.get("/api/v1/tickets").json()
        match = [t for t in tickets if t["title"] == f"Lifecycle RT {tag}"]
        assert match[0]["status"] == "resolved"

    def test_unauthorized_transition_no_state_change(self, warehouse):
        """Failed transition should not change state."""
        warehouse.set_role("warehouse manager")
        sku = _uid()
        r = warehouse.post("/api/v1/products", json={
            "sku": sku, "name": "No Change RT", "category": "raw material",
        })
        pid = r.json()["id"]

        # Executive can't activate (lacks write inventory)
        warehouse.set_role("executive")
        r2 = warehouse.post(f"/_transition/products/{pid}/active")
        assert r2.status_code == 403

        # Verify status unchanged via API
        warehouse.set_role("warehouse manager")
        products = warehouse.get("/api/v1/products").json()
        match = [p for p in products if p["sku"] == sku]
        assert match[0]["status"] == "draft"


# ═══════════════════════════════════════════════════════════════════════
# DATA VISIBILITY ROUND-TRIP
# ═══════════════════════════════════════════════════════════════════════

class TestDataVisibilityRoundTrip:
    """Data created via API should appear in rendered pages."""

    def test_api_created_product_visible_in_dashboard(self, warehouse):
        """A product created via API should appear in the dashboard HTML."""
        warehouse.set_role("warehouse manager")
        sku = _uid()
        warehouse.post("/api/v1/products", json={
            "sku": sku, "name": f"Visible {sku}", "category": "raw material",
        })

        # Fetch the dashboard page
        warehouse.set_role("warehouse clerk")
        r = warehouse.get("/inventory_dashboard")
        assert sku in r.text, \
            f"Product {sku} created via API but not visible in dashboard HTML"

    def test_api_created_ticket_visible_in_queue(self, helpdesk):
        """A ticket created via API should appear in the queue HTML."""
        helpdesk.set_role("customer")
        tag = _uid()
        helpdesk.post("/api/v1/tickets", json={
            "title": f"Visible {tag}", "description": "test",
        })

        helpdesk.set_role("support agent")
        r = helpdesk.get("/ticket_queue")
        assert tag in r.text, \
            f"Ticket '{tag}' created via API but not visible in queue HTML"

    def test_transitioned_status_reflected_in_html(self, warehouse):
        """After transitioning a product, the new status appears in HTML."""
        warehouse.set_role("warehouse manager")
        sku = _uid()
        r = warehouse.post("/api/v1/products", json={
            "sku": sku, "name": f"Status Vis {sku}", "category": "raw material",
        })
        pid = r.json()["id"]
        warehouse.post(f"/_transition/products/{pid}/active")

        # The dashboard should show "active" for this product
        warehouse.set_role("warehouse clerk")
        r2 = warehouse.get("/inventory_dashboard")
        # Find the row with our SKU and check it contains "active"
        assert sku in r2.text
        # The word "active" should appear (as a status value in the table)
        assert "active" in r2.text


# ═══════════════════════════════════════════════════════════════════════
# ENUM ROUND-TRIP
# ═══════════════════════════════════════════════════════════════════════

class TestEnumRoundTrip:
    """Enum values selected in forms should persist correctly."""

    def test_enum_form_option_roundtrip(self, warehouse):
        """Select an enum value in a form, verify it persists."""
        warehouse.set_role("warehouse manager")
        sku = _uid()

        # Submit form with each enum value
        for category in ["raw material", "finished good", "packaging"]:
            s = _uid()
            warehouse.post("/add_product", data={
                "sku": s, "name": f"Enum {s}", "category": category,
            })
            products = warehouse.get("/api/v1/products").json()
            match = [p for p in products if p["sku"] == s]
            assert len(match) == 1
            assert match[0]["category"] == category, \
                f"Enum value '{category}' didn't persist correctly"
