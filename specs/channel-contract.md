# Termin Channel Provider Contract — Conformance Specification

**Version:** 0.9.1-draft (synthesized 2026-04-30)
**Status:** Draft — companion to BRD #1 §6.4 (Channel Provider System) and
the design notes in `termin-compiler/docs/channel-provider-design.md`.
The conformance test pack at `tests/test_v09_channel_*.py` is the
executable form of this spec.

**Audience:** Three, in order of likelihood:

1. **Provider authors** writing channel providers (a Slack messaging
   provider, an SES email provider, a third-party webhook signer)
   that plug into the reference runtime via one of the four channel
   `Protocol`s. Most consumers of this spec — extending Termin
   through a provider is the v0.9 extension surface.
2. **Alternative runtime authors** building a Termin runtime in a
   different language or on a different stack. The binding-resolution
   and dispatch invariants in §3 + §4 are the most important sections
   for them — those rules keep the apps portable.
3. **App authors** declaring `Channel called "X"` blocks. Knowing
   which actions belong to which contract, and what failure mode the
   runtime gives them, tells them what their `.termin` source can
   say and what their deploy config must wire up.

**Relationship to other specs:**

- **BRD #1 §6.4** declares the four channel contracts at the language
  level. This document captures the runtime invariants every conforming
  (runtime, provider) pair must satisfy.
- `termin-runtime-implementers-guide.md` covers identity, storage,
  routing, etc.; channels are the externally-facing slice and live
  here.
- `termin-package-format.md` defines `.termin.pkg`; channel specs travel
  in the IR like any other top-level entity (see `channels[]` in
  `termin-ir-schema.json`).
- `migration-contract.md` and `presentation-contract.md` are precedent
  documents — same audience framing, same fail-soft / fail-closed
  language.

---

## 1. Scope and Audience Framing

### 1.1 What this spec covers

When a Termin app declares an external channel — `Channel called "X"
with Provider is "<contract>"` — a conforming runtime must:

1. **Recognize** the four canonical contract names: `webhook`, `email`,
   `messaging`, `event-stream`. Each carries a specific operation
   signature and action vocabulary; runtime dispatch MUST observe them
   per §2.
2. **Resolve** the deploy config's `bindings.channels.<channel-name>`
   entry, look up `(Category.CHANNELS, contract, product)` in the
   provider registry, and instantiate one provider per channel. The
   registry surface and the binding shape are §3.
3. **Dispatch** outbound sends through the bound provider, capturing
   exceptions per the channel's declared `failure_mode` (§5).
4. **Auto-route** inbound traffic. A channel with `direction:
   inbound` (or `bidirectional`) and a non-empty `carries_content`
   MUST register `POST /webhooks/<channel-snake-name>` and persist
   the validated payload as a record of `carries_content` (§6).
5. **Refuse to start** in strict mode when an outbound channel
   declares a `provider_contract` but has no deploy binding. This is
   the conformance "fail-closed" promise — see §4.

This spec defines that contract. It is the runtime side only —
**compiler-side error codes (`TERMIN-S026`/`S027`/`S028`/`S029`)
stay in the compiler** and are documented in the compiler repo;
this spec assumes a conforming compiler has produced an IR whose
`channels[].provider_contract` and `channels[].failure_mode` are
already validated.

### 1.2 Why this spec exists

Per the conformance suite philosophy (`CLAUDE.md`): *the conformance
suite is the spec*. Channel providers are the language's
externally-facing surface — a divergence between runtimes here is a
divergence in what an app can do at deploy time, not just an
implementation curiosity. A Termin app whose Slack-bound channel
delivers cleanly on the reference runtime but silently swallows
sends on a third-party runtime is broken in a way that the
language must rule out.

### 1.3 The provider-author audience

The v0.9 extension model makes the provider the natural surface.
A consumer who wants Termin-on-Slack writes a `MessagingChannelProvider`
implementation and registers it; they do not write a runtime. The
reference runtime + their provider is the more common deployment shape.

Two implications:

- **The four `Protocol` shapes in §2 are the most-read sections.**
  They are also the most enforced — every provider gets validated
  against its declared Protocol via `isinstance` (the Protocols
  are `runtime_checkable`).
- **Auth / scope checks are the runtime's job, not the provider's.**
  Per BRD §6.4.5, providers receive only authorized calls.
  The runtime checks the source's `Requires "<scope>" to send` /
  `Requires "<scope>" to invoke` clauses BEFORE invoking the
  provider. A provider that performs its own scope check is
  layering — and a provider that bypasses the runtime's check is
  non-conforming.

The runtime side of the contract (§3-§7) matters too — but most
provider authors only care about it as background context. They
are not implementing it.

### 1.4 What this spec does not cover

- **The internal real-time channel layer** (`channel_ws.py` in the
  reference runtime). That serves cross-boundary Termin-to-Termin
  traffic via the distributed runtime; it is not a channel
  contract. Channels in source with `direction: internal` and no
  `provider_contract` use that layer; they fall outside this spec.
- **The legacy v0.8 `channels:` top-level deploy config shape.**
  v0.9 explicitly retires it (§3.5). A conforming runtime MUST
  ignore top-level `channels:` and read only from
  `bindings.channels`.
- **The grammar of `Channel called "X"`.** The compiler validates
  the source; the IR shape it produces is what the runtime sees.
  See `termin-ir-schema.json` for the JSON shape of `channels[]`.
- **Failure modes beyond `log-and-drop` in v0.9.0.** The
  `surface-as-error` and `queue-and-retry` modes parse and lower
  correctly in v0.9.0, but the v0.9.0 reference runtime always
  uses log-and-drop at runtime. **v0.9.1 implements
  `surface-as-error`** (the dispatcher re-raises ChannelError to
  the caller when the provider raises) and the conformance pack
  asserts the deterministic shape (§5.3). **`queue-and-retry`**
  (renamed from `queue-and-retry-forever` to reflect the v0.10
  design that bounds retry duration) remains a grammar
  placeholder in v0.9.x; full implementation lands v0.10 with
  exponential backoff + a dead-letter table after a configurable
  max-retry-hours window (default reasonable, max 24h). The
  conformance pack §5.4 SKIPS the queue-and-retry semantic test
  with a documented v0.10 deferral marker.
- **Real provider products** (real Slack, real SES, real Twilio).
  The conformance pack tests the contract surface against the
  reference stub products. A conforming third-party product
  passes the same Protocol + dispatch tests, plus its own
  product-specific integration tests outside the conformance
  pack.

---

## 2. The Four Channel Contracts

The Channel category has four named contracts. Each has a distinct
operation signature; each gets its own `Protocol`.

```
(channels, "webhook")      → WebhookChannelProvider
(channels, "email")        → EmailChannelProvider
(channels, "messaging")    → MessagingChannelProvider
(channels, "event-stream") → EventStreamChannelProvider   (stub deferred)
```

There is no common `ChannelProvider` base type. The kwarg shapes
diverge enough (webhook takes `body + headers`; email takes
`recipients + subject + body`; messaging takes `target +
message_text + thread_ref`) that any common base would have to use
`**kwargs` and lose static type safety. Dispatch is by contract
name, not by `isinstance` against a common base.

### 2.1 Shared data shapes

Every conforming runtime MUST expose:

```python
@dataclass(frozen=True)
class ChannelSendResult:
    outcome: str           # "delivered" | "failed" | "queued"
    attempt_count: int = 1
    latency_ms: int = 0
    error_detail: Optional[str] = None
    audit_record: Optional[ChannelAuditRecord] = None

@dataclass(frozen=True)
class ChannelAuditRecord:
    channel_name: str
    provider_product: str
    direction: str         # "outbound" | "inbound"
    action: str            # e.g., "send", "post", "send_message"
    target: str            # resolved target (URL, channel name)
    payload_summary: str   # truncated body
    outcome: str           # "delivered" | "failed" | "queued"
    attempt_count: int
    latency_ms: int
    invoked_by: Optional[str] = None
    cost: Optional[Mapping[str, Any]] = None

@dataclass(frozen=True)
class MessageRef:
    id: str                            # platform-internal message id
    channel: str                       # platform channel name/id
    thread_id: Optional[str] = None
```

`ChannelSendResult.outcome` and `ChannelAuditRecord.outcome` MUST be
restricted to the literal triple `("delivered", "failed", "queued")`.
Construction with any other value MUST raise `ValueError`.
Similarly, `ChannelAuditRecord.direction` MUST be restricted to
`("outbound", "inbound")` — `"bidirectional"` is a channel-level
label, not a per-record direction; an inbound message on a bidirectional
channel produces an audit record with `direction="inbound"`.

These restrictions are validated at dataclass `__post_init__` time.
Conformance tests construct records with bad values and assert
`ValueError`.

### 2.2 `WebhookChannelProvider`

```python
@runtime_checkable
class WebhookChannelProvider(Protocol):
    async def send(
        self,
        body: Any,
        headers: Optional[Mapping[str, str]] = None,
    ) -> ChannelSendResult:
        ...
```

Runtime invariants:

- The destination URL, timeout, retry policy, and auth headers live
  in **provider config**, never in `send()` args. The leak-free
  principle (BRD §5.1) is enforced by the contract surface itself.
- `send()` MUST be `async`. The runtime awaits it from an asyncio
  task; a synchronous `send()` is non-conforming.
- A successful POST resolves to `outcome="delivered"`. A
  non-2xx-after-retries resolves to `outcome="failed"` (the
  provider should populate `error_detail`). A provider that
  implements durable queuing MAY return `outcome="queued"`; the
  reference stub never does.
- `audit_record` SHOULD be populated. The runtime treats absence
  as best-effort but tests assert presence on the stub products.

### 2.3 `EmailChannelProvider`

```python
@runtime_checkable
class EmailChannelProvider(Protocol):
    async def send(
        self,
        recipients: Sequence[str],
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        attachments: Optional[Sequence[Any]] = None,
    ) -> ChannelSendResult:
        ...
```

Runtime invariants:

- `recipients` is a sequence of resolved email addresses. The
  runtime resolves `Recipients are <role>` source clauses to
  concrete addresses via principal claims **before** calling the
  provider. The provider receives strings; it never sees a role
  reference.
- `html_body=None` is a plain-text-only message. When supplied,
  providers SHOULD send `multipart/alternative`. The conformance
  stub honors both shapes without dispatching format negotiation.
- `attachments=None` and `attachments=()` MUST be observably
  identical. The stub normalizes `None` to `[]`.

### 2.4 `MessagingChannelProvider`

```python
@runtime_checkable
class MessagingChannelProvider(Protocol):
    async def send(
        self,
        target: str,
        message_text: str,
        thread_ref: Optional[str] = None,
    ) -> MessageRef:
        ...

    async def update(self, message_ref: str, new_text: str) -> None:
        ...

    async def react(self, message_ref: str, emoji: str) -> None:
        ...

    async def subscribe(
        self,
        target: str,
        message_handler: Callable,
        reaction_handler: Optional[Callable] = None,
    ) -> Subscription:
        ...
```

Runtime invariants:

- `send()` returns `MessageRef`, NOT `ChannelSendResult`. The
  message-id round-trip is the point of the messaging surface;
  callers may pass `message_ref.id` to `update()` or `react()`.
  An audit record is produced as a side effect (logged by the
  runtime), not returned.
- `target` is the **physical** platform identifier (a Slack
  channel name, a Discord channel ID, etc.) — resolved by the
  runtime from `bindings.channels.<name>.config.target`. The
  source's logical channel name is never passed to the provider.
- `subscribe()` returns an object with a `cancel()` method.
  Calling `cancel()` MUST detach all handlers registered through
  that subscription; subsequent `inject_message()` (test-only
  helper) MUST NOT invoke them.
- A messaging provider that does not implement the full
  vocabulary (e.g., a Slack-without-threads product) declares the
  subset via `ProviderRecord.features`, and the runtime validates
  the IR's action vocabulary against that subset at startup. The
  reference messaging-stub declares the full set: `("send",
  "update", "react", "subscribe")`.

### 2.5 `EventStreamChannelProvider`

```python
@runtime_checkable
class EventStreamChannelProvider(Protocol):
    async def register_stream(
        self,
        name: str,
        content_types: Sequence[str],
        filter_predicate: Optional[Any] = None,
    ) -> str:
        ...

    async def publish(self, stream_endpoint: str, event: Any) -> None:
        ...
```

Defined in the contract module for completeness. **No stub
implementation is required in v0.9** — no fixture exercises this
contract, and a conforming runtime MAY register no product against
`(channels, "event-stream")`. A runtime that does register a
product MUST conform to the Protocol shape above; absence is the
conforming default.

### 2.6 Action vocabulary tables

The runtime exposes two tables every conforming runtime MUST publish:

```python
CHANNEL_CONTRACT_ACTION_VOCAB: dict[str, frozenset[str]] = {
    "webhook":      frozenset({"Post"}),
    "email":        frozenset({"Subject is", "Body is",
                               "HTML body is", "Attachments are",
                               "Recipients are"}),
    "messaging":    frozenset({"Send a message", "Reply in thread to",
                               "Update message", "React with",
                               "When a message is received",
                               "When a reaction is added",
                               "When a thread reply is received"}),
    "event-stream": frozenset({"register_stream", "publish"}),
}

CHANNEL_CONTRACT_FULL_FEATURES: dict[str, tuple[str, ...]] = {
    "webhook":      ("send",),
    "email":        ("send",),
    "messaging":    ("send", "update", "react", "subscribe"),
    "event-stream": ("register_stream", "publish"),
}
```

The vocab table is the compiler's authority for action-name
validation (display-string prefix match per design decision D),
but it MUST also be readable by the runtime — an alternate
runtime that wants to perform its own validation reads the same
table. The features table is what `ProviderRecord.features` slots
into when the product implements the full vocabulary.

---

## 3. Registry Surface and Binding Shape

### 3.1 The registry triple

Channel providers register against three keys:

```
(Category.CHANNELS, "<contract>", "<product>")
```

- `Category.CHANNELS` is a single enum value the conforming runtime
  exposes (alongside `Category.STORAGE`, `Category.PRESENTATION`,
  `Category.COMPUTE`, etc.).
- `<contract>` is one of `"webhook"`, `"email"`, `"messaging"`,
  `"event-stream"`.
- `<product>` is the registered name (e.g., `"stub"`, `"slack"`,
  `"ses"`, `"twilio"`).

A provider is registered by passing the triple plus a factory
callable to `ProviderRegistry.register(...)`. The factory receives
the binding's `config` sub-dict and returns a live provider
instance.

Every conforming runtime MUST register a `"stub"` product against
each of the three implementable contracts (`webhook`, `email`,
`messaging`). The fourth (`event-stream`) is optional in v0.9.

### 3.2 Contract registration

The contract registry exposes the full set of channel contracts
even when no product is bound. A conforming runtime MUST report:

```
contracts.has_contract(Category.CHANNELS, "webhook")     == True
contracts.has_contract(Category.CHANNELS, "email")       == True
contracts.has_contract(Category.CHANNELS, "messaging")   == True
contracts.has_contract(Category.CHANNELS, "event-stream") == True
```

These are present from `ContractRegistry.default()` — they do not
depend on any provider being registered.

### 3.3 The deploy-config envelope (v0.9 shape)

```json
{
  "version": "0.9.0",
  "bindings": {
    "channels": {
      "<logical-channel-display-name>": {
        "provider": "<product-name>",
        "config": {
          "target": "supplier-team-prod",
          "workspace_token_ref": "${SLACK_BOT_TOKEN}"
        }
      }
    }
  }
}
```

Invariants:

- The keys under `bindings.channels` MUST match the
  `channels[].name.display` field of the IR (the source's logical
  channel name as authored — `"team chat"`, not `"team_chat"`).
  Implementations MAY accept the snake-cased form as a fallback,
  but the display form is canonical.
- The `provider` field names a registered product; the runtime
  looks it up via `(Category.CHANNELS, contract, product)` where
  `contract` comes from the channel's IR `provider_contract` field.
- The `config` sub-dict is opaque to the runtime except for
  `${VAR}` environment-variable expansion. It is passed verbatim
  to the provider factory.

### 3.4 v0.8 fallback explicitly rejected

Pre-v0.9 deploy configs used a top-level `channels:` map keyed by
display name with `url`/`protocol` fields. **v0.9 conforming
runtimes MUST NOT honor this shape** for channels with a
`provider_contract`. The conformance suite asserts that an
outbound `provider_contract` channel whose only deploy entry is at
the top-level `channels:` key is treated as if it had no binding —
in strict mode, that raises; in non-strict mode, it log-and-drops.

The top-level `channels:` key remains tolerated only for legacy
URL/WebSocket channels (channels without a `provider_contract`),
which are out of scope for this spec. Provider-contract channels
flow exclusively through `bindings.channels`.

### 3.5 Provider isolation

For two channels declaring the same contract, the runtime MUST
construct **two distinct provider instances** — one per channel —
by calling the factory once per channel binding. State held in
provider instances does not bleed across channels. This is
testable: two webhook channels declaring the stub product produce
two `WebhookChannelStub` objects, and a `send()` on channel A does
not appear in channel B's `sent_calls`.

### 3.6 Stub-product fallback for unknown product names

When a deploy binding names a product the registry does not know,
the runtime MUST attempt a `(Category.CHANNELS, contract, "stub")`
lookup as a fallback. If the stub exists (which it does for every
implementable contract per §3.1), the channel is bound to the stub
and the deploy proceeds. The fallback is logged as a `warning`-level
event so operators see the substitution, but it does NOT raise.

This rule keeps deploys progressing in development environments
where a real product hasn't been packaged yet, while the strict
binding-presence check (§4) still catches the more common error
of forgetting the binding entirely.

---

## 4. Strict-Mode Binding Validation

### 4.1 The contract

A channel whose IR has a non-null `provider_contract` and whose
`direction` is `OUTBOUND` or `BIDIRECTIONAL` MUST have a
`bindings.channels.<display-name>` entry in the deploy config.

A conforming runtime exposes a `strict_channels` boolean (or
equivalent) that controls the response when the entry is missing:

- `strict_channels=True` (production default): the runtime MUST
  raise `ChannelConfigError` (or a runtime-specific exception
  named the same way) at app startup. The error message MUST name
  the channel and the contract.
- `strict_channels=False` (test/dev): the runtime MUST log the
  missing binding and continue. Subsequent `channel_send()` calls
  on that channel MUST log-and-drop without raising.

### 4.2 Why a flag, not auto-detection

`strict_channels` is the explicit opt-in / opt-out, not a
heuristic. A runtime MUST NOT infer strict-vs-non-strict from
the deploy file path, environment variables, or other signals —
those are unreliable and have caused production-vs-dev mode
mismatches in other systems. The default is conservative
(`strict=True`); operators set `strict=False` when they
deliberately want test/dev posture.

### 4.3 Inbound channels are exempt

`direction: inbound` channels do NOT require a deploy binding —
they have no outbound provider to wire up. Their conformance
surface is the auto-route (§6), not the dispatch path. A
strict-mode startup with an inbound-only channel and an empty
`bindings.channels` MUST succeed.

`direction: bidirectional` channels DO require a binding — they
have both an outbound dispatch (the binding's provider) and an
inbound auto-route (the webhook handler). Strict mode applies to
the outbound side.

### 4.4 Internal channels are exempt

A channel with `direction: internal` and no `provider_contract`
uses the runtime's distributed-runtime layer, not a provider.
Strict-mode binding validation does not apply; `bindings.channels`
need not contain an entry.

---

## 5. Failure-Mode Semantics

### 5.1 The three failure modes

Every channel's IR carries a `failure_mode` field, set from source
(`Failure mode is <mode>`) and defaulted to `"log-and-drop"` when
unspecified. The three values are:

- **`log-and-drop`** (default). Provider exceptions are caught by
  the dispatcher; the `channel_send()` call returns
  `{"ok": False, "outcome": "failed", "channel": <display>}`.
  No exception propagates. The error is logged at warning level.
- **`surface-as-error`**. Provider exceptions propagate to the
  caller of `channel_send()` as a `ChannelError`. The original
  exception is chained via `__cause__` so the audit trail
  preserves the upstream message. The runtime translates the
  raised `ChannelError` to an HTTP 5xx for HTTP-triggered sends,
  or routes it through TerminAtor for event-triggered sends.
- **`queue-and-retry`** (v0.10). The send is enqueued in a
  durable per-app `_termin_channel_queue` table; the synchronous
  `channel_send()` call returns
  `{"ok": False, "outcome": "queued", "channel": <display>,
  "queue_id": <id>}` immediately. An async retry worker drains
  the queue with exponential backoff. After a configurable
  `max_retry_hours` window (default reasonable, MUST NOT exceed
  24h) the payload moves to a `_termin_channel_dead_letter`
  table for operator inspection. v0.9.x reference runtime falls
  back to `log-and-drop` with a logged-warning posture
  distinguishing the placeholder from genuine default behavior;
  full implementation lands v0.10. A v0.9.x runtime that has
  not implemented this mode SHALL fall back to log-and-drop —
  this is the only conformant non-implementation posture.

### 5.2 Conformance of `log-and-drop`

The conformance pack tests `log-and-drop` end-to-end:

- A provider that raises an exception during `send()` MUST NOT
  cause `channel_send()` to raise.
- The return shape is a dict with `ok=False`, `outcome="failed"`,
  and the channel name.
- The runtime's per-channel error counter (if exposed via metrics)
  increments by one.

These tests run against the reference runtime today.

### 5.3 Conformance of `surface-as-error`

`surface-as-error` is a **deterministic** conformance test as of
v0.9.1: when a channel declares `failure_mode: "surface-as-error"`
and the provider's `send()` raises any exception, the dispatcher
MUST:

- Re-raise as `ChannelError(...)`. (Original exception preserved
  via `__cause__` chaining.)
- Increment the per-channel error counter (same bookkeeping as
  log-and-drop).
- Log the failure at warning level (same as log-and-drop).

The v0.9.1 reference runtime implements this; the conformance
test asserts the propagation shape directly without an
"either/or" fallback escape hatch. A runtime that catches and
swallows in surface-as-error mode is non-conforming.

### 5.4 Conformance of `queue-and-retry` — DEFERRED to v0.10

The grammar accepts `Failure mode is queue-and-retry`, the
analyzer validates the value, the IR records it. The v0.9.x
reference runtime falls back to log-and-drop with a logged
warning that distinguishes the placeholder mode from genuine
default behavior, so apps that declare it don't break — but
the queueing + retry + dead-letter semantics are NOT yet
required by the v0.9.1 conformance pack. The semantic test is
**SKIPPED** with a `pytest.mark.skip` marker pointing at this
section.

When the v0.10 implementation lands, this section will be
replaced with the deterministic conformance shape:

- `outcome="queued"` immediately on first failure
- `queue_id` opaque to the caller
- exponential backoff retry schedule (initial 30s, doubling, capped
  at 1h between attempts)
- payload migrated to `_termin_channel_dead_letter` after
  configurable `max_retry_hours` exhausted (operator-set, default
  reasonable, MUST NOT exceed 24h)
- dead-letter table observable via reflection / admin endpoint
  for operator drainage

Until v0.10, a conforming runtime MUST fall back to log-and-drop
when it sees `queue-and-retry` and has not implemented the worker.
Silent crashes or other behaviors are non-conforming.

### 5.5 Per-channel scope

`failure_mode` is per-channel. Two channels in the same app may
declare different failure modes. The runtime MUST honor each
channel's declared mode independently; there is no app-level
override.

---

## 6. Inbound Channel Auto-Routing

### 6.1 The contract

An IR channel with:

- `direction in ("INBOUND", "BIDIRECTIONAL")` AND
- non-empty `carries_content`

MUST cause the runtime to register a `POST` route at:

```
/webhooks/<channel.name.snake>
```

The path uses the channel's snake-case name. A channel called
`"echo-receiver"` (display) → `echo_receiver` (snake) registers at
`/webhooks/echo_receiver`.

### 6.2 Payload behavior

The auto-route handler MUST:

1. **Authorize.** Check the request principal's scopes against the
   channel's `requirements[direction == "send"]` clause. If the
   required scope is absent, return 403 (TerminAtor-routed).
2. **Parse JSON.** Reject non-JSON or non-object bodies as 400.
3. **Project to known columns.** Compute the set of column names
   from `carries_content`'s schema. Filter the body to that subset
   (extra fields silently dropped). If the projection is empty
   (no recognized fields), reject as 422.
4. **Persist.** Call `storage.create(carries_content, projected_data)`.
5. **Fire content events.** Run any `When <content>.created:`
   event handlers for the carried content type, in declaration
   order, before responding.
6. **Broadcast.** Publish a content event on the runtime's pub-sub
   surface so subscribers (`This table subscribes to <X> changes`)
   receive the new record live.
7. **Respond.** Return 200 with body
   `{"ok": True, "id": <record-id>, "channel": <display-name>}`.

### 6.3 Idempotency

The auto-route is NOT idempotent in v0.9. A POST with the same
body twice creates two records. Idempotency is a v0.10+ feature
candidate (the BRD mentions runtime-generated keys). The
conformance pack does not test idempotency for inbound — it
explicitly tests that two POSTs produce two records, locking in
the current (non-idempotent) contract until v0.10+ revisits.

### 6.4 Auth context for inbound

Inbound webhooks run under whatever principal the runtime's
identity provider resolves from the request — typically a default
"anonymous" or "system" role for unsigned webhooks, or a
provider-specific principal for signed ones. The conformance pack
verifies that the channel's `Requires "<scope>" to send`
declaration gates the auto-route exactly as it would gate an
outbound `channel_send()` for the same scope direction.

### 6.5 Channels carrying nothing

A channel with `direction: inbound` but empty `carries_content`
is a degenerate declaration. The runtime MUST NOT register an
auto-route for it. The compiler should reject the source at
compile time, but a runtime receiving such IR MUST NOT crash or
register a partial route; it MUST silently skip the registration.

---

## 7. The Dispatcher's Public Contract

For runtime authors. Provider authors and app authors can read
this as background.

### 7.1 Dispatcher construction

A conforming runtime exposes a `ChannelDispatcher` (or equivalent
named entity) constructed with:

- The IR (or at least its `channels[]` slice).
- The deploy config dict.
- The provider registry.

At construction time, the dispatcher MUST NOT call any provider
factory. Wiring happens at `startup()` to allow the dispatcher to
be reconstructed cheaply in tests.

### 7.2 `startup(strict)` semantics

Calling `startup(strict=True)` MUST:

1. For each channel in the IR with a non-null `provider_contract`:
   - Look up `bindings.channels.<display>` in the deploy config.
   - If absent and `direction in ("OUTBOUND", "BIDIRECTIONAL")`:
     raise `ChannelConfigError`.
   - If absent and `direction == "INBOUND"`: skip — inbound has no
     outbound dispatch to wire.
   - If present: look up
     `(Category.CHANNELS, provider_contract, binding.provider)`.
     On miss, fall back to
     `(Category.CHANNELS, provider_contract, "stub")`. On second
     miss, log a warning and skip (that channel will log-and-drop).
   - Construct one provider instance via the factory; store it
     keyed by the channel's display name.
2. Connect any non-provider WebSocket channels (out of scope of
   this spec; see `channel_ws.py`).

`startup(strict=False)` differs only in step 1's first sub-point:
the `ChannelConfigError` is replaced with a log line and the
channel skips into the log-and-drop posture.

### 7.3 `channel_send(name, data, user_scopes=...)` semantics

For a channel whose `provider_contract` is set:

1. Look up the channel by display or snake name. Unknown name →
   raise `ChannelError` (NOT log-and-drop; this is a programming
   error).
2. Check the user's scopes against the channel's `Requires
   "<scope>" to send` declaration. Insufficient scope → raise
   `ChannelScopeError`. Scope is checked BEFORE provider lookup.
3. Look up the bound provider. If absent (no binding, or fallback
   exhausted): return `{"ok": True, "status": "not_configured",
   "channel": <display>}`. **This MUST NOT raise.** Log-and-drop
   for "no provider" means the application keeps running.
4. Dispatch by contract:
   - `webhook`: `provider.send(body=data)`.
   - `email`: `provider.send(recipients=data["recipients"],
     subject=data["subject"], body=data["body"], ...)`.
   - `messaging`: `provider.send(target=<resolved>,
     message_text=data["text"])` where the target comes from the
     binding's `config.target`.
5. Map the result:
   - For webhook/email, return
     `{"ok": result.outcome == "delivered",
       "outcome": result.outcome,
       "channel": <display>}`.
   - For messaging, return
     `{"ok": True, "outcome": "delivered",
       "channel": <display>,
       "message_ref": message_ref.id}`.
6. On provider exception, apply the channel's `failure_mode`
   (§5).

### 7.4 Metrics surface

The dispatcher MAY expose a per-channel metrics dict:

```python
{
  "<display>": {
    "sent": int,        # successful outbound sends
    "received": int,    # inbound webhook hits
    "errors": int,      # failed sends (any failure mode)
    "last_active": str, # ISO8601 timestamp or None
    "state": str,       # "connected" | "disconnected" | "error"
  }
}
```

The metrics field is OPTIONAL in v0.9 — the conformance pack does
not assert its shape, only the side effects of the contracts it
gates (e.g., it does NOT assert `sent` equals 3 after three
sends). v0.10 may promote metrics to a contract surface.

---

## 8. Conformance Test Methodology

The conformance pack at `tests/test_v09_channel_*.py` tests a
(runtime, provider) pair against this spec. Five categories:

### 8.1 Contract conformance (`tests/test_v09_channel_contract.py`)

Tests the four `Protocol` shapes, the data classes, the action
vocabulary tables, and the contract registry. These are
unit-style tests against the contract module imports — no FastAPI
app, no compiled fixture.

### 8.2 Dispatch conformance (`tests/test_v09_channel_dispatch.py`)

Tests that `ChannelDispatcher.startup()` populates providers
correctly, that `channel_send()` routes through the right
provider method, that the message-ref surface works for messaging,
that provider isolation holds across two channels of the same
contract. Synthetic IR + synthetic deploy config; no compiled
fixture needed. Runs against the reference runtime today; will
run against any conforming runtime that exposes a
`ChannelDispatcher`-shaped surface (the adapter can wrap whatever
the runtime calls it).

### 8.3 Strict-mode conformance (`tests/test_v09_channel_strict_mode.py`)

Tests `strict_channels=True` raising on missing binding,
`strict_channels=False` log-and-dropping the same case, the
inbound exemption from strict mode, the bidirectional non-exemption,
the v0.8 fallback rejection, and the unknown-product-falls-back-to-stub
rule.

### 8.4 Inbound auto-route conformance (`tests/test_v09_channel_inbound.py`)

Tests the `/webhooks/<snake>` registration via deployed apps
(loads `channel_simple.termin.pkg` and `channel_demo.termin.pkg`
through the conformance adapter). Verifies record creation,
JSON projection, scope enforcement, the
non-idempotency contract, and the empty-content-skip rule.

### 8.5 Failure-mode conformance (`tests/test_v09_channel_failure_modes.py`)

Tests `log-and-drop` end-to-end (provider raises → channel_send
returns failure dict, no exception propagates). Tests
`surface-as-error` **deterministically** (provider raises →
ChannelError propagates; original exception chained via
`__cause__`; per-channel error metric increments) per §5.3. The
`queue-and-retry` test is **SKIPPED** with a `pytest.mark.skip`
marker pointing at §5.4 — the v0.10 deferral. v0.9.x runtimes
that fall back to log-and-drop are conformant; v0.10 will
replace the skip with a deterministic queue-shape assertion.

### 8.6 What "conforming" means

A (runtime, provider-stubs) pair is conforming for channels if:

- Every contract-conformance test passes (the four Protocols are
  satisfied; data classes validate inputs; action vocab tables
  are present and correct).
- Every dispatch-conformance test passes (startup wires
  providers; send routes correctly; provider isolation holds).
- Every strict-mode test passes (raise on missing, log-and-drop on
  non-strict, inbound exempt, etc.).
- Every inbound auto-route test passes (the route exists, payloads
  flow through to storage, scope gates, content events fire).
- Every failure-mode test passes (log-and-drop is enforced; the
  other two modes are either implemented or skipped via the
  documented fallback).

A pair that fails any test is non-conforming for channels in v0.9.

---

## 9. Out of Scope

The following are recognized as future work but not part of v0.9
channel conformance:

- **Real provider products.** The v0.9.x conformance pack tests
  against the reference stub products. Real providers (Slack, SES,
  Twilio, etc.) carry their own product-specific tests outside
  the conformance pack.
- **Per-channel idempotency keys for inbound webhooks.** v0.10
  candidate.
- **Webhook signature verification.** Per-product concern. The
  contract surface accommodates it (auth lives in `config`); the
  conformance pack does not exercise it.
- **Cross-channel ordering guarantees.** The runtime makes no
  ordering promise across channels. A v0.10 candidate.
- **The `event-stream` stub.** Defined in the Protocol module;
  no fixture exercises it. v0.10+ when an external-SSE consumer
  fixture exists.
- **Distributed-runtime channel-to-channel routing.** The internal
  `direction: internal` channel layer is the distributed runtime's
  concern, not this spec's.

---

*End of channel contract spec.*
