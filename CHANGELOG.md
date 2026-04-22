# Changelog

## v0.8.1 (2026-04-21)

### Theme: Maintenance release

Non-breaking patch release. Fixes release-artifact drift from the v0.8.0
tag and addresses two post-release GitHub issues. No new test coverage;
IR schema unchanged at 0.8.0.

### Fixture syncs
- **`fixtures/ir/*.json`**: re-extracted from the v0.8.1 compiler.
  `warehouse_ir.json` was missing 132 lines of Edit/Delete/edit_modal
  content in the v0.8.0 tag because the release script wasn't run before
  tagging. Adapters that consumed `fixtures/ir/*.json` directly (not
  `.pkg`) saw pre-v0.8 IR shapes.
- **`specs/termin-ir-schema.json`** + **`fixtures/termin-ir-schema.json`**:
  re-copied from the v0.8.1 compiler. The edit_modal component type
  is in the ComponentNode enum; strict validators accept v0.8 IR.
- **`fixtures/*.termin.pkg`**: revision bumps from recompile; content
  equivalent to v0.8.0.
- **`fixtures/*.deploy.json`**: model name updated from
  `"claude-sonnet-4-6"` to `"claude-haiku-4-5-20251001"` matching the
  v0.8.1 compiler's auto-generated deploy template.

### GitHub issue fixes
- **#1** (Session-scoped fixture FK collision in access_control DELETE):
  `test_warehouse_access_matrix[warehouse manager-DELETE-products-200]`
  now clears any inbound `stock_levels` FK references before the
  authoritative delete attempt, keeping the assertion focused on scope
  gating rather than referential integrity. Cannot reproduce on current
  main, but the defensive fix lands regardless.
- **#2** (test_action_buttons_labeled expects literal button text):
  Assertion relaxed to accept any of the canonical marker attribute
  (`data-termin-<action>`), literal label text, or `aria-label="<label>"`.
  Aligns with the v0.8 row-actions spec where the data-termin-* markers
  are the canonical affordance and literal text is a reference-runtime
  convention, not a contract.

### Version
- Conformance: 0.8.0 → 0.8.1
- IR schema: 0.8.0 (unchanged)

---

## v0.8.0 (2026-04-21)

### Theme: v0.8 conformance — action primitives + browser

Adds 66 new conformance tests covering every v0.8 runtime capability,
introduces a `served-reference` adapter variant for browser-automation
tests, and corrects a latent IR schema drift by adding `edit_modal` to
the ComponentNode type enum.

### New test files
- **`test_v08_pagination_filter_sort.py`** (19 tests): query-param
  contract for auto-CRUD list endpoints — `?limit`, `?offset`, `?sort`,
  `?<field>=`. Covers validation (negative/non-integer rejected, cap
  at 1000), security (SQL injection rejected at schema gate, values
  parameterized), and combined filter+sort+pagination.
- **`test_v08_manual_compute_trigger.py`** (5 tests):
  `POST /api/v1/compute/<name>/trigger` — 404/400 handling,
  content_name inference, envelope shape.
- **`test_v08_row_actions.py`** (19 tests): three-layer contract for
  Delete / Edit / Inline edit — IR structural assertions, rendered-HTML
  `data-termin-*` markers, and server-side route behavior (scope gating,
  FK 409, single-field PUT).
- **`test_v08_put_state_machine_gate.py`** (8 tests): security contract
  for the PUT-route state-machine gate — undeclared transitions (409),
  unknown states (409), scope enforcement (403), atomicity on rejection,
  no-op on same-state, regression on PUT without state.
- **`test_v08_streaming_protocol.py`** (9 tests): `compute.stream.*`
  channel namespace and payload contract for text + tool-use modes.
- **`test_v08_ir_shapes.py`** (6 tests): IR schema acceptance +
  fixture validation — every v0.8 addition present in the warehouse
  fixture IR.
- **`test_v08_browser.py`** (10 Playwright tests): full row-action UI
  flows — dashboard renders, scope-gated button visibility, edit modal
  open + populate, inline edit cell becomes input, delete confirm
  dialog, general stream hydrator updates table cells. Requires
  `TERMIN_ADAPTER=served-reference` + `pip install playwright` +
  `playwright install chromium`; skips gracefully otherwise.

### New infrastructure
- **`adapter_served_reference.py`**: launches each deployed app on a
  randomized localhost port via uvicorn-in-thread. Makes `AppInfo.base_url`
  a real HTTP URL for browser navigation. Session-scoped — each app
  starts once per test session (~0.5s per app).
- **`conftest.py`** additions: `_chromium`, `browser_context`, and
  `browser_page` fixtures; `_require_served_url` helper that skips
  browser tests cleanly when the adapter isn't served.
- **`pytest.ini`**: registers the `browser` pytest mark.

### Spec changes
- **`specs/termin-ir-schema.json`**: `edit_modal` added to the
  ComponentNode type enum. Previously would have rejected every v0.8
  warehouse app's IR.

### Test counts
- HTTP / behavioral: 729 → 778 passing (reference adapter, in-process)
- Browser / Playwright: + 10 passing (served-reference adapter)
- **Total: 788 passing, 27 skipped, 0 failing**

### Version
- Conformance: 0.7.1 → 0.8.0
- IR schema: 0.7.0 → 0.8.0
