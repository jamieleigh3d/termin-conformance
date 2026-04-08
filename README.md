# Termin Conformance Suite

Conformance test suite and specification for the Termin runtime. Contains the IR JSON Schema, Runtime Implementer's Guide, package format spec, test `.termin.pkg` fixtures, and 200+ behavioral tests. Everything needed to build and validate a conforming Termin runtime.

## What's Inside

```
termin-conformance/
├── specs/                              # Specifications
│   ├── termin-ir-schema.json           # IR JSON Schema (draft 2020-12)
│   ├── termin-runtime-implementers-guide.md  # How to build a runtime
│   └── termin-package-format.md        # .termin.pkg format spec
├── fixtures/                           # Test applications
│   ├── warehouse.termin.pkg            # Full-featured inventory app
│   ├── helpdesk.termin.pkg             # Ticket tracking with state machine
│   ├── projectboard.termin.pkg         # Project management with 5 content types
│   ├── hello.termin.pkg                # Minimal app (no content, no auth)
│   ├── hello_user.termin.pkg           # Role-based pages with compute
│   ├── compute_demo.termin.pkg         # Compute, Channel, and Boundary primitives
│   └── ir/                             # Raw IR JSON (for runtimes without .pkg support)
│       └── *.json
├── tests/                              # Conformance tests (TODO: migrate here)
├── adapter.py                          # Runtime adapter interface
├── adapter_reference.py                # Reference runtime adapter (in-process)
├── adapter_template.py                 # Template for your runtime adapter
├── conftest.py                         # Pytest fixtures and adapter wiring
└── requirements.txt                    # Test dependencies
```

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run against the reference runtime

```bash
# Install the reference runtime
pip install termin-compiler

# Run the conformance suite
TERMIN_ADAPTER=reference pytest tests/ -v
```

### 3. Run against your runtime

1. Copy `adapter_template.py` to `adapter_myruntime.py`
2. Implement `deploy()` — takes a `.termin.pkg`, returns a base URL
3. Optionally override `create_session()` for custom auth
4. Run:

```bash
TERMIN_ADAPTER=myruntime pytest tests/ -v
```

## Adapter Interface

Your runtime adapter implements one method:

```python
class MyAdapter(RuntimeAdapter):
    def deploy(self, fixture_path: Path, app_name: str) -> AppInfo:
        # Deploy the app and return its base URL
        return AppInfo(
            base_url="https://warehouse.myorg.myruntime.dev",
            ir=self.load_ir_from_fixture(fixture_path),
            cleanup=lambda: teardown(app_name),
        )
```

The suite deploys 6 test apps once per session and runs all tests via HTTP.

## Test Categories (201 tests)

### Tier 1: API Contract (131 tests)

| File | Tests | What it validates |
|------|-------|-------------------|
| `test_access_control.py` | 17 | Role resolution, scope checking, deny-by-default, role × verb × content matrices |
| `test_state_machines.py` | 19 | Initial state, valid transitions, scope-gated transitions, multi-word states, persistence |
| `test_field_validation.py` | 16 | Required fields, unique constraints, enum validation, min/max, type roundtrip |
| `test_crud.py` | 15 | List, create, get-one, update, delete, multiple records |
| `test_defaults.py` | 3 | `` defaults to `User.Name` ``, `` defaults to `now` `` |
| `test_data_isolation.py` | 5 | Cross-content safety, cross-app separation, mass assignment protection |
| `test_reflection.py` | 8 | Metadata endpoints, bootstrap, client runtime |
| `test_errors.py` | 4 | Error responses, edge cases |
| `test_websocket.py` | 3 | WebSocket connect, subscribe, unsubscribe |

### Tier 2: Presentation Contract (44 tests)

| File | Tests | What it validates |
|------|-------|-------------------|
| `test_presentation.py` | 21 | Page rendering, data tables, forms, buttons, filters, search |
| `test_presentation_contract.py` | 23 | IR-driven: every component, column, field, filter annotated with `data-termin-*` |

### Tier 3: Behavioral Round-Trip (16 tests)

| File | Tests | What it validates |
|------|-------|-------------------|
| `test_navigation.py` | 6 | Role-based nav visibility, role picker |
| `test_roundtrip.py` | 10 | Form submit → API verify, transition → API verify, data visibility |

## Specifications

- **[IR JSON Schema](specs/termin-ir-schema.json)** — Machine-readable contract defining the structure of compiled Termin applications (IR version 0.4.0)
- **[Runtime Implementer's Guide](specs/termin-runtime-implementers-guide.md)** — How to build a conforming runtime: storage, access control, state machines, events, presentation, CEL expressions, WebSocket protocol
- **[Package Format](specs/termin-package-format.md)** — `.termin.pkg` ZIP structure, manifest versioning, checksums, revision tracking

## IR Version

Current: **0.4.0**

### 0.4.0 (April 2026)

- **Expression delimiter: `[bracket]` → `` `backtick` ``** — Breaking change. Backticks are unambiguous with array indices (`items[0]`), familiar from markdown, and support both inline (`` `expr` ``) and triple-backtick (` ``` `) multi-line forms for embedded sub-languages (CEL, LLM prompts, provider-specific DSLs).
- **Confidentiality system** — `confidentiality_scopes` on FieldSpec and ContentSchema (AND semantics). `identity_mode`, `required_confidentiality_scopes`, `output_confidentiality_scope`, `field_dependencies` on ComputeSpec. `reclassification_points` on AppSpec.
- **Server-side Compute endpoint** — `POST /api/v1/compute/{name}` with 4 defense-in-depth checks (identity gate, taint integrity, CEL redaction guard, output taint enforcement).
- **Field redaction** — `{"__redacted": true, "scope": "..."}` markers in API responses for unauthorized fields. Presentation renders `[REDACTED]`.
- **`FieldDependency`** and **`ReclassificationPoint`** IR types for confidentiality audit trail.
- **Renamed PEG rule**: `jexl_expr` → `expr`, all `jexl` capture names → `cel`.
- **User identity standardized**: `User.Name`, `User.FirstName`, `User.Role`, `User.Scopes`, `User.Authenticated`. Deprecates `CurrentUser`, `LoggedInUser`, `UserProfile`.

### 0.3.0 (April 2026)

- `app_id` — compiler-managed UUID for deployment identity
- `default_expr` — CEL expressions for field defaults (`User.Name`, `now`)
- `condition_expr` — renamed from `jexl_condition` (CEL migration)
- `boundary_type` — application/library/module/configuration
- `client_safe` — compiler-inferred flag for client-side compute
- CEL (Common Expression Language) replaces JEXL for all expressions

## License

Apache 2.0
