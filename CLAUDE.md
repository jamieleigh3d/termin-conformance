# Termin Conformance Suite — Developer Context

This file is for Claude Code sessions (and human contributors) working in
this repository. It captures the adapter pattern, test categories, release
flow, and the rules that keep the suite portable across runtimes.

See `CONTRIBUTING.md` in the sibling `termin-compiler` repo for the DCO
sign-off requirement and general contribution workflow.

## What this is

The **Termin Conformance Suite** is a separate public repo
(`github.com/jamieleigh3d/termin-conformance`) that holds the authoritative
**spec** and **test suite** for any Termin runtime. It is the contract every
runtime must satisfy; the `termin-compiler` reference runtime is one
implementation among potentially many.

What lives here:
- **`specs/termin-ir-schema.json`** — IR JSON Schema (draft 2020-12), the
  machine-readable contract.
- **`specs/termin-runtime-implementers-guide.md`** — the how-to-build-a-runtime
  document.
- **`specs/termin-package-format.md`** — `.termin.pkg` ZIP structure.
- **`fixtures/*.termin.pkg`** + **`fixtures/ir/*.json`** — test applications
  (warehouse, helpdesk, projectboard, hello, hello_user, compute_demo,
  agent_simple, agent_chatbot, channel_simple, channel_demo, security_agent,
  hrportal).
- **`fixtures/*.deploy.json`** — deploy configs for agent/channel apps.
- **`tests/`** — 788 behavioral tests on v0.8.1 (778 HTTP/WS + 10 Playwright
  browser).
- **`adapter.py`** + adapter implementations — the plug-in interface for
  runtimes.

Current version: **v0.8.1** (IR schema 0.8.0). v0.8.0 has a known flaw
(stale `fixtures/ir/*.json`, missing `edit_modal` in the schema's
ComponentNode enum) — point readers at v0.8.1.

## The two-repo relationship

- **`termin-compiler`** — reference compiler + runtime. Canonical
  implementation.
- **`termin-conformance`** — this repo. Spec + tests that any conforming
  runtime must satisfy.

Both release together. The compiler's `util/release.py` bumps versions in
both repos, regenerates fixtures here, copies the IR JSON schema here, and
runs both test suites. **Never release one without the other.** When the
compiler CHANGELOG says "fixture syncs" or "IR schema updates," that's the
compiler script writing into this repo.

## The adapter pattern

The whole suite is adapter-agnostic. Each adapter tells the suite how to:

1. **Deploy** a `.termin.pkg` and return an `AppInfo(base_url, ir, cleanup)`.
2. **Authenticate** a test session as a specific role (via
   `TerminSession.set_role`).
3. **Tear down** when the session ends.

Three adapters ship in this repo:

- **`adapter_reference.py`** — default. Spins up the `termin_runtime`
  FastAPI app in-process via `TestClient`. Fast (~30s for the full HTTP
  suite). Used for CI and local dev. Deploy returns an in-memory base_url
  that hits the TestClient.
- **`adapter_served_reference.py`** — launches each app on a real
  `http://127.0.0.1:<port>` via uvicorn-in-thread. Required for browser
  tests that need a real HTTP URL for Playwright navigation. Slower
  (~0.5s per app session-scoped setup).
- **`adapter_template.py`** — blank skeleton for third-party runtimes to
  copy.

Adapter selection: `TERMIN_ADAPTER=<name> pytest tests/ -v`. Default is
`reference`.

The rule: **tests must not know which adapter is running.** If a test
needs a real HTTP URL (e.g., for Playwright), it uses the
`_require_served_url` helper in `conftest.py` which skips cleanly when
the adapter is in-process. Do not branch on adapter name inside tests.

## Test categories

From `README.md`; maintain these tiers as you add tests:

- **Tier 1 — API Contract (131 tests):** access control, state machines,
  field validation, CRUD, defaults, data isolation, reflection, errors,
  WebSocket basic.
- **Tier 2 — Presentation Contract (44 tests):** page rendering + IR-driven
  `data-termin-*` marker presence. Tests use DOM selectors only — never
  literal English text. If a test says "look for the word 'Delete'", it's
  wrong; look for `data-termin-delete` or `aria-label="Delete"` instead.
  (See the conformance#2 GitHub issue fix in v0.8.1.)
- **Tier 3 — Behavioral Round-Trip (16 tests):** navigation, form submit →
  API verify, transition → API verify.
- **Tier 4 — v0.5+ Features (284 tests):** IR structure for v0.5 additions,
  runtime v0.5 behaviors, IR schema validation across every fixture,
  behavioral WebSocket push contract.
- **v0.8 additions (66 tests across 7 files):** `test_v08_*.py` —
  pagination/filter/sort, manual compute trigger, row actions
  (Delete/Edit/inline), PUT-route state-machine gate, streaming protocol,
  IR shapes, browser.

## Running the suite

```bash
# Default: in-process reference adapter, HTTP + WS tests only
TERMIN_ADAPTER=reference pytest tests/ -v

# Served adapter, full suite including browser (requires Playwright install)
pip install playwright && playwright install chromium
TERMIN_ADAPTER=served-reference pytest tests/ -v

# Just browser tests
TERMIN_ADAPTER=served-reference pytest tests/test_v08_browser.py -v

# Single file
TERMIN_ADAPTER=reference pytest tests/test_access_control.py -v
```

Browser tests skip gracefully without Playwright. Don't mark them with
`@pytest.mark.skip` by default — the skip is dynamic (driven by the
`_require_served_url` helper + the `browser` pytest mark registered in
`pytest.ini`).

## Adding a conformance test (the conformance-first TDD pattern)

The contract comes first; the implementation follows.

1. **Write the `.termin` example first** (or reuse an existing fixture) so
   the feature has a concrete artifact.
2. **Write the conformance test** that expresses the contract you want.
   The test SHOULD fail initially — that's how you know it's testing
   something real.
3. **Update `termin-ir-schema.json` in the compiler repo** if the feature
   adds any IR field or enum value.
4. **Implement in the runtime.**
5. **Run `util/release.py` in the compiler repo** to regenerate fixtures
   here.
6. **Test should now pass.** If it doesn't, the runtime is wrong (or the
   test is — common enough that it's worth checking both directions).

**The conformance suite is the spec.** If a behavior isn't tested here, it
isn't specified, and the runtime is free to change it. Treat that as a
hole to fill, not a feature.

## Fixtures come from the compiler — do not hand-edit

`fixtures/*.termin.pkg` and `fixtures/*.deploy.json`
are **generated artifacts**. They are
produced by `util/release.py` in the compiler repo and copied here
automatically. If you edit them by hand:

- Next release will overwrite your edits.
- The conformance tests will pass locally but fail in any other
  environment that pulls from the compiler release.

If a fixture is wrong, fix the compiler (or the example `.termin` file in
the compiler's `examples/`), regenerate, and commit the regenerated
fixture. The v0.8.0 miss (stale `fixtures/ir/warehouse_ir.json` missing
132 lines for Edit/Delete/edit_modal) happened because the release script
wasn't run before tagging. v0.8.1 fixed it by re-running the release.

## Browser tests (Playwright)

- **Selector discipline:** use `[data-termin-<something>]` attributes,
  never literal English text. A user changing the button label from
  "Delete" to "Remove" must not break conformance. Marker attributes are
  the canonical affordance; literal text is a reference-runtime
  convention.
- **Chromium only** for now. Tests run with headless Chromium via a
  session-scoped `browser_context` fixture.
- **`_require_served_url`** skips browser tests when the in-process
  adapter is active — don't skip via static decorators.
- **`browser` pytest mark** registered in `pytest.ini`. Use it to filter
  (`pytest -m browser` or `pytest -m "not browser"`).

## Things future Claude should NOT do

- **Do not hand-edit fixtures.** They're regenerated from the compiler
  release. See above.
- **Do not write tests that depend on literal English text** in rendered
  HTML. Use `data-termin-*` selectors. If a test is broken because a
  label changed, the test is wrong.
- **Do not release conformance without running the compiler's
  `util/release.py`** end-to-end first. The compiler release script is
  what syncs this repo's fixtures and schema. See the termin-compiler
  CLAUDE.md release checklist.
- **Do not move the `v0.8.0` tag.** It ships with known-flawed fixtures;
  the v0.8.1 CHANGELOG documents it. Point readers at v0.8.1.
- **Do not merge test behaviors across adapters.** Tests should pass
  identically against any conforming runtime. If a test only passes
  against the reference adapter, it's testing implementation, not
  contract.
- **Do not add tests under `test_v08_*` after v0.8 is closed.** Once v0.9
  work starts, new tests live in appropriately-versioned files
  (`test_v09_*`) or in the topical files (`test_access_control.py`,
  `test_state_machines.py`, etc.).

## Handling external GitHub issues

When responding to issues reported by other runtime implementers or users:

- **Reproduce first.** If the issue reproduces, write a regression test
  before the fix — that's the contract change the bug exposes.
- **If it doesn't reproduce**, a defensive fix plus a CHANGELOG note is a
  valid outcome when the reporter's evidence is clear but the repro path
  isn't reliable. Document the defensive change honestly rather than
  closing as "could not reproduce."
- **Relax assertions, don't tighten them**, when a conformance test is
  over-specific. The v0.8.1 fix for a test that expected literal "Delete"
  button text is a good example: the test was relaxed to accept marker
  attributes (`data-termin-*`), literal text, OR `aria-label`, matching
  the v0.8 row-actions spec where markers are the canonical affordance.
- **Document in CHANGELOG** under the appropriate version and commit on a
  feature branch that fast-forward-merges to main.

## Current state (as of v0.8.1)

- 788 tests passing (778 HTTP/WS on `reference`, 10 browser on
  `served-reference`).
- 27 skipped, 0 failing, 0 xfails.
- IR schema 0.8.0.
