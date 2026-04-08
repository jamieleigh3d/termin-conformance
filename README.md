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

## Test Categories

| Category | Tests | What it validates |
|----------|-------|-------------------|
| Identity & Access Control | 40+ | Role resolution, scope checking, deny-by-default, per-content grants |
| State Machine Enforcement | 30+ | Initial state, valid transitions, scope-gated transitions, multi-word states |
| Field Validation | 30+ | Required fields, unique constraints, enum validation, type roundtrip |
| CRUD Operations | 25+ | List, create, get-one, update, delete, error responses |
| Presentation | 25+ | Page rendering, data tables, forms, action buttons, filters, nav |
| Default Expressions | 20+ | `defaults to [User.Name]`, `defaults to [now]`, CEL evaluation |
| Data Isolation | 10+ | Cross-content safety, cross-app separation, mass assignment protection |
| Events & WebSocket | 10+ | EventBus, channel filtering, WebSocket protocol |
| Navigation | 10+ | Role-based visibility, nav items |
| Reflection & Bootstrap | 10+ | Metadata endpoints, client initialization |
| IR Schema Validation | 6 | All fixtures validate against JSON Schema |

## Specifications

- **[IR JSON Schema](specs/termin-ir-schema.json)** — Machine-readable contract defining the structure of compiled Termin applications (IR version 0.3.0)
- **[Runtime Implementer's Guide](specs/termin-runtime-implementers-guide.md)** — How to build a conforming runtime: storage, access control, state machines, events, presentation, CEL expressions, WebSocket protocol
- **[Package Format](specs/termin-package-format.md)** — `.termin.pkg` ZIP structure, manifest versioning, checksums, revision tracking

## IR Version

Current: **0.3.0**

This suite validates runtimes implementing IR version 0.3.0. Key features:
- `app_id` — compiler-managed UUID for deployment identity
- `default_expr` — CEL expressions for field defaults (`User.Name`, `now`)
- `condition_expr` — renamed from `jexl_condition` (CEL migration)
- `boundary_type` — application/library/module/configuration
- `client_safe` — compiler-inferred flag for client-side compute
- CEL (Common Expression Language) replaces JEXL for all expressions

## License

Apache 2.0
