# Changelog

## [0.9.1] — 2026-05-01

Conformance pack expansion + spec-tightening release. Closes the
Phase 3 + Phase 4 cross-runtime conformance gaps that v0.9.0 left
deferred. **IR schema unchanged** at 0.9.0 — patch release only
adds new `test_v09_*.py` files and tightens existing assertions;
no fixture re-shape.

### Added

- **Phase 3 conformance pack** — `specs/compute-contract.md`
  (~1100 lines, 9 sections covering registry shape, tool-surface
  gating, audit-record reshape per BRD §6.3.4, refusal envelope
  + sidecar semantics, Acts-as principal substitution) plus 45
  adapter-tested assertions across 5 files
  (`test_v09_compute_{contract,grants,audit,refusal,acts_as}.py`).
  Pins the three Compute contracts (`llm`, `ai-agent`,
  `default-CEL`) for any conforming runtime + provider pair.
- **Phase 4 conformance pack** — `specs/channel-contract.md`
  (~900 lines, 8 sections covering the four channel contracts,
  registry surface, failure-mode semantics, strict-mode gate,
  inbound auto-routing, per-channel scope) plus 77 adapter-tested
  assertions across 5 files
  (`test_v09_channel_{contract,dispatch,strict_mode,inbound,failure_modes}.py`).
- **`__termin_principal_preferences` audit-shape additions**
  surface in the `compute_audit_log_*` schema across the
  reference fixtures — they round-trip cleanly through the
  conformance suite at the new totals.

### Changed

- **`failure_mode` enum:** renamed `queue-and-retry-forever` →
  `queue-and-retry` in `specs/termin-ir-schema.json`. Companion
  rename across the compiler analyzer + parser + IR schema.
- **Spec §5.3 — `surface-as-error` is now deterministic**, not
  conditional. The previous "either propagates or falls back to
  log-and-drop" framing accepted broken implementations; v0.9.1
  pins the contract: provider raises → ChannelError propagates,
  original chained via `__cause__`, error metric increments. A
  runtime that catches and swallows in this mode is
  non-conforming.
- **Spec §5.4 — `queue-and-retry` test SKIPPED with v0.10
  deferral marker**. The v0.10 implementation lands an async
  retry worker with exponential backoff + dead-letter table at a
  configurable max-retry-hours window. The v0.9.x conformance
  posture: a runtime that has not implemented the worker MUST
  fall back to log-and-drop; the fallback test is deterministic.
- **Spec §7.1 — anonymous principal stamping requires
  `anonymous:<short>` synthesis** (was silent on the anonymous
  case in v0.9.0, leading to empty-string columns). The v0.9.1
  reference runtime synthesizes via the new
  `make_anonymous_principal` factory in `termin-core`.

### Fixed

- **Manual-trigger CEL audit gap (§5.2).** v0.9.0 reference
  runtime silently dropped audit rows on the manual `/trigger`
  path for `default-CEL` computes. Spec §5.2 always required
  the row; the conformance test now asserts it
  (un-skipped from the previous "skip if missing" placeholder).
  Reference-runtime fix lives in
  `termin-server/compute_runner._execute_cel_compute`.
- **Stranded delegate-mode test relaxation** picked up at
  release-day audit time — the post-FF-merge test was asserting
  the older mirror invariant against the new chain-target
  invariant. Recovery commit `4e56297` aligned spec + test.

### Suite

**1036 tests passing on the reference runtime, 32 skipped, 0
failed in 46s** (was 925 + 31 skipped + 0 failed). Test count
delta: +111 from Phase 3 (45) + Phase 4 (77) packs, minus 11
that overlapped with existing single-state-machine tests now
covered structurally by the new packs. Browser conformance
(`test_v08_browser.py` on `served-reference`) holds at 10/10.

## [0.9.0] — 2026-04-30

The v0.9 milestone release. The conformance suite tracks IR schema
0.9.0 and the v0.9 contract additions — keyset-cursor pagination,
multi-state-machine support, ownership-cascade gates (BRD #3 §3.6),
the `the user` shape on the CEL surface (BRD #3 §4.2), and the ten
`presentation-base.*` provider contracts (BRD #2 §5.1).

**Release-day suite:** 925 tests passing on Windows (915 reference +
10 served-reference browser), 31 skipped, 0 failing. Browser
conformance returns to 10/10 after the EditModalFlow regression in
the compiler was fixed today (see compiler CHANGELOG).

### Release-day note (2026-04-30)

Fixtures regenerated end-to-end via `termin-compiler/util/release.py`
to pick up the `_build_edit_modal` lowering fix that retired the
duplicate `data-termin-field` emission for state-machine columns.
The `fixtures/*.termin.pkg` artifacts and `fixtures/ir/*.json` IR
dumps reflect the corrected lowering; the v0.8 EditModalFlow tests
in `tests/test_v08_browser.py` pass against the regenerated
warehouse fixture.

### 24 pre-existing failures squashed (2026-04-29 late evening)

Suite went from 891 passing / 24 failing to **915 passing / 0 failing**.

**Root cause #1 — Playwright session fixture poisoned the asyncio
runner for migration tests.** `_chromium` (session-scoped) called
`sync_playwright().__enter__()` whenever the Playwright PIP package was
installed, even when the active adapter was `reference` (in-process,
unreachable by a real browser). The dependent tests then skipped via
`_require_served_url`, but the playwright driver subprocess + its
asyncio loop stayed alive for the rest of the session. pytest-asyncio
1.x's `Runner.run()` then raised "Runner.run() cannot be called from a
running event loop" for every async test that ran later in collection
order — 23 migration tests across `test_v09_migration_apply.py`,
`test_v09_migration_classifier.py`, `test_v09_migration_e2e.py`, and
`test_v09_migration_fault_injection.py`. Fix in `conftest.py`: gate
`_chromium` on `TERMIN_ADAPTER` and skip before launching sync_playwright
when the adapter is `reference`/`template`/unset. Browser tests still
run normally under `served-reference`.

**Root cause #2 — `?offset=` test asserted retired v0.8 behavior.**
v0.9 removed `?offset=` in favor of keyset cursors (BRD §6.2); the
runtime now rejects the parameter with HTTP 400 and migration guidance.
`test_v08_pagination_filter_sort.py::test_offset_skips_records` was
asserting the old skip semantics — it pre-dated the offset removal.
Replaced with `test_offset_param_rejected_with_v09_guidance` asserting
the migration contract (status 400 + `cursor` mentioned in the error
message). The `test_negative_offset_rejected` neighbor still passes
(any offset returns 400 in v0.9).

**Bonus — sync `asyncio.run()` calls in classifier converted to
`@pytest.mark.asyncio`.** Four sync test methods in
`test_v09_migration_classifier.py` called `asyncio.run(...)` directly.
Not the cause of the 24 failures, but identified during root-cause
hunt as a fragile pattern that would break the same way once any
caller of those tests started managing its own loop. Converted to
async-marked tests using the runner pytest-asyncio already provides.

### Pre-Phase 7 cleanup (2026-04-29 evening)

Fixture regen + adapter / test-infra fixes paired with the compiler-side
deploy-template fix.

**Fixture regen** — every `fixtures/*.termin.pkg`, `fixtures-cascade/*.termin.pkg`,
and `fixtures/*.deploy.json` regenerated via the compiler's
`util/release.py`. Deploy configs now consistently emit the v0.9 shape
on every channel (`provider`/`config` envelope), including the channels
that don't declare `Provider is "X"` in source — those previously fell
through the generator's legacy fallback path and produced flat
URL/protocol/auth blobs the v0.9 strict validator rejected. The
generator fix lives in `termin-compiler/termin/cli.py`.

**Adapter — `deploy_with_agent_mock` patches v0.9 deploy shape** —
`adapter_reference.py` was patching `deploy_config["ai_provider"]` (the
retired v0.8 top-level shape). v0.9 routes per-compute provider
configuration through `bindings.compute.<name>.config`. The adapter now
overwrites `bindings.compute.*.api_key = "mock"` (and `model = "mock"`)
on every LLM/agent compute binding, plus synthesizes a full v0.9 deploy
config when no `<app>.deploy.json` exists. Without this, the
`${ANTHROPIC_API_KEY}` placeholder remained, the provider's
`is_configured()` returned False, and `compute_runner` skipped every
mocked invocation with "no provider bound, skipped".

**`tests/test_behavioral_ws.py::_make_server` gives each app a unique
DB** — the helper called `create_termin_app(...)` without `db_path=`,
which meant all three session-scoped fixtures
(`agent_simple_ws_server`, `channel_simple_ws_server`,
`warehouse_ws_server`) shared the default `./app.db`. Whichever fixture
ran first owned the schema; the other two then hit `MigrationBlockedError`
on startup because their IRs declared different content types. Each
helper now mints a `tempfile.mktemp(suffix=f"_{app_name}_ws.db")`. The
shared `app.db` was masked in prior runs by happening to contain a
schema compatible with whichever app went first; the regenerated
fixtures put more apps through the helper and surfaced the latent bug.

### Phase 5: presentation provider conformance pack (2026-04-29)

**New test pack:** `tests/test_v09_presentation_provider.py` (33 tests)
covering the v0.9 Phase 5 contracts every conforming runtime + provider
pair must satisfy.

**New spec:** `specs/presentation-contract.md` (~200 lines) — companion
to BRD #2. Captures the language-level invariants the test pack
exercises. Three sections:
- §2 Provider Protocol — declared_contracts, render_modes, render_ssr,
  csr_bundle_url, Redacted sentinel + JSON wire shape.
- §3 Binding resolution — namespace fan-out, per-contract override,
  instance caching, default-Tailwind synthesis, unknown-product /
  unknown-namespace fail-soft, package-namespace expansion via the
  contract-package registry.
- §4 Contract package loading — well-formed YAML, missing required
  fields, intra-package + cross-package verb collision (BRD §4.5),
  deploy-config wiring, fail-closed on missing file / verb collision,
  no-packages no-op, deploy-relative path resolution.

Per BRD #2 §12 / Q8 the pack lands as one commit after the underlying
compiler slices (5c.1-5c.4) merge to `feature/v0.9` — the cross-repo
sequencing constraint is satisfied.

**Out of scope for v0.9, deferred to v0.10:**
- Per-component override-mode dispatch (mixing SSR Tailwind + CSR
  Spectrum within a single page).
- SSR rendering through `PresentationProvider.render_ssr` (the legacy
  presentation.py path remains authoritative until a runtime-side
  refactor lands).

### Phase 2.x (a): cascade grammar (2026-04-26)

**New test pack:** `tests/test_v09_cascade.py` (9 tests) covering:
- IR shape: every reference field carries a non-null
  `cascade_mode in {cascade, restrict}`; non-reference fields carry
  `null`.
- Schema validation: every cascade fixture's IR validates against
  the v0.9 schema, including the new `if/then/else` invariant on
  FieldSpec.
- Cascade-on-delete behavior: deleting a parent removes
  cascade-children.
- Restrict-on-delete behavior: deleting a parent with
  restrict-children returns 409.
- Self-cascade subtree deletion.
- Optional FK with cascade — NULL-FK records unaffected by other
  parents' deletes.
- Multi-hop cascade chain (A → B → C all cascade).

**New fixtures** in `fixtures-cascade/` (separate from production
`fixtures/` since these are purpose-built test apps, not example
applications):
- `cascade_demo.termin.pkg`
- `cascade_self_ref.termin.pkg`
- `cascade_optional.termin.pkg`
- `cascade_multihop_ok.termin.pkg`

**Conftest:** new session-scoped fixtures for the four cascade test
apps. Negative fixtures (`*_rejected.termin`) stay compiler-side —
they exercise the compiler's refusal to compile structurally
deadlocked or cyclic cascade graphs, which is a compile-time concern,
not a runtime-conformance concern.

**IR schema:** synced from compiler. New optional `cascade_mode`
property on FieldSpec with a structural `if/then/else` invariant
that requires it whenever `business_type == "reference"`. v0.8 IRs
without `cascade_mode` on reference fields fail v0.9 validation.

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
