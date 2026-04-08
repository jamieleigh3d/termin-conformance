# Termin Conformance Testing Methodology

**Version:** 1.0.0-draft
**Authors:** Jamie-Leigh Blake & Claude Anthropic

---

## Purpose

This document describes the approach, categories, and principles behind the Termin Conformance Test Suite. It serves as a reference for understanding what the tests validate, how they validate it, and how to extend the suite for new runtime features.

The conformance suite answers one question: **does this runtime behave correctly for every contract defined in the IR?**

---

## Principles

### 1. Test Observable Behavior, Not Implementation

Every conformance test interacts with the runtime through its public interfaces: HTTP API, rendered HTML, and WebSocket. No test imports runtime internals, inspects database tables, reads log files, or depends on a specific framework. A runtime written in Rust, Go, Python, or JavaScript should pass the same tests.

### 2. IR-Driven Expectations

Tests derive their expectations from the IR — the compiled application description. If the IR declares a Content with a required field, the test verifies the runtime rejects creates without that field. If the IR declares a state machine transition requiring a scope, the test verifies the runtime returns 403 without that scope.

This means the tests are not hardcoded descriptions of expected behavior — they are programmatic assertions against the IR contract. When the IR changes, the tests adapt.

### 3. Session-Scoped Apps, Test-Isolated Data

Each test application (warehouse, helpdesk, etc.) is deployed once per test session via the adapter. All tests within a session share the same running app instance. Tests use unique identifiers (`uuid4`) for all created data to avoid interference.

### 4. Adapter Abstraction

The conformance suite never knows how an app is deployed, how authentication works, or what technology the runtime uses. An adapter translates between the suite's abstract operations (deploy, authenticate, make HTTP request) and the runtime's concrete mechanisms.

---

## Test Tiers

### Tier 1: API Contract Tests

**Interface:** HTTP request → HTTP response

Tests that the REST API behaves correctly for every CRUD operation, access control rule, state machine transition, and field constraint declared in the IR.

**What Tier 1 tests:**
- **Access control:** every role × verb × content combination returns the correct status code (200, 201, 403, 404)
- **State machines:** initial state assignment, valid transitions succeed, invalid transitions return 409, scope-gated transitions return 403
- **Field validation:** required fields enforced (400), unique constraints enforced (409), enum values enforced (422)
- **CRUD operations:** create returns record with ID, get-one returns correct record, update modifies fields, delete removes record
- **Default expressions:** `defaults to [User.Name]` populates correctly from identity
- **Data isolation:** operations on one Content don't affect another
- **Error handling:** nonexistent records return 404, duplicate keys return 409, malformed input returns 4xx

**What Tier 1 does NOT test:**
- What the HTML looks like
- Whether JavaScript works
- How the runtime stores data internally

### Tier 2: Presentation Contract Tests

**Interface:** HTTP GET → HTML response → DOM analysis

Tests that rendered pages contain the semantic content declared in the IR's component tree. Uses `data-termin-*` attributes as the bridge between the IR and the rendered output.

**The `data-termin-*` contract:**

Every conforming runtime must annotate its rendered output with IR references:

| Attribute | Purpose | Example |
|-----------|---------|---------|
| `data-termin-component` | Component type from IR | `data-termin-component="data_table"` |
| `data-termin-source` | Content name this component displays | `data-termin-source="products"` |
| `data-termin-field` | Field name within a row | `data-termin-field="sku"` |
| `data-termin-row-id` | Record ID for a table row | `data-termin-row-id="42"` |
| `data-termin-target` | Content name a form submits to | `data-termin-target="tickets"` |

For non-HTML renderers (Three.js, native apps, etc.), the equivalent contract applies through the platform's metadata mechanism (e.g., `userData` on Three.js objects, accessibility labels on native views). The conformance suite's HTML tests use `data-termin-*`; a runtime-specific test layer would use the platform equivalent.

**What Tier 2 tests:**

**Component existence:** For every component in the IR's page tree, the rendered HTML must contain an element annotated with the corresponding `data-termin-component` type and `data-termin-source`.

**Column completeness:** For every column declared on a `data_table`, the rendered HTML must contain the column's field name — either as a header label, a `data-termin-field` attribute, or cell content.

**Form field completeness:** For every `field_input` declared in a `form`, the rendered HTML must contain an input element with a matching `name` attribute. Required fields must have the `required` attribute.

**Filter controls:** For every `filter` child of a `data_table`, the rendered HTML must contain a filter control referencing that field.

**Navigation visibility:** Nav items declared as `visible_to: ["all"]` must appear for every role. Nav items restricted to specific roles must appear only for those roles and be absent for others.

**Action button state:** Transition buttons must be enabled when the transition is valid for the current state and user scope, and disabled or hidden otherwise.

**What Tier 2 does NOT test:**
- Visual appearance (colors, fonts, layout, CSS)
- Specific HTML tag names (`<table>` vs `<div role="table">`)
- JavaScript behavior or client-side interactivity

### Tier 3: Behavioral Round-Trip Tests

**Interface:** Rendered page → automated interaction → API verification

Tests the full data loop: a user action in the rendered UI (filling a form, clicking a button) produces the expected effect in the data layer (a record is created, a state transitions). This verifies that the presentation layer and the API layer agree.

**The automation approach:**

Tier 3 tests use one of two mechanisms:

1. **Automation API** (preferred): The runtime exposes a `/runtime/automation` endpoint that returns a structured description of the current page state — rendered components, available actions, form fields, current data. The conformance suite interacts with this API programmatically without needing a browser.

2. **Browser automation** (alternative): For runtimes that don't implement the automation API, a headless browser (Playwright, Puppeteer) renders the page and interacts with `data-termin-*` annotated elements. This is slower and requires a browser dependency but works with any HTML-rendering runtime.

**What Tier 3 tests:**

**Form round-trip:** Navigate to a page with a form. Fill each `data-termin-field` input. Submit the form. Verify via the API that the record was created with the correct values.

**Transition round-trip:** Navigate to a page with action buttons. Click a transition button (identified by `data-termin-component="action_button"` and target state). Verify via the API that the record's status changed.

**Real-time update:** Create a record via the API. Verify that a page with a `subscribe` component for that Content reflects the new data without a page reload (requires WebSocket or polling verification).

**Default population round-trip:** Submit a form without filling fields that have `default_expr`. Verify the created record has the correct default values (e.g., `User.Name` for `submitted_by`).

---

## Test File Organization

Tests are organized by category, one file per major concern:

```
tests/
├── test_access_control.py       # Tier 1: identity, scopes, role × verb matrices
├── test_state_machines.py        # Tier 1: initial state, transitions, scope gating
├── test_field_validation.py      # Tier 1: required, unique, enum, type roundtrip
├── test_crud.py                  # Tier 1: list, create, get-one, update, delete
├── test_defaults.py              # Tier 1: default_expr evaluation via API
├── test_data_isolation.py        # Tier 1: cross-content, cross-app, mass assignment
├── test_presentation.py          # Tier 2: IR-driven HTML analysis
├── test_navigation.py            # Tier 2: role-based nav visibility
├── test_reflection.py            # Tier 1: metadata and bootstrap endpoints
├── test_websocket.py             # Tier 1/3: WebSocket protocol
└── test_errors.py                # Tier 1: error responses, edge cases
```

Each file imports fixtures from `conftest.py` and uses the adapter interface. No file imports from any runtime implementation.

---

## Writing New Tests

### Adding a Tier 1 test

```python
def test_new_behavior(self, warehouse):
    """Description of what this tests."""
    warehouse.set_role("warehouse manager")
    r = warehouse.post("/api/v1/products", json={
        "sku": _uid(), "name": "Test", "category": "raw material",
    })
    assert r.status_code == 201
    assert r.json()["status"] == "draft"
```

### Adding a Tier 2 test (IR-driven)

```python
def test_data_table_has_declared_columns(self, warehouse, warehouse_ir):
    """Every column declared in the IR must appear in the rendered HTML."""
    warehouse.set_role("warehouse clerk")
    r = warehouse.get("/inventory_dashboard")
    html = r.text

    page = next(p for p in warehouse_ir["pages"]
                if p["slug"] == "inventory_dashboard")
    data_table = next(c for c in page["children"]
                      if c["type"] == "data_table")

    for col in data_table["props"]["columns"]:
        assert col["field"] in html or col["label"] in html, \
            f"Column '{col['field']}' declared in IR but missing from HTML"
```

### Test naming convention

- `test_<what>_<expected>` for positive tests: `test_create_returns_201`
- `test_<what>_<condition>_<expected>` for conditional: `test_create_without_scope_is_403`
- `test_<what>_<edge_case>` for edge cases: `test_delete_nonexistent_returns_404`

---

## Adapter Requirements

An adapter must implement:

| Method | Required | Purpose |
|--------|----------|---------|
| `deploy(fixture_path, app_name) → AppInfo` | Yes | Deploy a test app, return base URL |
| `create_session(app_info) → TerminSession` | Yes | Create an HTTP session with set_role() |

The `TerminSession` must support:

| Method | Required | Purpose |
|--------|----------|---------|
| `get(path)`, `post(path)`, `put(path)`, `delete(path)` | Yes | HTTP methods |
| `set_role(role, user_name)` | Yes | Set identity for subsequent requests |
| `websocket_connect(path)` | Optional | WebSocket connection (Tier 3) |

---

## Coverage Goals

| Tier | Tests | Coverage Target |
|------|-------|----------------|
| Tier 1 (API) | 150+ | Every access grant, transition, field constraint |
| Tier 2 (Presentation) | 50+ | Every component type, column, form field, nav item |
| Tier 3 (Round-trip) | 20+ | Form submit, transition click, real-time update |
| **Total** | **220+** | |

---

## Future Extensions

- **Performance conformance:** response time bounds for CRUD operations
- **Concurrency conformance:** concurrent writes don't corrupt state
- **Migration conformance:** upgrading an app (same app_id, higher revision) preserves data
- **Accessibility conformance:** ARIA attributes on interactive elements
