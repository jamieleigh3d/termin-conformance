# Termin Conversation Field Contract — Conformance Specification

**Version:** 0.9.2-draft (synthesized 2026-05-04)
**Status:** Draft — companion to `compute-contract.md` and `termin-runtime-implementers-guide.md`. Specifies the v0.9.2 conversation field surface that any conforming runtime + ai-agent provider pair must satisfy. The conformance pack at `tests/test_v092_conversation_field.py` is the executable form of this spec.
**Audience:** Three, in order of likelihood:
1. **Provider authors** writing alternate ai-agent providers (Bedrock, OpenAI, local-LLM) that handle the new `AgentContext.conversation` field. The §11.4 mapping table they implement is the canonical contract; the pack tests the observable result.
2. **Alternative runtime authors** building a Termin runtime in a different language. The conversation field type, the Append CRUD verb, the `<content>.<field>.appended` event class, and the auto-write-back path are the v0.9.2 surface they need to mirror exactly so chat apps run without reauthorship.
3. **App authors** whose computes use `Conversation is X.Y` and who need to predict what gets persisted, what the agent sees, and how a refusal renders.

**Relationship to other specs:**
- `compute-contract.md` covers the three Compute provider Protocols (default-CEL / llm / ai-agent). This spec extends the ai-agent surface with conversation-context delivery and auto-write-back; the original Protocol shape is unchanged.
- `termin-ir-schema.json` defines the IR shape; this spec operates over `ContentSchema` (the `conversation` base type), `ComputeSpec.conversation_source`, `EventSpec.actions` (When-rule Append actions), and `RouteSpec.kind == APPEND`.
- `termin-runtime-implementers-guide.md` covers the runtime's general behavioral contract; this spec captures the cross-runtime invariants for the conversation surface.
- The compiler-side tech design for v0.9.2 (`termin-v0.9.2-conversation-field-type-tech-design.md`) is the implementation-side design notes for the reference runtime; this conformance spec captures the language-level invariants that design produces.

---

## 1. Scope and Audience Framing

### 1.1 What this spec covers

When a Termin app declares one or more `conversation` fields and one or more ai-agent computes that wire `Conversation is X.Y`, the runtime must:

1. **Persist** appended entries on the conversation field in source order, each with the canonical metadata fields (id, kind, body, created_at, appended_by_principal_id, plus optional per-kind discriminators like type, source, parent_id, tool_call_id, tool_name, tool_args, attachments).
2. **Validate** the kind on append against the closed enum `{user, assistant, tool_call, tool_result, system_event}`.
3. **Generate** UUIDv7 entry ids on append.
4. **Publish** a `<content>.<field>.appended` event whenever an entry is appended (REST or WebSocket path), with the documented payload shape.
5. **Materialize** the conversation field into provider-native shape via the §11.4 canonical mapping when an ai-agent compute with a `Conversation is X.Y` source declaration fires. For Anthropic providers, that's the messages array described in §3.4 below.
6. **Pass** the materialized conversation to the provider through `AgentContext.conversation` (Protocol-level) so providers that consume the field see the pre-translated shape and don't reimplement the mapping.
7. **Auto-write-back** the agent's actions per §11.5 of the design — final assistant text, tool_call entries, tool_result entries — each with `parent_id` set to the triggering user entry's id.
8. **Strip `set_output`** from the tool surface on the conversation-mode dispatch path, because conversation-mode agents communicate by ending their turn naturally; declaring `Output into field` alongside `Conversation is` is a compile-time error (TERMIN-S061).
9. **Substitute** the WARN-level audit log entry as the audit-trail surface for refusals (the v0.9.1 `compute_refusals` sidecar Content type is retired in v0.9.2 — see §6 below).
10. **Append** a `kind: "assistant", type: "refusal"` entry to the conversation field on refusal, parent-linked to the triggering user entry, so the chat surface can render the refusal inline at source position.

This spec defines that contract. The shapes in §3 (entry shape), §4 (Append verb), §5 (event payload), §6 (refusal surfaces), and §7 (kind → Anthropic mapping) are language-level invariants — every conforming runtime must produce the same observable behavior for the same source + deploy config + sequence of appended entries.

### 1.2 Why this spec exists

The conformance suite philosophy (per `CLAUDE.md` of this repo): *the conformance suite is the spec*. If a behavior isn't tested here, it isn't specified.

The conversation field is the v0.9.2 collapsing of two prior patterns — the v0.9.1 `messages` content type with a tool-using ai-agent loop, and a separate "agent reply field" — into one canonical surface that any chat-shaped app can use without authoring its own message storage. Silent disagreement between runtimes about which mappings happen, when entries get parent_ids, or whether refusal is in the field or out of it would undermine the audit-over-authorship promise (Tenet 1) and break cross-runtime portability of chat apps.

### 1.3 What this spec does not cover

- **The chat presentation contract.** `Show a chat for X.Y` rendering is per `presentation-contract.md` and the chat provider's deploy config — convention-not-configuration per §14 of the v0.9.2 design.
- **Conversation read pagination.** v0.9.2 reads the whole field via the standard CRUD GET. Pagination is deferred (see design §21).
- **Per-entry update or delete.** Out of scope for v0.9.2 (no use case yet — design §21).
- **OpenAI / Bedrock conversation-mode mapping.** v0.9.2 conformance is Anthropic-shape; the §11.4 mapping is Anthropic-canonical. Other providers can be added per provider-author audience but aren't gated by this spec's tests in v0.9.2.
- **Hierarchical context-window summarization** (a projection layer that runs before materialization to keep older turns within budget). Reserved for v0.9.3+ per design §21.
- **Optional `purpose` field on tool entries** for short display text. v0.9.3+ per design §21; not part of v0.9.2 conformance.

### 1.4 Tier 1 vs Tier 2 conformance

Per BRD §9.1:

- **Tier 1** (built-in providers): `anthropic` ai-agent. Ships with the reference runtime and **must** pass the full conformance pack including the conversation surface.
- **Tier 2** (third-party providers): self-certify against the same suite. A provider that doesn't claim conversation support can declare so (the `AgentContext.conversation` field is `Optional` per `compute_contract.py`); its ai-agent computes must then use the legacy triggering-record prompt path. Tier-2 conversation-mode conformance opts in by ignoring nothing in §3–§7.

A conforming pair is `(runtime, set-of-bound-providers)`. The pack tests observable behavior through the conformance adapter, not provider internals.

---

## 2. The `conversation` base type

Source declares a conversation field using the `conversation` base type:

```
Content called "chat_threads":
  Each chat_thread has a conversation which is conversation
```

Storage is JSON (the underlying field is a JSON-array column carrying the entry list). The runtime validates entry shape on append, materializes on agent invocation, and surfaces the raw value on read. Conformance assertion: the field appears in the IR's `ContentSchema.fields` with `business_type == "conversation"` (or the runtime's equivalent schema annotation), and read endpoints return a JSON array (or stringified JSON array) of entry objects.

---

## 3. The canonical entry shape

### 3.1 Required fields (every entry)

Every entry persisted on a conversation field has at minimum:

| Field | Type | Source |
|-------|------|--------|
| `id` | string (UUIDv7) | runtime-generated on append |
| `kind` | string (one of the closed enum) | caller-supplied; runtime-validated |
| `body` | string | caller-supplied (required) |
| `created_at` | string (ISO 8601 with timezone) | runtime-stamped |
| `appended_by_principal_id` | string | runtime-stamped from the appending principal |

### 3.2 Closed kind enum

Exactly five values are accepted on append:

```
user, assistant, tool_call, tool_result, system_event
```

Any other kind value MUST be rejected with a 400-class error on the REST surface (the reference runtime returns HTTP 400 with `code == "validation_error"`). The kind enum is closed because the §11.4 mapping table is also closed; opening it would break the runtime's ability to translate to provider-native shape.

### 3.3 Optional per-kind fields

The runtime accepts and persists the following optional fields when the caller supplies them; the runtime does not validate their structure beyond JSON-passability. Missing fields are absent on the persisted entry (not null).

| Field | Per-kind purpose |
|-------|------------------|
| `type` | Free-form per-kind sub-discriminator. v0.9.2 documents exactly one value: `assistant.type == "refusal"` (set by the runtime on the refusal-as-assistant entry per §6). All other kinds reserve the field for future use (see design §21 — `purpose` on tool entries is a v0.9.3+ candidate). |
| `source` | For `system_event` entries, the originating subsystem (e.g., `OVERSEER`). The materializer uses this in the source-prefix wrapper per §7.4. |
| `parent_id` | The id of the entry that triggered this one. Set by the runtime on every auto-write-back entry (§5.5) to point at the user entry that started the turn. Optional for caller-supplied entries. |
| `tool_call_id` | Provider-supplied id linking a `tool_call` to its `tool_result`. Required on both kinds for the materializer's tool-linkage validation (§7.5). |
| `tool_name` | The tool the agent called, on `tool_call` entries. |
| `tool_args` | The args the agent supplied to the tool, on `tool_call` entries. JSON-passable. |
| `attachments` | List of attachment descriptors on `user` entries. Each has at least `media_type` and `source` (Anthropic-shape). The materializer turns these into `image` / `document` content blocks per §7.3. |

### 3.4 Anthropic-shape materialization output (provider-native form)

The materialization output for an Anthropic provider is a list of message dicts with `role` ∈ `{user, assistant}` and `content` ∈ `list[block]`. Each block is one of:

- `{"type": "text", "text": <str>}`
- `{"type": "image", "source": {<Anthropic source dict>}}`
- `{"type": "document", "source": {<Anthropic source dict>}}`
- `{"type": "tool_use", "id": <str>, "name": <str>, "input": <dict>}`
- `{"type": "tool_result", "tool_use_id": <str>, "content": <str>, "is_error": <bool, when true>}`

The full mapping rules are in §7. The runtime hands this list to the provider through `AgentContext.conversation.messages`; the provider passes it (possibly transformed for non-Anthropic services) to its underlying SDK.

---

## 4. The Append CRUD verb

### 4.1 Source-level grammar

```
Content called "chat_threads":
  Each chat_thread has a conversation which is conversation
  Anyone with "chat.use" can append to chat_threads.conversation
```

The dot notation matches every other field reference in v0.9.2 (`Conversation is X.Y`, `Trigger on event "X.Y.appended"`, `Append to X.Y as ...`). Plural and singular forms of the parent content both resolve.

### 4.2 REST endpoint

`POST /<resource>/{id}/<field>:append` — request body is the entry payload (kind + body required, optional fields per §3.3), response is the persisted entry shape (with runtime-stamped id, created_at, appended_by_principal_id), HTTP 201 on success.

Error surfaces:
- HTTP 400 with `code == "validation_error"` for invalid kind, missing body, malformed JSON.
- HTTP 404 for parent-record-not-found OR row-filter-rejected (their_own ownership check failure — ownership is not allowed to leak existence).
- HTTP 403 for missing scope (per the standard CRUD permission gate).

### 4.3 WebSocket frame format (parity with REST)

The streaming protocol's inbound frame for append:

```json
{"type": "append", "resource": "<content_snake>", "id": "<record_id>",
 "field": "<field_snake>", "payload": {"kind": "...", "body": "..."}}
```

Same validation, same permission gate, same event publication as the REST path. The REST handler and WS frame handler share the runtime's `_do_append` helper (or equivalent) to guarantee no behavioral drift.

### 4.4 Source-level Append action (When-rules)

`When` rules support an `Append to X.Y as "<kind>" with body \`<expr>\`` action:

```
When `appended_entry.kind == "user" && record.message_count >= 3`:
  Append to chat_threads.conversation as "system_event" with body `"User has been idle"`
```

The runtime evaluates `body` (CEL) against the bound symbols (record + appended_entry + standard envelope), constructs the entry payload, and calls the same `_do_append` path. The action MUST publish the same `<content>.<field>.appended` event so listener computes downstream see the When-rule's append the same way they see a user-driven append.

---

## 5. The `<content>.<field>.appended` event class

### 5.1 Channel id

`content.<content_snake>.<field_snake>.appended`

Field-specific so subscribers can react to conversation activity on one column without false positives from other column updates.

### 5.2 Payload shape

Every appended event carries (at minimum):

| Field | Source |
|-------|--------|
| `type` | `<content_snake>_<field_snake>_appended` (legacy compatibility marker) |
| `channel_id` | as above |
| `content_name` | parent content's snake_case name |
| `field_name` | conversation field's snake_case name |
| `record_id` | parent record's id |
| `record` | parent record after the append (post-update snapshot) |
| `appended_entry` | the new entry (with all stamped metadata) |
| `triggered_at` | matches `appended_entry.created_at` |
| `invoked_by_principal_id` | matches `appended_entry.appended_by_principal_id` |
| `trigger_kind` | `"crud-append"` |

### 5.3 Trigger predicate binding

CEL expressions in `Trigger on event "<content>.<field>.appended" where ...` MUST receive `appended_entry` and `record` in scope alongside the standard envelope fields. Predicates like `appended_entry.kind == "user"` and `record.message_count >= 3` work without additional source-level wiring.

### 5.4 Listener dispatch

Both `When` rules (event handlers) and `Compute` blocks with `Trigger on event "X.Y.appended"` are dispatched on every appended event; the trigger predicate gates entry. Computes that match dispatch through the runtime's compute scheduler the same way create/update/delete-driven computes do.

### 5.5 Auto-write-back attribution

When a conversation-mode ai-agent compute auto-writes its turn back to the field (§7.6), the `parent_id` field on each written entry MUST be the `id` of the user entry from the `appended_entry` that triggered the compute. Reviewers reconstruct turn boundaries by walking parent_id; conformance asserts the linkage holds across multi-turn conversations.

---

## 6. Refusal surfaces

`system.refuse(reason)` is a closed always-available tool. When an ai-agent provider invokes it during an invocation, the runtime MUST:

1. **Capture** the reason and terminate the agent loop (no further provider calls for this invocation).
2. **Set** the invocation outcome to `"refused"` and propagate that to any caller awaiting the AgentResult.
3. **Write a WARN-level audit log entry** with at minimum: `compute_name`, `invocation_id`, `reason`, `refused_at`, `invoked_by_principal_id`, `on_behalf_of_principal_id`. This is the **audit-trail surface** — operations dashboards and reflection queries read from here.
4. **Append a conversation entry** to the compute's `conversation_source` field of `kind: "assistant", type: "refusal", body: <reason>` with `parent_id` set to the triggering user entry's id. This is the **chat surface** — providers render it inline at source position, distinguished as a refusal but rooted in the assistant's voice.

**The `compute_refusals` sidecar Content type from v0.9.1 / Phase 3 slice (e) is retired in v0.9.2.** Conforming v0.9.2 runtimes MUST NOT auto-generate it. Apps with at least one ai-agent compute now produce only the audit Content (per `compute-contract.md` §5) and, for conversation-mode computes, the in-field assistant/refusal entry. Reflection queries that previously hit the sidecar must migrate to the audit surface (see CHANGELOG migration note).

---

## 7. Canonical kind → Anthropic mapping (the materialization contract)

Verified against the official Anthropic API docs ([Tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview), [Vision](https://platform.claude.com/docs/en/build-with-claude/vision), [PDF support](https://platform.claude.com/docs/en/build-with-claude/pdf-support)).

### 7.1 Per-kind translation

| Termin kind | Anthropic role | Anthropic content block(s) |
|-------------|----------------|----------------------------|
| `user` | `user` | `{"type": "text", "text": <body>}` plus image/document blocks for any attachments per §7.3 |
| `assistant` | `assistant` | `{"type": "text", "text": <body>}`. The `type == "refusal"` discriminator is **not** sent to Anthropic — refusal-type assistant entries map identically to response-type ones; the discrimination is for Termin's audit and chat rendering only. |
| `tool_call` | `assistant` | `{"type": "tool_use", "id": <tool_call_id>, "name": <tool_name>, "input": <tool_args>}` |
| `tool_result` | `user` | `{"type": "tool_result", "tool_use_id": <tool_call_id>, "content": <body>, "is_error": <true if outcome was error, else absent>}` |
| `system_event` | `user` | `{"type": "text", "text": "[" + source + "] " + <body>}` (the source-prefix wrapper makes the in-band context distinguishable from real user input) |

### 7.2 Adjacent-role merging

Anthropic requires alternating user/assistant roles in the messages array; consecutive entries that map to the same role MUST be merged into one message with multiple content blocks. The materializer handles this; authors and agents don't think about it. Conformance asserts:

- Two adjacent user entries → one user message with two text blocks.
- An assistant entry followed by a tool_call entry → one assistant message with `[text, tool_use]` blocks.
- A user entry followed by a system_event entry → one user message with two text blocks (the second prefixed `[<source>]`).

### 7.3 Attachments rule

Image and document blocks ride alongside the text block in the same message's content array. Multiple attachments fan out as multiple content blocks within the one message. Image blocks (`media_type` starting `image/`) become `{"type": "image", "source": <as-supplied>}`; PDF blocks (`media_type == "application/pdf"`) become `{"type": "document", "source": <as-supplied>}`. Other media types are dropped silently in v0.9.2 — append-time validation (deferred to a future slice) will reject them upstream.

### 7.4 system_event source prefix

`system_event` entries carry a `source` field; the materializer wraps the body as `[<source>] <body>`. Default source label when missing is `system`.

### 7.5 Tool linkage validation

Every `tool_result` entry MUST have a `tool_call_id` that matches a preceding `tool_call` entry in the same conversation. Orphan `tool_result` entries cause materialization to raise (the reference runtime translates this to an `AIProviderError` and the invocation fails — the field has bad data the runtime can't translate into a valid provider call). Conformance asserts both the positive case (matched linkage materializes cleanly) and the negative case (unmatched linkage raises).

### 7.6 Auto-write-back ordering

The runtime auto-writes the agent's actions in source order:

- **For each tool call the agent made on a turn** → one `kind: "tool_call"` entry with `tool_call_id` from the provider's response, `tool_name`, `tool_args`, and `body` set to `"<tool_name>(<json args>)"` (the structured fields hold the data; body is the at-a-glance summary). v0.9.2 ships no truncation on body; v0.9.3+ adds an optional `purpose` field for short display per design §21.
- **For each tool result returned by the runtime to the agent** → one `kind: "tool_result"` entry linked by `tool_call_id`, with `body` set to the result text. `is_error: true` on tool execution failures.
- **For the agent's final assistant text on natural turn end** → one `kind: "assistant"` entry (no `type` field) with the text in `body`.

All entries written by the auto-write-back pipeline carry the same `parent_id` (the user entry that triggered the agent), so reviewers can reconstruct turn boundaries.

---

## 8. Compile-time validation (cross-runtime invariants)

These are compile-time errors the runtime is NOT required to catch (the compiler does), but conformance assertions verify the IR shape that lands at the runtime is well-formed:

- **TERMIN-S057** (Conversation + Accesses on same content): a compute's IR will not carry both `conversation_source[0] == X` AND `accesses` containing `X`. Runtimes can rely on the absence.
- **TERMIN-S058** (Conversation requires matching .appended trigger): a compute's IR carrying `conversation_source = [X, Y]` will have `trigger == "event \"X.Y.appended\""`. Runtimes can rely on the alignment.
- **TERMIN-S061** (Conversation + Output into field conflict): a compute's IR will not carry both `conversation_source` AND `output_fields`. Runtimes don't need to dispatch the legacy set_output path on conversation-mode computes.

---

## 9. Backwards compatibility

- **Existing computes without `conversation_source` continue to work unchanged.** The legacy triggering-record-as-user-message prompt path is the fallback when a compute has no `Conversation is` declaration.
- **Existing apps with the v0.9.1 messages-collection pattern continue to compile and run.** `examples/agent_chatbot_legacy.termin` is the reference example for this case.
- **Apps with at least one ai-agent compute no longer auto-generate `compute_refusals`.** This is a forward-incompatible change: a v0.9.2 runtime running against a v0.9.1-shaped database with a `compute_refusals` table will leave that table untouched (no reads, no writes); apps that read the sidecar via a CEL access surface will need to migrate to the audit surface (per §6 above).

---

## 10. Acknowledgments

The two-tier (audit log + in-field entry) refusal design is the resolution of JL's Wave 3 callout (2026-04-30): "audit log should be enough; let's go with B retire the sidecar." The §11.4 mapping table is the resolution of the design pass that made the canonical kind → Anthropic mapping convention rather than per-compute configuration. Both are recorded in the v0.9.2 design doc (`termin-v0.9.2-conversation-field-type-tech-design.md`); this spec is their conformance projection.
