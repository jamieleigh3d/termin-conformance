# Termin Conformance Suite

Conformance test suite and specification for the Termin runtime. Contains the IR JSON Schema, Runtime Implementer's Guide, package format spec, test `.termin.pkg` fixtures, and 788 behavioral tests (778 HTTP/WebSocket + 10 Playwright browser). Everything needed to build and validate a conforming Termin runtime.

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
│   ├── agent_simple.termin.pkg         # Minimal AI agent (LLM completion)
│   ├── agent_chatbot.termin.pkg        # Conversational agent with tool calls
│   ├── channel_simple.termin.pkg       # Channel loopback demo
│   ├── channel_demo.termin.pkg         # All 6 channel patterns
│   ├── security_agent.termin.pkg       # Action channels + agent computes
│   ├── *.deploy.json                   # Deploy configs for channel/agent apps
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

The suite deploys 12 test apps once per session and runs all tests via HTTP and WebSocket.

## Test Categories (475 tests)

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

### Tier 4: v0.5.0 Features (284 tests)

| File | Tests | What it validates |
|------|-------|-------------------|
| `test_ir_v050.py` | 80 | IR structure: singular, directive, accesses, input/output fields, trigger_where, channel actions, event sends, semantic marks |
| `test_runtime_v050.py` | 44 | Agent/channel app bootstrap, webhooks, channel reflection, deploy config, default field values, state machine access control |
| `test_ir_schema_validation.py` | 94 | Every IR fixture validates against the IR JSON Schema (draft 2020-12) |
| `test_behavioral_ws.py` | 5 | Real WebSocket push: create→push, update→push, subscribe current, payload shape, no cross-content leakage |

## Specifications

- **[IR JSON Schema](specs/termin-ir-schema.json)** — Machine-readable contract defining the structure of compiled Termin applications (IR version 0.9.0)
- **[Runtime Implementer's Guide](specs/termin-runtime-implementers-guide.md)** — How to build a conforming runtime: storage, access control, state machines, events, presentation, CEL expressions, WebSocket protocol, behavioral contract
- **[Package Format](specs/termin-package-format.md)** — `.termin.pkg` ZIP structure, manifest versioning, checksums, revision tracking

## IR Version

Current: **0.9.0** (in development)

### 0.7.0 (April 2026)

- **Auto-generated REST API (D-11)** — Every Content gets CRUD at `/api/v1/{content}` automatically. Headless services (no user stories) fully supported. `Expose a REST API` syntax removed.
- **Agent observability (D-20)** — AUDIT verb, auto-generated `compute_audit_log_{name}` Content per Compute, trace recording, audit levels (none/actions/debug), redaction in flight.
- **Chat component (D-09)** — New `chat` IR component type. Not AI-specific — any Content with role+content fields. Integrated input, WebSocket subscription.
- **Transition feedback** — `TransitionFeedbackSpec` on transitions: trigger, style (toast/banner), message (CEL or literal), dismiss_seconds.
- **Compound verbs** — All verb combinations supported in access grants (view, create, update, delete, audit in any combination).
- **SQL safety** — Runtime validates all IR identifiers at startup, rejects unsafe names. SQL centralized in storage.py.

### 0.5.0 (April 2026)

- **AI Providers** — `Provider is "llm"` (field-to-field completion) and `Provider is "ai-agent"` (autonomous agent with tool calls). Built-in Anthropic + OpenAI support.
- **Field wiring** — `Input from field X.Y` / `Output into field X.Y` / `Output creates X`. Explicit LLM input/output mapping replaces Transform shapes for LLM/agent providers.
- **Accesses** — Required boundary declaration on all Computes. Defines what content types a Compute can touch. Runtime enforces, compiler cross-checks.
- **Directive / Objective** — Two-part prompt: Directive (system prompt, strong prior) and Objective (task prompt). Replaces Strategy.
- **Trigger where clause** — `Trigger on event "X" where \`CEL\`` for event routing filters. Distinct from preconditions.
- **Mark...as** — `Mark rows where \`expr\` as "label"` semantic emphasis with ARIA attributes. Replaces Highlight.
- **Channel Actions** — `Action called "name":` with typed Takes/Returns/Requires on Channels. RPC verbs for external services.
- **Event channel sends** — `Send X to "channel"` in When event handlers.
- **Channel runtime** — Outbound HTTP/WS dispatch, inbound webhooks, action invocation, deploy config with strict validation.
- **WebSocket behavioral contract** — 7 requirements: push on create/update within 2s, no duplicates, payload is record not wrapper, no cross-content leakage, background thread delivery.
- **ContentSchema.singular** — Authoritative singular from DSL (fixes pluralization for event context).
- **ComputeShape.NONE** — For LLM/agent providers that use field wiring instead of Transform shapes.
- **Deploy config** — App-specific `{name}.deploy.json`, auto-generated by compiler, `${ENV_VAR}` substitution.

### 0.4.0 (April 2026)

- **Expression delimiter: `[bracket]` → `` `backtick` ``** — Breaking change. Backticks are unambiguous with array indices (`items[0]`).
- **Confidentiality system** — Field-level redaction, taint propagation, CEL guard, output taint enforcement.
- **Server-side Compute endpoint** — `POST /api/v1/compute/{name}` with 4 defense-in-depth checks.
- **Field redaction** — `{"__redacted": true}` markers in API responses.
- **User identity standardized**: `User.Name`, `User.Role`, `User.Scopes`.

### 0.3.0 (April 2026)

- `app_id` — compiler-managed UUID for deployment identity
- `default_expr` — CEL expressions for field defaults
- CEL replaces JEXL for all expressions

## License

Apache 2.0
