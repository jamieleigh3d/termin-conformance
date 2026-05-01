# Termin Compute Contract — Conformance Specification

**Version:** 0.9.1-draft (synthesized 2026-04-30)
**Status:** Draft — companion to `termin-runtime-implementers-guide.md`. Specifies the Compute provider category that every conforming runtime + provider pair must satisfy. The conformance pack at `tests/test_v09_compute_*.py` is the executable form of this spec.
**Audience:** Three, in order of likelihood:
1. **Provider authors** writing alternate compute providers (Bedrock LLM, OpenAI agent, local-LLM, etc.) that plug into the reference runtime via the three Compute Protocols. Most consumers will reach this surface first.
2. **Alternative runtime authors** building a Termin runtime in a different language. The Compute contract is the most behavior-rich provider category in v0.9 — three distinct contracts, a closed tool surface, a structured audit shape, and refusal semantics.
3. **App authors** whose computes invoke LLMs or agents and who need to predict what gets logged, what tool calls are permitted, and how a refusal propagates.

**Relationship to other specs:**
- `termin-ir-schema.json` defines the IR shape; the Compute contract operates over the `computes`, `content` (audit + sidecar), and `bindings.compute` parts of that IR.
- `termin-runtime-implementers-guide.md` covers the runtime's behavioral contract for Compute invocation; this spec captures the cross-runtime invariants.
- `migration-contract.md` covers schema evolution; the audit Content's `latency_ms` rename and the new BRD §6.3.4 columns are migration-classifier inputs but not in scope here.
- `compute-provider-design.md` (in the compiler repo) is the implementation-side design notes for the reference runtime; this conformance spec captures the language-level invariants that design produces.

---

## 1. Scope and Audience Framing

### 1.1 What this spec covers

When a Termin app declares one or more `Compute called "X"` blocks, the runtime must:

1. **Resolve** each compute's contract (`default-CEL` for implicit, `llm` or `ai-agent` for `Provider is "..."` declarations) and its product (from `bindings.compute["<name>"].provider`).
2. **Construct** a provider satisfying the contract's Protocol from the registry, configured with `bindings.compute["<name>"].config`.
3. **Build** a `ToolSurface` from the source's `Accesses`, `Reads`, `Sends to`, `Emits`, `Invokes` declarations (ai-agent only).
4. **Dispatch** invocations to the provider on trigger (event, schedule, manual).
5. **Gate** every tool call the provider issues against (a) the source's declared grants and (b) the effective principal's scopes — both gates must pass.
6. **Persist** an audit record matching BRD §6.3.4 for every `llm` and `ai-agent` invocation, with structured fields queryable via the CRUD surface.
7. **Capture** refusals through the sidecar `compute_refusals` Content type when an `ai-agent` calls `system_refuse`, propagate `outcome="refused"` to the caller, and discard staged outputs.
8. **Substitute principals** for service-mode (`Acts as service`) computes: the agent acts as its own principal, with roles drawn from the deploy config's identity binding.

This spec defines that contract. The shapes in §3 (registry), §4 (tool surface), §5 (audit), §6 (refusal), and §7 (Acts-as) are language-level invariants — every conforming runtime must produce the same observable behavior for the same source + deploy config + sequence of tool calls.

### 1.2 Why this spec exists

The conformance suite philosophy (per `CLAUDE.md` of this repo): *the conformance suite is the spec*. If a behavior isn't tested here, it isn't specified. Compute is the highest-risk provider category — it's the seam between the deterministic Termin core and the AI zone (Tenet 5: declared agents over ambient agents). Silent disagreement between runtimes about what an agent is allowed to do, or about what goes into the audit log, undermines the entire audit-over-authorship promise (Tenet 1).

### 1.3 The provider-author audience

Most v0.9 consumers will reuse the reference runtime entirely and write or swap a provider. In that case:

- **The Protocol surface (§3.1) is the most-read section.** Three Protocols, three surfaces, distinct method signatures.
- **The audit-record shape (§5) is the most enforced.** The runtime stamps it from provider output; the conformance pack reads it back through the CRUD surface and checks every required field.
- **The tool-surface gate (§4) is the runtime's job, not the provider's.** Provider authors do not implement gating; they receive a callback the runtime has already gated and are forbidden from bypassing it.

The runtime side of the contract (§4–§7) matters most for alternative-runtime authors. Provider authors can read it as background.

### 1.4 What this spec does not cover

- **Channel contracts** (`Sends to "X" channel`). Phase 3 declares the source-side grant grammar and gates `channel.send`/`channel.invoke_action`; Phase 4 (channel contracts spec, forthcoming) defines the four channel contracts. Calling `channel.send` from an agent before Phase 4 lands is a runtime "not yet implemented" error, not a contract violation.
- **Bedrock / OpenAI / Gemini / local-LLM products.** v0.9 ships Anthropic + stubs as first-party `llm` and `ai-agent` products. New products are post-v0.9 (BRD §11 / roadmap).
- **Domain-specific compute contracts** (geospatial, financial, etc.). Post-v0.9 per BRD §11.
- **Cost enforcement.** v0.9 captures cost in audit (when the provider reports it); enforcement is post-v0.9.
- **Cross-version migration of audit content shapes.** Covered by the migration contract; the v0.8 → v0.9 audit reshape (latency_ms rename + new columns) is in scope of `migration-contract.md` §5 not here.
- **Streaming wire format.** The reference runtime emits `compute.stream.<inv_id>.field.<name>` events; alternative runtimes may surface streaming differently. The contract-level `AgentEvent` taxonomy (§4.6) is fixed; the wire encoding is not.
- **Tiered AI-agent contracts** (sandboxed / orchestrator / etc.). The registry supports adding contracts at runtime, but v0.9 ships exactly the three documented here.

### 1.5 Tier 1 vs Tier 2 conformance

Per BRD §9.1:

- **Tier 1** (built-in providers): `default-cel`, `stub` LLM, `anthropic` LLM, `stub` ai-agent, `anthropic` ai-agent. These ship with the reference runtime and **must** pass the full conformance pack.
- **Tier 2** (third-party providers): self-certify against the same suite. The conformance pack is parameterized by adapter; running it against a non-reference runtime measures the runtime + bound provider together.

A conforming pair is `(runtime, set-of-bound-providers)`. The pack tests observable behavior through the conformance adapter (§9), not provider internals.

---

## 2. The Three Compute Contracts

Three named contracts populate the Compute category. Source declares which by the presence (or absence) of `Provider is "..."`.

| Contract | Source signature | Purpose |
|---|---|---|
| `default-CEL` | (no `Provider is` clause) | Pure expression evaluation. Synchronous, deterministic. |
| `llm` | `Provider is "llm"` + `Input from field X` + `Output into field Y` | Single-shot prompt → completion. Transform shape with model-based body. No tool surface. |
| `ai-agent` | `Provider is "ai-agent"` + `Accesses ...` (and optional `Reads`, `Sends to`, `Emits`, `Invokes`) | Multi-action autonomous behavior with closed tool surface. Streamable. |

A compute is exactly one of these three; the parser refuses any other `Provider is` value at the Compute block (it would fail registry resolution at deploy time anyway).

### 2.1 `default-CEL` invocation

```
evaluate(expression: text, bound_symbols: map<text, any>) -> any
```

Synchronous. No tool calls. No audit record (CEL evaluates server-side as part of compute body, trigger filter, event handler condition, pre/postcondition; audit is emitted by the calling site if its `audit_level` declares it). Errors raise; the runtime routes through TerminAtor.

Implicit from source. No deploy-config keying — there is exactly one registered product for `default-CEL`, and the runtime binds to it without operator declaration.

### 2.2 `llm` invocation

```
complete(directive: text, objective: text, input_value: any,
         sampling_params: map<text, any> | null) -> CompletionResult

CompletionResult:
  outcome         : "success" | "refused" | "error"
  output_value    : any                    (for outcome="success")
  refusal_reason  : text | null            (for outcome="refused")
  error_detail    : text | null            (for outcome="error")
  audit_record    : AuditRecord            (see §5)
```

Single-shot. No tool calls — no `ToolSurface` argument. Streaming supported through the wire-level event-bus (`compute.stream.<inv_id>.field.<name>` for token deltas), but the contract-level method returns a `CompletionResult` once complete.

Refusal happens entirely at the provider level: the model declines via training-time policy, the provider stamps `outcome="refused"` with a `refusal_reason`. There is no `system_refuse` tool because `llm` has no tool surface.

### 2.3 `ai-agent` invocation

```
invoke(directive: text, objective: text, context: AgentContext,
       tools: ToolSurface) -> AgentResult

invoke_streaming(directive: text, objective: text, context: AgentContext,
                 tools: ToolSurface) -> Stream<AgentEvent>

AgentContext:
  principal      : Principal               (effective principal — see §7)
  bound_symbols  : map<text, any>
  tool_callback  : (tool_name, args) -> result   (runtime-supplied; gated)

AgentEvent (closed sum type):
  | TokenEmitted{text}
  | ToolCalled{tool, args, call_id}
  | ToolResult{call_id, result, is_error}
  | Completed{result: AgentResult}
  | Failed{error: text}

AgentResult:
  outcome           : "success" | "refused" | "error"
  output_value      : any                    (for outcome="success")
  actions_taken     : List<AuditableAction>
  reasoning_summary : text | null
  refusal_reason    : text | null            (for outcome="refused")
  error_detail      : text | null            (for outcome="error")
  audit_record      : AuditRecord            (see §5)
```

Multi-action. The agent issues tool calls via `context.tool_callback`; the runtime gates each call (§4) before executing. `system_refuse` is always-available — calling it terminates the invocation with `outcome="refused"` regardless of subsequent tool calls.

The streaming form yields the same `AgentResult` packaged inside a final `Completed` event; `Failed` is emitted instead when the provider couldn't complete the invocation. Token-level streaming is via `TokenEmitted` events; tool dispatch is via `ToolCalled` + matching `ToolResult` pairs.

### 2.4 Compute shapes (cross-cutting)

All three contracts support the five compute shapes (Transform, Reduce, Expand, Correlate, Route) at the source level. The shape determines the input/output types but not the contract — a Transform compute can be `default-CEL`, `llm`, or `ai-agent`. The provider ignores shape; the runtime adapts the shape's input/output to the contract's invocation arguments.

---

## 3. Registry Surface

Compute providers register against the unified provider registry, keyed by `(Category.COMPUTE, contract_name, product_name) → ProviderRecord(factory, conformance, version, features)`.

### 3.1 Registration keys

The five Tier 1 keys that **must** be registered after `register_builtins`:

| Category | Contract | Product | Notes |
|---|---|---|---|
| `COMPUTE` | `default-CEL` | `default-cel` | The implicit product for unbound CEL evaluation. |
| `COMPUTE` | `llm` | `stub` | Scripted-response stub for tests. |
| `COMPUTE` | `llm` | `anthropic` | Anthropic single-shot completion. |
| `COMPUTE` | `ai-agent` | `stub` | Scripted-response stub for tests. |
| `COMPUTE` | `ai-agent` | `anthropic` | Anthropic agent loop. |

A conforming runtime ships all five. Alternative runtimes may register additional products (Bedrock, OpenAI, etc.) under the same contracts; those satisfy the same Protocol and pass the same per-product conformance tests.

The contract names are exact strings: `default-CEL` (mixed case), `llm` (lowercase), `ai-agent` (hyphen). Registries that accept `ai_agent` or `LLM` are non-conforming — keys are case-sensitive.

### 3.2 Deploy-config keying

`bindings.compute` is name-keyed by the source-level Compute name (snake-cased):

```json
{
  "version": "0.9.0",
  "bindings": {
    "compute": {
      "<compute-name-snake>": {
        "provider": "<product-name>",
        "config": { "<provider-specific>": "..." }
      }
    }
  }
}
```

Example for an `agent_chatbot` app with one `Compute called "reply"` declared as `Provider is "ai-agent"`:

```json
"compute": {
  "reply": {
    "provider": "anthropic",
    "config": {
      "model": "claude-haiku-4-5-20251001",
      "api_key": "${ANTHROPIC_API_KEY}"
    }
  }
}
```

Resolution rules:

1. For each compute declared in the IR, the runtime looks up `bindings.compute[<compute_snake>]`.
2. If present: registry lookup is `(COMPUTE, comp.provider, binding.provider)`. The `comp.provider` is the contract name from source (`llm` or `ai-agent`); `binding.provider` is the product name from deploy config.
3. If absent and the source has no `Provider is` clause (implicit default-CEL): registry lookup is `(COMPUTE, "default-CEL", "default-cel")`. No deploy entry needed.
4. If absent but the source has `Provider is "llm"` or `"ai-agent"`: deploy refused with a clear error pointing at the missing binding. Fail-closed.
5. If present but the keyed product is not in the registry: deploy refused with a clear error pointing at the unknown product (stub-product fallback applies — see §3.3).

**`default-CEL` does not appear in `bindings.compute`.** The contract is implicit; deploy configs that put a `default-CEL`-only compute into `bindings.compute` are non-conforming (the runtime ignores it but should warn). Conversely, every `llm` or `ai-agent` compute in the IR **must** appear in `bindings.compute` — there is no implicit default product for those contracts.

### 3.3 Stub-product fallback

When a deploy config names a product that is not registered (e.g., `provider: "bedrock"` against a runtime that only ships Anthropic):

- The runtime **may** fall back to the contract's `stub` product (`(COMPUTE, "<contract>", "stub")`) when the unknown product matches no registered factory.
- Fallback is informational, not silent: the runtime logs a warning, and the audit records emitted by the stub carry `provider_product: "stub"` (not the requested name).
- Fallback is **never** used for `default-CEL` — `default-cel` is the only product, it is always registered, and a deploy that names a different product for `default-CEL` is a hard error.

The behavior the conformance pack tests:

- A deploy bound to a registered product (e.g., `stub`) construct cleanly and serve invocations.
- A deploy bound to `anthropic` with an unresolved API key (`${ANTHROPIC_API_KEY}` left as a literal placeholder) constructs cleanly at boot — the provider only fails on actual call (BRD §6.1 fail-closed posture for late-bound config).
- A deploy bound to a non-existent product produces a deterministic outcome — either clean fallback to `stub` with a warning, or a clear refusal at deploy time. The conformance pack accepts both behaviors as conforming and tests that whichever the runtime chose, it does not crash startup or produce undefined behavior.

This is the "never crashes startup" promise: a typo in deploy config or a missing third-party SDK should not take down the deploy. The fallback path makes deterministic-test paths (stub-bound) the default for conformance fixtures.

---

## 4. Tool Surface and Gate Semantics

The tool surface is the runtime-defined set of typed callables exposed to an `ai-agent` provider through `AgentContext.tool_callback`. The set is closed: providers cannot extend it. The set the provider sees per invocation is computed from the source declarations on the Compute block.

### 4.1 What "tool" means

A **tool** is a runtime-implemented operation the agent loop can invoke. Tools have:

- A stable **name** (snake_case identifier).
- A **JSON Schema** describing inputs (the runtime exposes this to the provider).
- A **scope requirement** the effective principal must satisfy.
- A **declaration requirement** the source must explicitly grant.

The provider issues tools by calling `tool_callback(name, args)`. The runtime responds with a result dict (success) or `{"error": "..."}` (denied). The provider never has direct database, filesystem, network, or schema access — the tool surface is the only seam.

### 4.2 The closed tool surface

| Tool | Inputs (informal) | Source declaration that grants |
|---|---|---|
| `content_query` | `content_name`, optional `filters` | `Accesses <T>` or `Reads <T>` for `<T>` |
| `content_read` | `content_name`, `record_id` | `Accesses <T>` or `Reads <T>` for `<T>` |
| `content_create` | `content_name`, `data` | `Accesses <T>` for `<T>` |
| `content_update` | `content_name`, `record_id`, `data` | `Accesses <T>` for `<T>` |
| `content_delete` | `content_name`, `record_id` | `Accesses <T>` for `<T>` |
| `state_transition` | `content_name`, `record_id`, optional `machine_name`, `target_state` | `Accesses <T>` for `<T>` (NOT `Reads`) |
| `event_emit` | `event_name`, `payload` | `Emits "<event-name>"` |
| `channel_send` | `channel_name`, `payload`, optional `headers` | `Sends to "<channel-name>" channel` (Phase 4 implements) |
| `channel_invoke_action` | `channel_name`, `action`, `args` | `Sends to "<channel-name>" channel` + the channel's action grant (Phase 4 implements) |
| `compute_invoke` | `compute_name`, `args` | `Invokes "<compute-name>"` |
| `identity_self` | (none) | Always available |
| `system_refuse` | `reason` (text, required) | Always available |

The exact tool method names use **underscore form** at the wire level (`content_query`, not `content.query`). Some implementation surfaces use dot form internally; the conformance pack tests the underscore form because that is what the provider sees and what the audit `tool_calls` field records.

### 4.3 Closed-set guarantee

The provider may NOT call any tool not in §4.2. Calls to undeclared tools are denied with an error result (`{"error": "..."}`) — the runtime does not crash, but the call has no effect.

The conformance pack tests this by scripting a stub provider to call a fictitious tool name and verifies the result is an error envelope. **Tool injection is structurally impossible** — the tool surface is a runtime-supplied closure, and the agent has no other way to issue side effects.

### 4.4 Read vs write asymmetry (BRD §6.3.3)

`Accesses` grants the full Content tool set: `content_{query,read,create,update,delete}` plus `state_transition`. `Reads` grants only the read-side: `content_{query,read}`. **State tools come from `Accesses` only** — never from `Reads`. The conformance pack tests both directions:

- An agent declaring `Reads orders` calling `state_transition` on `orders` → denied.
- An agent declaring `Accesses orders` calling `state_transition` on `orders` → allowed (subject to scope).

A type appearing in both `Accesses` and `Reads` is a **parse error** (TERMIN-S044) — the grant is contradictory. The conformance pack tests the runtime-side rejection: a deploy with a contradictory pair fails to load (the IR would have failed validation at compile time, but a runtime receiving such an IR must refuse).

### 4.5 Double gating

Every tool call goes through two gates, both of which must pass:

**Gate 1 — declared in source.** The tool must appear in §4.2 AND the requested target (`content_name` for content/state tools, `channel_name` for channel tools, `event_name` for events, `compute_name` for invokes) must be in the source's grant set. Failure code: `TERMIN-A001` ("not declared").

**Gate 2 — effective principal authorized.** The principal that the agent is acting on behalf of (delegate mode) or acting as (service mode, §7) must hold the scope the tool requires. Scope requirements come from the source-level access grants on the target Content (`Anyone with "X" can update orders` → `state_transition` on orders requires `X` and the principal must have it). Failure code: `TERMIN-A002` ("not authorized").

Both gate failures yield error envelopes through the tool callback — they do not raise to the provider. The provider sees `{"error": "..."}`, not an exception. The audit log records the denied call with the deny reason and code (§5.4).

### 4.6 Streaming events

`invoke_streaming` yields `AgentEvent` instances. The five-variant taxonomy is fixed:

| Variant | Carries | Emitted when |
|---|---|---|
| `TokenEmitted{text}` | Text fragment | Provider streams a chunk of model output |
| `ToolCalled{tool, args, call_id}` | Tool name + args + correlation id | Agent issues a tool call (after gate passes) |
| `ToolResult{call_id, result, is_error}` | Result keyed by call_id | Tool execution completes |
| `Completed{result: AgentResult}` | Final agent result | Loop terminates normally |
| `Failed{error: text}` | Error string | Loop terminates abnormally |

Ordering invariants:

1. Every `ToolCalled` is followed (eventually) by exactly one `ToolResult` with the matching `call_id`.
2. Exactly one of `Completed` or `Failed` is yielded as the **last** event of any successful stream.
3. `TokenEmitted` events may be interleaved with tool calls.
4. After `Completed` or `Failed`, no further events are yielded.

The wire-level encoding (event-bus channels, SSE, WebSocket frames) is runtime-defined; the contract is the variant taxonomy and the ordering invariants.

---

## 5. Audit Record Shape (BRD §6.3.4)

**This is the load-bearing portability piece.** Every conforming runtime must produce identical audit records (modulo runtime-stamped timestamps and correlation ids) for identical inputs. App authors, security reviewers, and compliance officers query this shape across runtimes; field drift makes audit non-portable.

### 5.1 The audit Content type

Every Compute with `audit_level != none` triggers auto-generation of a Content type named `compute_audit_log_<compute_snake>` at IR-compile time. The Content has VIEW access for principals holding the scope declared by `Anyone with "X" can audit` on the source Compute block. CRUD is read-only for that role; the runtime is the only writer.

The audit Content's snake name is `compute_audit_log_<compute_snake>`, exactly. Examples:

- `Compute called "reply"` → `compute_audit_log_reply`
- `Compute called "calculate order total"` → `compute_audit_log_calculate_order_total`
- `Compute called "purge cancelled orders"` → `compute_audit_log_purge_cancelled_orders`

Audit records are queryable through the standard CRUD surface:
`GET /api/v1/compute_audit_log_<compute_snake>` (subject to the audit scope).

### 5.2 Required fields — base shape (every contract with audit_level != none)

These columns appear on the audit Content for **every** contract — `default-CEL`, `llm`, and `ai-agent`. **An audit row MUST be written for every invocation regardless of trigger path** — including manual `POST /api/v1/compute/<name>/trigger` calls for `default-CEL` computes. v0.9.0 reference runtime had a known divergence where the manual-trigger path silently dropped audit rows for default-CEL; v0.9.1 fixes this in `termin-server`'s compute_runner so every trigger path produces an audit row.

| Field | Type | Notes |
|---|---|---|
| `id` | automatic | Standard primary key. |
| `compute_name` | text | Source-level snake name. |
| `invocation_id` | text | Per-invocation correlation id. Stable across audit + sidecar. |
| `trigger` | text | `"event"`, `"schedule"`, `"manual"`, `"api"`, etc. |
| `started_at` | timestamp | Invocation start (runtime-stamped). |
| `completed_at` | timestamp | Invocation end. |
| `latency_ms` | number | Wall-clock duration. **Renamed from `duration_ms` in v0.9** (the v0.8 column is gone — migration carries existing data through the rename mapping). |
| `outcome` | enum | One of `success`, `refused`, `error`, `timeout`, `cancelled`. **`refused` was added in v0.9.** |
| `total_input_tokens` | number | Provider-reported (zero/null for non-LLM). |
| `total_output_tokens` | number | Provider-reported. |
| `trace` | text | JSON blob of the full reasoning + tool sequence (legacy v0.8 shape; preserved). |
| `error_message` | text | Free-form when `outcome="error"`. |
| `invoked_by_principal_id` | text | The actual caller's principal id. Anonymous callers stamp `anonymous:<short>` per §7.1; system-triggered runs (no caller) stamp empty string. |
| `invoked_by_display_name` | text | Caller's display name (denormalized for audit-time stability). For anonymous callers the runtime fills `Anonymous` if not otherwise provided. |
| `on_behalf_of_principal_id` | text | Delegate-mode mirrors `invoked_by_principal_id`; service mode stamps the upstream caller's id while invoked_by carries the synthesized service principal. |

### 5.3 Required fields — LLM/agent extension (BRD §6.3.4)

When the compute is `Provider is "llm"` or `Provider is "ai-agent"`, the audit Content gains these additional columns. **They MUST NOT appear on `default-CEL` audit Contents** (the conformance pack tests the negative case — CEL audits don't have them).

| Field | Type | Notes |
|---|---|---|
| `provider_product` | text | The product name from `bindings.compute["<name>"].provider` (e.g., `"anthropic"`, `"stub"`). |
| `model_identifier` | text | Provider-reported model id (e.g., `"claude-haiku-4-5-20251001"`). |
| `provider_config_hash` | text | `sha256:` + 64 hex. Hash of the resolved provider config with secret values redacted (see §5.5). |
| `prompt_as_sent` | text | Fully-assembled prompt (directive + objective + bound symbols + tool defs). May be large. |
| `sampling_params` | text (JSON) | Temperature, top_p, seed, etc. as a JSON object. |
| `tool_calls` | text (JSON list) | Structured per-call records. Empty list for `llm`. |
| `refusal_reason` | text | Populated when `outcome="refused"`; empty string when `outcome="success"` or `outcome="error"`. |
| `cost_units` | number | Provider-reported (e.g., token count). Null when unknown. |
| `cost_unit_type` | text | `"tokens"`, `"requests"`, etc. Null when unknown. |
| `cost_currency_amount` | text | Numeric string for currency cost (kept as text to preserve precision). Null when unknown. |

### 5.4 Tool-call structure (`tool_calls` field)

The `tool_calls` JSON list contains one entry per tool dispatch (including denied calls). Each entry is a JSON object with these keys:

```json
{
  "tool":       "content_query",
  "args":       { "content_name": "messages" },
  "result":     { "...": "..." },
  "latency_ms": 12,
  "is_error":   false
}
```

Denied calls (gate failures) record `is_error: true` and `result: {"error": "<reason>"}`. The audit record includes them; auditors see what the agent attempted, not just what it accomplished.

### 5.5 `provider_config_hash` semantics

The hash is `"sha256:" + hex(sha256(canonical_json(redacted_config)))`. Canonicalization:

1. Recursively sort keys.
2. Replace any value whose key matches the secret-key set — `api_key`, `api-key`, `bearer_token`, `bearer-token`, `password`, `secret`, `token` (case-insensitive prefix/suffix match) — with the literal placeholder `"<redacted>"`.
3. Serialize as compact JSON (no whitespace).
4. SHA-256 hex digest.

Properties the conformance pack tests (when run against deterministic stub providers):

- Same non-secret config → same hash.
- API key rotation (only secret value changes) → **same** hash. The hash captures *operational* config drift, not secret rotation.
- Model change, endpoint change, sampling-parameter change → **different** hash.
- Key order does not affect the hash.

The mapping from `provider_config_hash` to actual resolved config is a runtime-internal privileged audit record (BRD §6.3.4). It is NOT part of the cross-runtime contract — different runtimes may store the mapping differently or not at all. The hash itself is the cross-runtime invariant.

### 5.6 Outcome-conditional invariants

For every emitted audit record:

- `outcome="success"`: `refusal_reason` is empty/null. `error_message` is empty. `latency_ms` populated.
- `outcome="refused"`: `refusal_reason` populated with a non-empty string. `error_message` is empty. `latency_ms` populated.
- `outcome="error"`: `error_message` populated. `refusal_reason` is empty/null. `latency_ms` populated.
- `outcome="timeout"`: `error_message` describes the timeout. Other fields populated as available.
- `outcome="cancelled"`: invocation cancelled before completion (e.g., shutdown). Other fields populated as available.

Construction of an `AuditRecord` value with an inconsistent state (e.g., `outcome="refused"` and `refusal_reason` empty) is a contract violation — the dataclass-level constructors enforce this at the provider boundary.

### 5.7 Audit invariant for refusal

**Every refusal is logged regardless of `audit_level` setting.** If the source declares `Audit level: none`, normal invocations still produce no audit row, but a refusal MUST emit an audit record with `outcome="refused"` plus a corresponding `compute_refusals` sidecar row. Auditors must always see refusals.

This is a contract-level invariant, not a per-compute setting. The conformance pack tests it by configuring a `default-CEL`-but-actually-checking-an-ai-agent fixture with `audit_level: none` and confirming a refusal still surfaces.

---

## 6. Refusal Semantics

Refusal is a first-class outcome distinct from `success` and `error`. An agent calling `system_refuse(reason)` deliberately declines to perform some part of the requested work. This is structurally different from an error (system-level failure) and propagates differently to the caller.

### 6.1 Refusal as a tool call

`system_refuse` is always-available (§4.2). Its schema:

```json
{
  "name": "system_refuse",
  "description": "Refuse the requested work because it conflicts with system policy or training-time constraints. Provide a clear, structured reason.",
  "input_schema": {
    "type": "object",
    "properties": {
      "reason": { "type": "string", "description": "Why the work is being refused." }
    },
    "required": ["reason"]
  }
}
```

The conformance pack verifies the schema (name, required `reason` parameter) is present in every agent's tool list.

### 6.2 Runtime behavior on refusal

When the agent calls `system_refuse(reason)`:

1. Runtime captures the call in the agent's `tool_calls` list with full args.
2. Runtime writes a row to the sidecar `compute_refusals` Content type (§6.4).
3. Runtime aborts (or continues to natural termination of) the agent loop. No further tool calls accepted; the runtime ignores any staged writes the agent made before refusing.
4. Provider's invocation result becomes `outcome="refused"` with `refusal_reason=<reason>`.
5. Runtime emits a `compute.<compute_snake>.refused` event on the event bus carrying `{compute, invocation_id, reason, principal}`. Apps may declare event handlers to react.

The agent CAN call `system_refuse` at any point — including after partial work is done. The runtime does not commit any staged outputs from the refused invocation; rollback is the contract guarantee.

### 6.3 The `compute_refusals` sidecar

For any app with at least one `ai-agent` compute, the runtime auto-generates a Content type named `compute_refusals` at IR-compile time. Apps with no `ai-agent` computes do NOT get the sidecar.

**Required fields:**

| Field | Type | Notes |
|---|---|---|
| `id` | automatic | |
| `compute_name` | text | Source-level snake name of the refusing compute. |
| `invocation_id` | text | Joins to the audit record's `invocation_id`. |
| `reason` | text | Exact string passed to `system_refuse`. |
| `refused_at` | timestamp | Runtime-stamped. |
| `invoked_by_principal_id` | text | The principal whose request was refused (delegate-mode caller). |
| `on_behalf_of_principal_id` | text | Delegate chain target; empty for service mode. |

**Access:** the sidecar surfaces with VIEW access to principals holding the audit scope of any `ai-agent` compute in the app (the sidecar is shared across all agents). Apps MAY declare additional scopes for it; the conformance pack tests only the audit-scope grant.

**Joining:** auditors join `compute_refusals` to `compute_audit_log_<name>` via `invocation_id`. The audit row carries the full BRD §6.3.4 reproducibility shape (prompt, sampling, tool calls); the sidecar carries the structured refusal-specific fields. Both are written for every refusal.

### 6.4 Refusal envelope (returned to caller source)

When a compute refuses, the Termin-language-level response to whatever invoked it (event handler, API call, scheduled trigger) is:

```
{
  "outcome": "refused",
  "refusal_reason": "<reason from system_refuse>",
  "compute": "<compute_snake>",
  "invocation_id": "<id>"
}
```

This is **NOT an exception** — calling source must explicitly handle the refused outcome. The runtime does not raise; the caller sees a structured refusal envelope. This is the BRD §6.4 propagation rule: refusal is an outcome, not an error.

For the manual trigger endpoint (`POST /api/v1/compute/<name>/trigger`), the HTTP response is `200` with body `{"outcome": "refused", ...}` — refusal is a successful invocation that produced no output, not an HTTP error. Status `4xx`/`5xx` are reserved for system errors and authorization failures.

### 6.5 Refusal vs error vs timeout

The three non-success outcomes are distinct and not interchangeable:

| Outcome | Trigger | Decided by | Caller should |
|---|---|---|---|
| `refused` | Agent declined to perform some part of the work | Agent (via `system_refuse`) | Surface to UI, escalate to human, NOT auto-retry |
| `error` | Provider/network/SDK failure, malformed model output, etc. | Runtime | Log, possibly retry with backoff |
| `timeout` | Invocation exceeded configured budget | Runtime | Log, retry once, then surface |

The `outcome` enum captures these; consuming source distinguishes them via the `outcome` field. The conformance pack tests that the runtime produces exactly the right enum value for each cause and that the audit record's outcome-conditional invariants hold.

---

## 7. Acts-as Principal Substitution

By default, an `ai-agent` compute runs in **delegate mode**: it has no roles of its own; all authorization derives from `on_behalf_of` (the principal that triggered the compute). Audit log records "agent X acting for user Y did Z."

Source can opt into **service mode** with `Acts as service` on the Compute block:

```
Compute called "scanner":
  Provider is "ai-agent"
  Acts as service
  ...
```

Service-mode behavior:

- The agent has its own principal id (synthesized by the runtime, e.g., `service:scanner@app`).
- The agent's roles come from the deploy config's identity binding's `role_mappings` keyed by the agent's principal id.
- Tool calls are gated against the agent's own scopes — there is no `on_behalf_of`.
- Audit records carry `invoked_by_principal_id` = the runtime-synthesized id, `on_behalf_of_principal_id` = empty/null.

`Acts as delegate` is explicit-default; absent the line, mode is `delegate`.

### 7.1 Audit invariants under Acts-as

For **delegate-mode** invocations:
- `invoked_by_principal_id` = the actual principal who triggered the compute (e.g., the human user whose `messages.created` event ran the trigger).
- `on_behalf_of_principal_id` = the same as `invoked_by_principal_id`. Delegate mode means the agent acts as the upstream principal; there is no further hop in v0.9, so the two columns mirror each other.

For **service-mode** invocations:
- `invoked_by_principal_id` = the synthesized service principal.
- `on_behalf_of_principal_id` = empty/null.

#### Anonymous principals

When the upstream principal is anonymous (the caller had no
authenticated identity, or the app's only declared role is
`anonymous`), the runtime MUST synthesize a typed identifier of the
form `anonymous:<short>` rather than emitting an empty string.
The prefix `anonymous:` is the auditable type marker — operators
filter audit logs with `invoked_by_principal_id LIKE 'anonymous:%'`
to find anonymous-caller activity. The suffix is a short opaque
token derived from the invocation_id (first 8 hex chars after
stripping dashes), giving each anonymous audit row a distinct id
within the trail without claiming cross-row correlation.

This applies equally to `invoked_by_principal_id` and
`on_behalf_of_principal_id` (in delegate mode where they mirror).
A truly system-triggered run with no upstream principal at all
(scheduler hooks, startup tasks) MAY emit empty-string ids — that
case is distinguishable from anonymous because there is no caller,
not because the caller was unauthenticated.

The conformance pack tests both shapes by examining audit records emitted from a delegate-mode chatbot (one row per user-triggered invocation, principal id matches the user OR the synthesized anonymous form) and a service-mode scanner (synthesized service principal, no on_behalf_of).

### 7.2 Tool-call principal

The principal passed to the `tools.permits_*` checks (Gate 2, §4.5) is:
- Delegate mode: the `on_behalf_of` principal.
- Service mode: the agent's synthesized service principal.

A delegate-mode agent cannot escalate beyond its caller's scopes. A service-mode agent cannot exceed its declared `role_mappings`. Neither can extend the source-declared grant set (Gate 1).

---

## 8. Stub Providers

Per BRD §10, every contract ships a stub product. Stubs return scripted responses (input → fixed output), supporting deterministic tests in conformance and downstream consumer apps.

### 8.1 Stub products required

| Contract | Product | Construction config |
|---|---|---|
| `default-CEL` | `default-cel` | (the real CEL evaluator IS the deterministic implementation; no separate stub needed) |
| `llm` | `stub` | Optional `responses` map (substring → response), `default_response`, `model_identifier` |
| `ai-agent` | `stub` | Optional `default_script` (`{final_outcome, output_value, refusal_reason, tool_calls: [...]}`) |

Stub providers MUST emit valid `AuditRecord` values stamped with `provider_product: "stub"`. A scripted refusal MUST produce `outcome: "refused"` with the configured `refusal_reason`.

### 8.2 Conformance binding

The conformance suite binds compute-bearing fixtures to stub products by default to keep tests deterministic and offline. The conformance adapter's `deploy_with_agent_mock` patches the Anthropic provider with a scripted tool-call sequence — equivalent in effect to binding `provider: "stub"` with that script in deploy config.

A conforming runtime that does not ship the stub products is non-conforming. Tests cannot proceed without them.

---

## 9. Conformance Test Methodology

The conformance pack tests Compute provider behavior through the conformance adapter (§9.1) — never by direct import of runtime internals. This keeps the pack adapter-agnostic: alternative runtimes run the same tests against their own adapters.

### 9.1 Adapter surfaces used

The pack consumes these adapter surfaces:

- `adapter.deploy(fixture_path, app_name)` → `AppInfo(base_url, ir, cleanup)`. Standard deploy of a `.termin.pkg`.
- `adapter.deploy_with_agent_mock(fixture_path, app_name, tool_calls)` → `(AppInfo, results_list)`. Deploy with a scripted agent-loop mock that executes the supplied tool calls in order.
- `adapter.create_session(app_info)` → `TerminSession`. HTTP/WS session for CRUD and trigger calls.
- `session.set_role(role, user_name=...)` for principal-driven tests.
- `session.get/post/put/delete` for CRUD against audit content + manual trigger.
- `app_info.ir` for IR-shape assertions (registry resolution, tool-surface declaration, audit-content presence).

The pack does **not** import from `termin_server` or any reference-runtime internal. The conformance philosophy: tests must work against any conforming runtime via the adapter.

### 9.2 Test categories

Five files cover distinct concerns:

| File | Focus | Approx. count |
|---|---|---|
| `test_v09_compute_contract.py` | Registry resolution, IR-level contract surface, three-contract presence, deploy-config keying | 6–9 |
| `test_v09_compute_grants.py` | Tool-surface gating: read tools require Accesses ∪ Reads, write/state tools require Accesses only, undeclared content denied | 6–9 |
| `test_v09_compute_audit.py` | Audit-record shape: BRD §6.3.4 columns present, CEL lacks LLM extras, `latency_ms` rename, outcome enum | 7–10 |
| `test_v09_compute_refusal.py` | `system_refuse` schema, sidecar generation, refusal propagation through audit + sidecar, refusal envelope | 5–8 |
| `test_v09_compute_acts_as.py` | Delegate vs service mode: audit `invoked_by` / `on_behalf_of` stamping, default-is-delegate | 4–6 |

Total target: ~30–40 tests.

### 9.3 Fixtures used

The pack reuses existing v0.9 fixtures rather than introducing new `.termin` sources:

- `compute_demo` — five `default-CEL` computes with audit, audit scope `orders.admin`. Drives §3 registry tests, §5 base-shape audit tests for CEL, §5.7 CEL-lacks-LLM-extras.
- `agent_simple` — one `llm` compute (`complete`), audit scope `agent.use`, anonymous role. Drives §5 LLM-extras audit tests.
- `agent_chatbot` — one `ai-agent` compute (`reply`), audit scope `chat.use`, anonymous role. Drives §4 gate tests, §6 refusal tests, §7 delegate-mode tests via `deploy_with_agent_mock`.
- `security_agent` — two `ai-agent` computes (`scanner`, `remediator`), service-mode declared. Drives §7 service-mode tests (IR-shape assertions; not driven end-to-end because the provider is bound to live Anthropic in the deploy config and isn't mock-friendly without rebinding).

Existing fixtures already carry the v0.9 audit content shape. The pack does not regenerate fixtures; the release script does that.

### 9.4 What "conforming" means for Compute

A (runtime, provider-set) pair is conforming for Compute if:

- The five Tier 1 registry keys (§3.1) are populated after `register_builtins`.
- The contract resolution rules (§3.2, §3.3) produce the documented behavior — including stub-product fallback or clean refusal for unknown products.
- The tool surface gate (§4.5) denies undeclared tool calls with error envelopes; never crashes; records denials in audit.
- Every emitted audit record has the BRD §6.3.4 shape exactly (§5.2 + §5.3); CEL audits lack the LLM extras (§5.3 negative case).
- `system_refuse` is in every agent's tool list with the documented schema (§6.1).
- Apps with at least one `ai-agent` compute have the `compute_refusals` sidecar Content (§6.3); apps without any do not.
- A refused invocation produces an audit row with `outcome="refused"` AND a sidecar row with the matching `invocation_id` AND an event-bus signal AND a `200`-with-refusal-envelope HTTP response from the manual trigger endpoint.
- Delegate-mode agents stamp `invoked_by_principal_id` from the triggering caller; service-mode agents stamp from the synthesized service principal (§7.1).

A pair that fails any of the above is non-conforming for Compute. Operators decide whether to deploy a partially-conforming pair in their environment based on which invariants matter to their compliance posture.

---

## 10. Out of Scope (recap)

Recognized as future work but not part of v0.9 Compute:

- **Channel contract runtime** (Phase 4 / channels-contract.md, forthcoming). Phase 3 ships the source-side `Sends to "X" channel` grant grammar and the gate; Phase 4 implements `channel_send` / `channel_invoke_action` and the four channel contracts.
- **Bedrock / OpenAI / Gemini / local-LLM products.** v0.9 ships Anthropic + stubs only.
- **Tiered AI-agent contracts** (sandboxed agent, orchestrator agent, etc.) — post-v0.9 / `ContractRegistry.register_contract` supports them at runtime but no Tier 1 product is shipped.
- **Cost enforcement.** Audit captures cost; enforcement is post-v0.9.
- **Provider-side full-CEL pushdown.** Runtime keeps doing residual CEL evaluation in v0.9.
- **Multi-step orchestration patterns beyond `compute.invoke` chaining.** Post-v0.9.
- **Escalation as a language construct.** State machines + scopes already express it (compute-provider-design.md §3.13).
- **Refusal-with-partial-output.** v0.9 discards staged outputs on refusal; future versions may add a "refused-with-checkpoint" semantics.

---

*End of compute contract spec.*
