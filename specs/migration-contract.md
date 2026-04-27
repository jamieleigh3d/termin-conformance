# Termin Migration Contract — Conformance Specification

**Version:** 0.9.0-draft (synthesized 2026-04-26)
**Status:** Draft — companion to `termin-runtime-implementers-guide.md`. Specifies the migration semantics every conforming runtime + provider pair must satisfy. The conformance test pack at `tests/test_v09_migration.py` (forthcoming) is the executable form of this spec.
**Audience:** Three, in order of likelihood:
1. **Provider authors** writing storage providers (Postgres, DynamoDB, third-party) that plug into the reference runtime via the `StorageProvider` Protocol. Most consumers will reach this surface first — extending Termin through a provider, not by writing a new runtime.
2. **Alternative runtime authors** building a Termin runtime in a different language or on a different stack. The migration contract is the most data-sensitive boundary they must reproduce; the conformance pack validates their classifier against the language-level rules.
3. **App authors** whose IR evolves between deploys. Knowing which changes are safe vs. risky vs. blocked tells them what their PRs cost in operator review.

**Relationship to other specs:**
- `termin-ir-schema.json` defines the IR shape; the migration contract operates over differences between two IR versions.
- `termin-runtime-implementers-guide.md` covers the runtime's behavioral contract for a single IR; this spec covers the runtime's behavior when the IR changes.
- `termin-package-format.md` defines `.termin.pkg`; migration applies when a new package is deployed over an existing data store.
- `migration-classifier-design.md` (in the compiler repo) is the implementation-side design notes for the reference SQLite provider; this conformance spec captures the language-level invariants that design produces.

---

## 1. Scope and Audience Framing

### 1.1 What this spec covers

When a Termin application is redeployed with an evolved IR — new fields, removed fields, type changes, cascade-mode changes, new state machines, renames, etc. — the runtime must:

1. **Read** the current on-disk schema and **compute** a diff against the target (IR-declared) schema.
2. **Classify** every change as `safe`, `low`, `medium`, `high`, or `blocked`. Classification is a function of the change kind and content state; it is **the same on every conforming runtime**.
3. **Gate** with operator acknowledgment when classification requires it. Refuse the deploy if any change is `blocked` or any `low+` change is unack'd.
4. **Apply** the diff atomically through the bound storage provider.

This spec defines that contract. The classification rules in §5 are language-level invariants — every conforming runtime must produce the same `MigrationDiff` for the same `(current schema, target IR)` pair.

### 1.2 Why this spec exists

The conformance suite philosophy (per `CLAUDE.md` of this repo): *the conformance suite is the spec*. If a behavior isn't tested here, it isn't specified. Migration is the most data-sensitive operation in the language — silent classification disagreement between runtimes corrupts data. This spec closes the hole.

### 1.3 The provider-author audience

The v0.9 provider system makes the storage provider the natural extension surface. A consumer who wants Termin-on-Postgres or Termin-on-DynamoDB writes a provider, not a runtime. The reference runtime + their provider is the more common deployment shape than an alternative runtime entirely.

Two implications:

- **The provider's `migrate()` contract (§6) is the most-read section of this spec.** It is also the most enforced — every provider gets validated against it.
- **The classifier is the runtime's job, not the provider's.** Provider authors do not implement classification; they receive a fully-classified `MigrationDiff` from the runtime and apply it. A provider that re-classifies, ignores classification, or partially applies is non-conforming.

The runtime side of the contract (§7) matters too — but most provider authors only care about it as background context. They are not implementing it.

### 1.4 When migration is necessary

A migration is computed and applied whenever the deployed IR's content schemas differ from the on-disk schema. This happens in two distinct cases, with different frequency across the language's lifecycle:

**App-driven schema changes (always relevant).** The app author added a field, removed a field, changed a type, added a state machine, etc. The IR shape changed because the app changed. Every classification rule in §5 applies. App-driven changes are independent of the language version — they happen at v0.6, v0.9, v1.0, v2.5, all the same way.

**Language-driven IR changes (pre-v1.0 frequent; post-v1.0 cross-major only).** The Termin grammar evolved between deploys, producing a different IR shape from the same source. The v0.8 → v0.9 cascade migration is the canonical example: existing apps don't change their `.termin` source, but the same source compiles to a richer IR with explicit `cascade_mode` declarations.

Pre-v1.0, language-driven IR changes happen between every minor version. v0.5 → v0.6 added audit fields. v0.7 added trigger-where clauses. v0.8 → v0.9 added cascade grammar. Operators redeploying an app across minor versions encounter migrations even when the `.termin` source is unchanged.

Post-v1.0, the language commits to compatibility within a major version. v1.0 IR is forward and backward compatible with v1.5 IR — same IR shape, only optional additions, no removals. Operators redeploying across minor versions encounter no language-driven migrations. **Only app-driven schema changes produce migrations within a major version post-v1.0.**

Cross-major-version transitions (v1.x → v2.x) carry full migration semantics — new IR shapes, classified changes, operator ack. The cross-major case is rare and gets BRD-level specification each time.

This spec covers both cases uniformly. The classifier (§5) makes no distinction between "the app's schema changed" and "the language's IR shape changed" — both produce a `MigrationDiff` and the same per-change-kind classification rules apply. The skip-version rule (§8.4) reflects the lifecycle: pre-v1.0 forbids skipping minor versions; post-v1.0 forbids only skipping major versions.

### 1.5 What this spec does not cover

- Migration tooling (CLI flags for `termin migrate`, IDE assistance, etc.) — out of scope; the contract is what the runtime must do at deploy time, not how operators invoke it.
- Provider-internal implementation details (SQLite's table-rebuild dance, Postgres's `ALTER TABLE` capabilities) — these are documented per provider and may differ. Conformance is about observable behavior, not implementation strategy.
- Application-level data migration (changing the meaning of a field while keeping its type) — the runtime cannot detect or classify semantic-only changes. App authors handle these manually.
- Pre-v0.9 IR migration (v0.5 → v0.6 → v0.7 → v0.8). The v0.8 → v0.9 migration is the first formally-specified cross-version migration; older versions are out of scope and require manual operator action.

---

## 2. Layered Architecture

Migration is a layered concern. Three layers, with strict separation:

```
┌─────────────────────────────────────────────────────────────┐
│  IR LAYER (source of truth)                                  │
│  - Old IR (read from on-disk schema metadata or introspected)│
│  - New IR (the .termin.pkg being deployed)                   │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  RUNTIME LAYER (policy)                                      │
│  - Compute diff: (old IR, new IR) → MigrationDiff            │
│  - Classify each change: safe / low / medium / high / blocked│
│  - Check operator ack against deploy config                  │
│  - Construct backup when classification requires             │
│  - Drive the provider through the migration                  │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  PROVIDER LAYER (mechanism)                                  │
│  - Apply classified MigrationDiff atomically                 │
│  - Persist new schema metadata                               │
│  - Verify referential integrity post-apply                   │
│  - Surface errors to runtime for rollback decisions          │
└─────────────────────────────────────────────────────────────┘
```

### 2.1 Why this separation matters

**Classification is portability.** A change classified `medium` for SQLite must also be `medium` for Postgres. Otherwise an app that migrates cleanly on the reference runtime fails — or worse, silently corrupts data — on a different provider. Classification is a function of *what the change means in the language*, not *how a particular backend handles DDL*.

**Atomicity is mechanism.** SQLite uses transactional DDL with PRAGMA `defer_foreign_keys`. Postgres uses transactional DDL natively. DynamoDB doesn't have transactional DDL and must implement atomicity another way. The runtime doesn't care how the provider achieves atomicity; it only cares that the provider succeeds-completely-or-fails-completely.

**Provider boundary discipline (BRD §6.2).** The reference runtime's storage contract docstring states explicitly: "providers do not classify." A provider that classifies is non-conforming, even if its classification matches the runtime's. The classifier rules belong upstream of the provider boundary.

### 2.2 The provider-extension model

Most v0.9 consumers will reuse the reference runtime entirely and write a provider. In that case:

- The runtime layer is the reference Python implementation. The classifier, the operator-ack flow, the schema metadata table — all reused as-is.
- The provider layer is where extension lives. A Postgres provider implements `StorageProvider.migrate(diff)` against Postgres-native DDL; the runtime's classifier output becomes that provider's input.
- The conformance pack validates the provider against the contract. The runtime is implicitly conforming because it's the reference.

For alternative-runtime authors, both layers are theirs to implement. The conformance pack validates the whole pair.

---

## 3. The MigrationDiff Data Structure

The `MigrationDiff` is the runtime's output and the provider's input. It is also the wire shape the conformance pack tests against.

### 3.1 Top-level shape

```
MigrationDiff {
  changes: list of ContentChange,
  ir_version_before: text,           # "0.8.0", "0.9.0", etc.
  ir_version_after: text,
  fingerprint: text,                 # stable hash of the diff for ack/audit
}
```

A `MigrationDiff` is **the complete delta** between two IR versions. Empty `changes` means no migration is needed (the deploy is a no-op). Non-empty `changes` is processed atomically — the entire diff lands or none of it does.

### 3.2 ContentChange

Every entry in `changes` is a `ContentChange` with one of three kinds:

```
ContentChange {
  kind: "added" | "removed" | "modified",
  content_name: text,
  classification: "safe" | "low" | "medium" | "high" | "blocked",
  schema: ContentSchema (the target shape; null for "removed"),
  field_changes: list of FieldChange (empty for "added" and "removed"),
}
```

- **`added`** — new content type. Provider creates the table.
- **`removed`** — content type deleted from IR. Classification depends on whether the table is empty (§5).
- **`modified`** — content type exists in both versions; field-level changes captured in `field_changes`.

### 3.3 FieldChange

```
FieldChange {
  kind: "added" | "removed" | "type_changed" | "constraint_changed" | "renamed",
  field_name: text,
  detail: object (kind-specific),
}
```

- **`added`** — new field on existing content. `detail` carries the new field's spec.
- **`removed`** — field deleted from content. `detail` carries the old field's spec for rollback.
- **`type_changed`** — `business_type` or `column_type` changed. `detail.from` and `detail.to`.
- **`constraint_changed`** — `required`, `unique`, `min/max`, `cascade_mode`, `foreign_key`, etc. changed. `detail.constraint`, `detail.from`, `detail.to`.
- **`renamed`** — operator-declared rename mapping in deploy config matched. `detail.from` and `detail.to` field names. (Without an operator mapping, the runtime sees `removed` + `added`, not `renamed`.)

### 3.4 Classification aggregation

`MigrationDiff.classification` (computed) is the worst-case across all changes:

```
blocked > high > medium > low > safe
```

`ContentChange.classification` is the worst-case of (the content-kind classification, the field-change classifications).

The runtime exposes computed properties: `is_blocked`, `has_high_risk`, `has_medium_risk`, `has_low_risk`. Each is `true` if any change in the diff has that classification.

### 3.5 Cross-version round-trip

When the runtime reads an existing on-disk database that has no schema metadata table (because it predates v0.9), the runtime introspects the schema from native catalogs (e.g., `sqlite_master` + `PRAGMA table_info()` for SQLite) to construct an old IR. The diff is computed from that introspected old IR against the deployed new IR. After successful migration, the runtime writes the new IR to the metadata table; subsequent deploys read from there directly. See §9 for the v0.8 → v0.9 case in detail.

---

## 4. The Five-Tier Classification

The 5-tier model replaces the earlier single-tier "risky." Each tier carries different operator expectations and different runtime behavior.

### 4.1 `safe`

**Semantics:** No data is touched. No semantics change. The migration applies at startup with no operator interaction.

**Examples:** Adding an optional field with no default. Creating a new content type. Removing an empty content type.

**Deploy config:** No acknowledgment required.

**Runtime behavior:** Apply at startup, log the migration, continue.

**Provider behavior:** Apply atomically. No backup needed.

### 4.2 `low`

**Semantics:** Schema changes in-place via an ALTER. No data rewritten. Easily reversible. Audit trail desirable but no operational risk.

**Examples:** Field rename with operator mapping (same type). Content rename with operator mapping. Adding a column the backend supports as in-place ADD COLUMN with default.

**Deploy config:** Operator includes the change's fingerprint in `migrations.accepted_changes` (per-change ack), OR — only when `migrations.dev_mode: true` — sets `migrations.accept_any_low: true` for blanket acceptance of low-tier changes. **The blanket form is dev-only and refused in production deploys** regardless of value (see §7.2). Per-change ack is always honored in any environment. Audit trail; no extended validation.

**Runtime behavior:** Refuse deploy if unacked. Apply on ack. Log.

**Provider behavior:** Apply atomically (in-place if backend supports). No backup needed; transaction rollback is sufficient if the apply fails.

### 4.3 `medium`

**Semantics:** Backend rebuild required (ALTER doesn't support the change), OR data values may need transformation/validation. Data preserved; rollback via transaction if apply fails.

**Examples:** Type widening (whole_number → number, number → text). Removing NOT NULL. Adding UNIQUE (data is checked but expected to satisfy). Adding/removing CHECK constraints. Loosening min/max bounds.

**Deploy config:** Operator must include the change's fingerprint in `migrations.accepted_changes`. **No blanket form exists for medium-tier changes** — every medium-tier change requires explicit fingerprint review in any environment. Validation step gates commit.

**Runtime behavior:** Refuse deploy if unacked. Apply on ack. Run validation step (e.g., row counts before/after match; new constraints satisfied). Log.

**Provider behavior:** Apply atomically via rebuild if needed. No backup required (transaction is sufficient). Surface validation errors to runtime for rollback.

### 4.4 `high`

**Semantics:** Backend rebuild required AND either data semantics change for existing records OR referential integrity is briefly broken during apply. Rollback to a transaction snapshot is insufficient — a backup is required for operator confidence.

**Examples:** Adding NOT NULL to a nullable field. Adding UNIQUE where backfill is needed. Changing cascade_mode (including v0.8 implicit-null → v0.9 explicit cascade/restrict). Tightening min/max bounds. Removing an enum value (operator must remap data first). Adding a state machine to existing content (existing rows need an initial state).

**Deploy config:** Operator must include the change's fingerprint in `migrations.accepted_changes`. **No blanket form exists for high-tier changes** — every high-tier change requires explicit fingerprint review in any environment. **Pre-migration backup is REQUIRED.** Validation step gates commit.

**Runtime behavior:** Refuse deploy if unacked. Construct backup before calling provider. Apply on ack. Run validation step. Keep backup until deploy is verified.

**Provider behavior:** Implement `create_backup()` (returns a backup handle the runtime can reference). Apply atomically. Surface validation errors. Provide a rollback path to the backup if validation fails.

### 4.5 `blocked`

**Semantics:** Data loss, impossible operation, or invariant the runtime cannot reconstruct. The deploy is refused unconditionally; the operator must reshape the IR or the data manually.

**Examples:** Removing a non-empty content type. Removing a non-empty field. Adding a foreign-key field where existing rows can't be NULL. Changing FK target where old values may not exist in new target. Lossy type changes (text → whole_number where some text values aren't integers). Changing `is owned by` to a field with non-unique values.

**Deploy config:** No acknowledgment will unblock. No blanket flag, no per-change fingerprint, no dev-mode override bypasses `blocked`. The deploy is refused; the operator must reshape the IR or remediate the data.

**Runtime behavior:** Refuse deploy. Emit a clear error pointing at the blocked change(s) and the available remediations.

**Provider behavior:** Should never receive a `blocked` diff. If one arrives (defense-in-depth), refuse with a clear error.

### 4.6 Aggregation

A single diff that contains both `safe` and `high` changes is overall `high`. The deploy is gated as a unit — partial application is not permitted. Operators ack each change individually (per-change fingerprints), but the apply happens atomically. If any change fails, all changes roll back.

---

## 5. Per-Change-Kind Classification Rules

This is the language-level invariant. Every conforming runtime must classify every change kind exactly as below. The reference runtime's tests (compiler-side) enforce this; the conformance pack tests it cross-runtime.

### 5.1 Content-level changes

| Change | Classification | Reasoning |
|---|---|---|
| Add content (new table) | `safe` | Creates new table; affects no existing data. |
| Remove content, table non-empty | `blocked` | Data loss. |
| Remove content, table empty | `low` (downgraded from blocked per §5.3) | DROP TABLE on empty table loses no data, but the operator should know a content type disappeared — audit trail via per-change ack is the floor. |
| Rename content (operator-declared mapping) | `low` | In-place ALTER TABLE RENAME TO; FK references update automatically (in backends that support it). |
| Add state machine to existing content | `high` | New NOT NULL state column; existing rows need a backfilled initial state; rebuild required. |
| Remove state machine | `medium` | Column may stay (orphaned) or be dropped via rebuild; transition gating disappears. |
| Change initial state of state machine | `safe` | Affects new records only; existing records are untouched. |

### 5.2 Field-level changes

| Change | Classification | Reasoning |
|---|---|---|
| Add field, optional, no default | `safe` | ADD COLUMN; existing rows get NULL. |
| Add field, optional, with default | `safe` | ADD COLUMN; new rows use default; existing rows get NULL. |
| Add field, required, with default | `safe` | ADD COLUMN with default; existing rows backfill implicitly. |
| Add field, required, no default | `medium` | Existing rows would need a value the IR doesn't provide; operator must accept that the column is non-null only for new rows OR provide a default in a follow-up. Treated as a values question. |
| Add field, with `foreign_key` | `blocked` | Existing rows would have NULL refs; violates the cascade-or-restrict invariant from grammar. |
| Add field, with `unique` | `medium` | Backfill with NULL works (NULLs don't violate UNIQUE in most backends); existing data validation needed if a non-null default is provided. |
| Remove field, table non-empty | `blocked` | Data loss. |
| Remove field, table empty | `low` (downgraded from blocked per §5.3) | No data to lose, but the operator should still see the change in the audit trail. |
| Rename field, operator-declared mapping, same type | `low` | RENAME COLUMN in-place. |
| Rename field, operator-declared mapping, different type | `medium` | Rebuild required for the type change; data preserved if cast is lossless. |
| Change `business_type`, lossless widening (whole_number → number, number → text) | `medium` | Rebuild required; data preserved by cast. |
| Change `business_type`, lossy (text → whole_number) | `blocked` | Values may not parse; data loss. |
| Add NOT NULL to nullable field | `high` | Rebuild + existing NULLs would violate; backfill required. |
| Remove NOT NULL | `medium` | Rebuild required (most backends); data preserved. |
| Add UNIQUE to existing field | `high` | Rebuild + existing duplicates would fail; data validation needed. |
| Remove UNIQUE | `medium` | Rebuild required; data preserved. |
| Add CHECK (min/max) | `high` | Rebuild + existing rows may violate. |
| Remove CHECK | `medium` | Rebuild required; data preserved. |
| Tighten min/max bounds | `high` | Rebuild + existing values may violate. |
| Loosen min/max bounds | `medium` | Rebuild required; loosening can't violate. |
| Add enum value | `medium` | Rebuild required (CHECK changes); existing data preserved. |
| Remove enum value | `high` | Rebuild + existing rows with that value violate; values need to be remapped (operator's job before redeploy). |
| Add `foreign_key` to existing field | `blocked` | Existing values may not exist in target. |
| Remove `foreign_key` | `medium` | Rebuild required; loosening. |
| Change `foreign_key` target | `blocked` | Old values may not exist in new target. |
| Change `cascade_mode` (any direction, including v0.8 implicit-null → v0.9 cascade/restrict) | `high` | Rebuild required to update ON DELETE clause; future delete behavior changes for existing records. |

### 5.3 Empty-table downgrade

A `medium`, `high`, or `blocked` change that would otherwise be classified at that tier may be downgraded to `low` if the affected content type's table is empty at migration time.

**Rules:**
- Downgrade applies only at the change-kind level, not aggregated. If a content type has multiple changes and any change still requires the higher tier, no downgrade.
- The runtime queries row count from the provider before classification; this is the only mid-classification provider call.
- The downgrade is recorded in the audit log so operators see "would-have-been `high`, downgraded to `low` because table was empty."
- The downgrade target is `low`, NOT `safe`. Even on an empty table, the operator should see the change pass through the per-change ack flow — the audit trail of "we removed this field" is valuable independent of whether data was lost. `safe` would skip operator awareness entirely; `low` records the change without operational friction.
- `blocked` for "remove non-empty content" downgrades to `low` for "remove empty content."

**Why `low` not `safe`:** First-deploy and migrate-of-staging-environments commonly have empty tables. The downgrade prevents friction-without-value (a migration refusing to start because of a removal that has nothing to remove). But the operator should still see and ack the change — pre-empty tables in production may have been recently emptied by an unrelated process, and the audit trail catches that. `safe` is reserved for changes where no audit trail is needed at all (additive, no semantics change).

### 5.4 Rationale for the "operator-declared rename" requirement

Without an operator mapping, the runtime sees a removed field and an added field — two changes, one classified `blocked` (remove non-empty) and one classified per the new field's shape. With an operator mapping, the runtime resolves them to a single `renamed` change, classified as `low` or `medium` per type compatibility.

The operator mapping lives in deploy config:

```yaml
migrations:
  renames:
    "tickets.priority": "tickets.severity"      # field rename
    "tickets": "incidents"                       # content rename
```

The runtime applies renames before computing the rest of the diff, so subsequent classification operates against the renamed names.

---

## 6. The Provider's `migrate()` Contract

This section is the most-read for provider authors. It is the contract the provider's implementation must satisfy.

### 6.1 Signature

```python
async def migrate(self, diff: MigrationDiff) -> None:
    """Apply the migration diff atomically.

    Receives a fully-classified diff from the runtime. Does not classify.
    Does not gate. Applies the changes or raises.

    Atomicity: the entire diff lands or none of it does. Partial migrations
    are a contract violation — the caller will see the database as if
    migrate() had never been called.
    """
```

### 6.2 Required behavior

A conforming provider's `migrate(diff)`:

1. **Does not re-classify.** The diff arrives classified. The provider trusts the classification and applies the changes. Even if the provider believes a change should be a different tier, it applies as-classified — re-classification is a contract violation.

2. **Applies atomically.** All changes in the diff land together, or none do. If applying change *N* fails, changes 1..N-1 must be rolled back. The on-disk state after a failed `migrate()` must be observably identical to the on-disk state before it was called.

3. **Is idempotent under retry.** A provider that has successfully applied a diff and is called with the same diff again must detect no-op and return without re-applying. Implementations typically use the schema metadata table (§7.3) to detect this; a diff whose `ir_version_after` matches the metadata table's current version is a no-op.

4. **Persists schema metadata on success.** After applying, the provider writes the new IR to its schema metadata storage (§7.3). On subsequent boot, the runtime reads this metadata to identify the "current" IR. Failing to persist metadata means the next deploy will see the migration as un-applied, even though the data was changed.

5. **Verifies referential integrity post-apply.** After applying all changes, the provider must verify that every foreign-key reference in the new schema resolves. Backends that support transactional FK deferral (SQLite ≥ 3.26, Postgres) verify at commit time; backends that don't must verify explicitly after apply. Failure here is a rollback.

6. **Implements `create_backup()` for `high`-classified diffs.** The runtime calls `create_backup()` before `migrate()` when any change is `high`. The provider returns a backup handle (an opaque token; the format is provider-internal). The runtime references this handle if rollback-to-backup becomes necessary. After successful deploy verification, the runtime calls `release_backup(handle)`.

7. **Surfaces structured errors.** Failures in `migrate()` raise typed errors the runtime can route through TerminAtor:
   - `MigrationApplyError` — apply failed mid-way; provider has rolled back.
   - `MigrationValidationError` — apply succeeded but post-apply verification (FK integrity, validation step) failed; provider has rolled back.
   - `MigrationFingerprintMismatch` — provider detected a fingerprint mismatch (very rare; defense-in-depth).
   - `MigrationProviderError` — backend infrastructure error (connection lost, disk full, etc.); rollback may or may not have completed; runtime treats as worst-case.

### 6.3 Forbidden behavior

- **Classifying.** The provider does not decide which tier a change belongs to.
- **Gating.** The provider does not check operator ack. The runtime did that before calling `migrate()`.
- **Partial apply.** No "apply what you can; leave the rest." Atomicity is non-negotiable.
- **Silent metadata drift.** The provider must persist the new IR after every successful migration, even if the diff was empty (no-op deploys still update the deployed_at timestamp).
- **Long-lived locks.** The migration must complete in bounded time. Backends that lock the entire database for migration are conforming but not recommended for production-scale; document the lock semantics in the provider's metadata.

### 6.4 What "atomic" means per backend

Atomicity is observable behavior. Implementations differ:

- **SQLite (reference):** transactional DDL with `PRAGMA defer_foreign_keys = ON` inside a single transaction. The 12-step table-rebuild dance for unsupported ALTERs.
- **Postgres:** transactional DDL natively. `BEGIN; ... ; COMMIT;` is sufficient for almost everything.
- **DynamoDB or other non-relational:** no native DDL transactions. Implementations construct a "shadow table" pattern — apply changes to a copy, swap atomically, retain the original as the backup. The conformance test does not care how atomicity is achieved; it tests that a failed apply leaves the database observably unchanged.

The conformance pack includes a "fault injection" category where the provider's apply path is forcibly interrupted (e.g., raise an exception mid-apply). The post-fault state must be observably identical to the pre-call state. Providers that fail this are non-conforming.

---

## 7. The Runtime's Migration-Drive Contract

This section matters for alternative-runtime authors. Provider authors can read it as background.

### 7.1 The migration drive sequence

On every deploy (first-deploy and evolve-deploy alike), the runtime executes:

```
1. Determine the current schema:
   a. Try: read the schema metadata table from the provider.
   b. On miss (table doesn't exist): introspect via backend-native catalogs.
   c. On miss (no data at all): empty schema (initial deploy).

2. Compute the diff:
   diff = MigrationDiff(current_schema, target_ir)

3. Classify the diff (§5).

4. Check operator ack against deploy config:
   - blocked → refuse deploy with specific error
   - high/medium/low changes → must each have a fingerprint in
     migrations.accepted_changes, OR migrations.accept_any_risky must be true
   - safe changes → no ack needed

5. If the diff has any `high` change: ask the provider for a backup handle.
   The runtime stores the handle for the duration of the deploy.

6. Call provider.migrate(diff). Block until complete.

7. Run the validation step (when classification requires it):
   - row counts before/after match (the provider exposed pre-apply counts)
   - new constraints are satisfied (smoke read with constraint-tightening)
   - foreign keys resolve

8. On validation success: the deploy is complete.
   - Release the backup handle (if any).
   - Continue to runtime startup.

9. On validation failure: rollback to backup if available; otherwise the
   provider's rollback applies.
   - Refuse the deploy with a specific error pointing at what failed.
```

### 7.2 Operator acknowledgment surface

Deploy config carries the ack. The default posture is **production-strict** — every non-safe change requires explicit per-change fingerprint review. Operators opt into developer conveniences by setting `dev_mode: true`.

```yaml
migrations:
  # Dev-mode opt-in. Default is false (production-strict).
  # When false: only per-change fingerprint ack is honored. This is the
  #   posture for any production or shared-staging environment.
  # When true: the accept_any_low blanket flag is ALSO honored, in
  #   addition to per-change ack. Convenient for local dev where the
  #   operator doesn't want to fingerprint every rename.
  dev_mode: false

  # Blanket ack for low-tier changes only. Honored only when
  # dev_mode: true. Has no effect in production-strict mode regardless
  # of value. Does NOT cover medium, high, or blocked changes — those
  # always require per-change ack regardless of dev_mode.
  accept_any_low: false

  # Per-change ack — operator lists the fingerprints they have reviewed.
  # Always honored in any environment, for low/medium/high tiers.
  # Each fingerprint is computed by the runtime from
  #   (kind, content_name, field_name, before_detail, after_detail)
  # If the IR drifts after the fingerprint is recorded, the fingerprint
  # changes and the deploy refuses again.
  accepted_changes:
    - "tickets.priority:add_required_field:b3f2a"
    - "comments.ticket:cascade_mode_change:cascade:7d8e1"

  # Operator-declared rename mappings — the runtime resolves these
  # before classifying, so a removed-and-added pair becomes a single
  # rename change.
  renames:
    "tickets.priority": "tickets.severity"
    "tickets": "incidents"
```

**Environment gating.** `dev_mode` is the explicit opt-in. The runtime does not infer dev vs prod from boundary path naming, environment variables, or other heuristics — those are unreliable signals. The default is conservative: `dev_mode: false` means "treat this deploy as production." Operators who want dev conveniences set the flag explicitly in the deploy config they're using locally.

**Conformance posture.** A conforming runtime refuses any low-tier change without per-change ack when `dev_mode: false`. A conforming runtime refuses any medium-or-high-tier change without per-change ack regardless of `dev_mode`. The conformance pack tests these gates explicitly.

**Fingerprint determinism.** The fingerprint is a stable hash. The conformance pack includes fingerprint-determinism tests: the same change in the same context produces the same fingerprint across runtimes. Fingerprint drift between runtimes makes operator ack non-portable, which violates the language-level promise of §2.

### 7.3 Schema metadata table

Every conforming provider exposes a schema metadata mechanism:

```
read_schema_metadata() -> { ir_version: text, schema_json: text, deployed_at: timestamp } | None
write_schema_metadata(ir_version: text, schema_json: text) -> None
```

The runtime calls these during the migration drive. The provider's underlying storage (a `_termin_schema` SQLite table; a `termin.schema` Postgres table; a metadata document in DynamoDB) is provider-internal — the runtime only knows the contract.

On first-ever deploy, `read_schema_metadata()` returns None, the runtime falls back to introspection (§9), and after a successful migration writes the new metadata.

### 7.4 Audit logging

Every migration produces an audit-log record:

```
{
  ir_version_before: text,
  ir_version_after: text,
  classification: "safe" | "low" | "medium" | "high",
  changes: list of { content, field, kind, classification, fingerprint },
  ack_source: "deploy_config" | "blanket" | "downgrade_empty_table",
  applied_at: timestamp,
  applied_by_principal: Principal,
  apply_duration_ms: number,
  validation_duration_ms: number,
}
```

The runtime persists this record. Audit-log conformance is a separate spec; this section captures only the migration-specific fields.

---

## 8. Cross-Version Migration

The v0.8 → v0.9 cross-version migration is the first formally-specified case. The general rules below apply to every IR version transition.

### 8.1 v0.8 → v0.9 specifically

Pre-v0.9 databases have no schema metadata table. The runtime:

1. Calls `provider.read_schema_metadata()` → returns None.
2. Falls back to introspection: `provider.introspect_schema()` returns a `ContentSchema` set reconstructed from backend catalogs. This is the v0.8-shape "current" schema.
3. Computes the diff against the deployed v0.9 IR. The most common changes:
   - **Cascade mode, implicit-null → explicit cascade or restrict**: classified `high` per §5.2. Requires backup, requires per-change ack. The fingerprint is stable across deploys.
   - **State machine constraint additions** (v0.8 didn't enforce some scope gates that v0.9 does at the storage layer): classified per §5.2.
   - **Field renames** (rare; most apps didn't rename): require operator-declared mapping per §5.4.
4. Operator ack flow runs as normal.
5. On success, writes v0.9 IR to schema metadata. Subsequent deploys read from there.

### 8.2 The introspection fallback

For v0.9-conforming providers, `introspect_schema()` returns a `ContentSchema` reconstructed from backend catalogs:

- **SQLite:** queries `sqlite_master` for table definitions, `PRAGMA table_info(<table>)` for columns and constraints, `PRAGMA foreign_key_list(<table>)` for FK declarations. CHECK constraints are parsed from the `sqlite_master.sql` text.
- **Postgres:** queries `information_schema.tables`, `information_schema.columns`, `information_schema.table_constraints`. CHECK constraints come from `pg_constraint`.
- **DynamoDB or other non-SQL:** introspection is provider-defined; the conformance pack accepts any reconstruction that produces a valid `ContentSchema`.

The introspection produces a *best-effort* old IR. Some constraints that the IR would have specified (e.g., `business_type: "currency"` vs `business_type: "number"`) cannot be recovered from a SQL backend that only stored REAL — these collapse to a generic type. The conformance pack treats this as expected; the diff against the deployed IR will show the constraint refinement as a change, and the operator acks it.

### 8.3 Future cross-version migrations

For v0.9 → v0.10 and beyond, both old and new IR will be readable from the schema metadata table — no introspection fallback needed except for the original v0.8 → v0.9 jump. Migration semantics are otherwise identical.

### 8.4 Skipping versions

The skip-version rule reflects the language lifecycle (§1.4):

**Pre-v1.0 (today).** A v0.X database deployed against a v0.Z IR where Z > X+1 is **not supported**. The classifier rules for v0.Z may not cover v0.X-shaped diffs; intermediate versions added IR fields the v0.Z classifier assumes are present. Operators must migrate v0.X → v0.X+1 → ... → v0.Z, one minor version per deploy.

**Post-v1.0 (future).** Within a major version, skipping is permitted. v1.0 → v1.5 directly is supported because v1.x's compatibility guarantees mean v1.5's classifier handles v1.0-shape IRs natively. Cross-major (v1.x → v2.x) is the analog of pre-v1.0's minor-version skip rule: no skipping. v1.x → v3.x must go through v2.x.

The runtime detects skip-version cases by comparing `ir_version_after` (from deploy config or the deployed IR's manifest) to `ir_version_before` (from the metadata table or the introspection-implied version):

- If the gap violates the rule for the current era → deploy refused with a specific error pointing at the required intermediate version.
- If the gap is permitted → migration proceeds normally.

**Convenience for chained migrations.** Operators chaining several migrations (e.g., a v0.6 production database upgrading to v0.9) deploy each intermediate version in sequence. The recommended workflow:

1. Stop the v0.6 service.
2. Deploy v0.7 IR over the v0.6 database. Review classification, ack changes, verify post-deploy.
3. Deploy v0.8 IR over the v0.7 database. Review, ack, verify.
4. Deploy v0.9 IR over the v0.8 database. Review, ack, verify.
5. Resume service.

The runtime contract is **one IR transition per deploy**. Chained migrations are operator workflow, not a runtime feature — the runtime stays simple, and each step is independently auditable. A `termin migrate --chain` CLI utility that automates the sequence (including pulling the right intermediate package versions and presenting the cumulative ack list once) is in the compiler repo's tooling backlog. It will be a thin orchestration layer over the same per-deploy contract this spec defines; nothing about it changes the runtime's per-IR-transition semantics.

---

## 9. Conformance Test Methodology

The conformance pack at `tests/test_v09_migration.py` (forthcoming) tests a (runtime, provider) pair against this spec. Three categories:

### 9.1 Classifier conformance (runtime-layer)

For a given (current schema, target IR) pair, the runtime under test must produce the expected `MigrationDiff`. Every `ContentChange` and `FieldChange` must match — same kind, same classification, same details.

Test fixtures live in `fixtures/migrations/classifier/`:

```
fixtures/migrations/classifier/
  add-optional-field/
    current_schema.json    # v0.8.x shape, hand-authored
    target_ir.json         # v0.9.x shape, hand-authored
    expected_diff.json     # the exact MigrationDiff the runtime must produce
  cascade-mode-change/
    current_schema.json
    target_ir.json
    expected_diff.json
  ... (one per change kind)
```

The test loads the pair, runs the runtime's classifier, and asserts deep equality with `expected_diff.json` (modulo timestamps and runtime-specific fields).

**~30 test cases**, one per change kind from §5.1 and §5.2 plus aggregation cases (mixed-tier diffs).

### 9.2 Provider migrate() conformance (provider-layer)

For a given (classified diff, on-disk DB) pair, the provider's `migrate()` must produce the expected post-apply DB state.

Test fixtures live in `fixtures/migrations/apply/`:

```
fixtures/migrations/apply/
  add-required-field-with-default/
    pre_db.sql             # SQL/dump representing the pre-state
    diff.json              # the classified MigrationDiff
    post_db.sql            # the expected SQL/dump after migrate()
  cascade-mode-change-with-data/
    ...
```

The test:
1. Loads `pre_db.sql` into a fresh database via the provider.
2. Calls `provider.migrate(diff)`.
3. Dumps the resulting database.
4. Asserts equality with `post_db.sql` (modulo whitespace and ordering).

**~15-20 test cases**, focused on the destructive/transformational categories (`medium` and `high`).

### 9.3 End-to-end migration (full-stack)

For a given (pre-IR, post-IR, pre-DB, deploy-config) tuple, the full deploy flow must produce the expected post-DB state OR refuse with the expected error.

Test fixtures live in `fixtures/migrations/end-to-end/`:

```
fixtures/migrations/end-to-end/
  v0.8-to-v0.9-cascade-migration/
    pre_ir.json            # v0.8 IR
    pre_db.sql             # v0.8-shape on-disk
    post_ir.json           # v0.9 IR
    deploy_config.yaml     # operator ack included
    expected_outcome.json  # success + post-state, OR refusal + error
  blocked-non-empty-removal/
    pre_ir.json
    pre_db.sql
    post_ir.json
    deploy_config.yaml     # no ack — should refuse
    expected_outcome.json  # refuse with specific error
  ...
```

The test runs the runtime's full deploy flow and asserts the outcome.

**~10-15 test cases**, including the v0.8 → v0.9 round-trip explicitly.

### 9.4 Fault injection

A subset of the apply-conformance tests injects faults — raises an exception at a configurable point during `migrate()`. The post-fault DB state must be observably identical to the pre-call state. Atomicity violations are non-conforming.

**~5 test cases**, covering apply-failure, validation-failure, and metadata-write-failure.

### 9.5 Fixture generation

Hand-authoring `pre_db.sql` for every test would be expensive and error-prone. The conformance pack ships a fixture generator at `fixtures/migrations/_gen.py`:

```bash
python fixtures/migrations/_gen.py --ir current_schema.json --seed sample_seed.json --output pre_db.sql
```

The generator:
1. Loads an IR.
2. Compiles it through the reference Python compiler to produce a runnable runtime.
3. Boots the runtime with the bound provider.
4. Inserts seed data.
5. Dumps the resulting database.

Fixtures are regenerated whenever the IR shape or provider serialization changes. The generator is part of the conformance repo so test authors can add new fixtures without depending on the compiler repo's internals.

### 9.6 What "conforming" means

A (runtime, provider) pair is conforming for migration if:

- Every classifier-conformance test produces the expected diff.
- Every apply-conformance test produces the expected post-DB.
- Every end-to-end test produces the expected outcome (success-with-state OR refuse-with-error).
- Every fault-injection test produces the pre-call state.

A pair that fails any test is non-conforming for migration. The conformance summary records which tier of the spec each failure violates, so operators can decide whether to deploy a partially-conforming runtime in their environment.

---

## 10. Out of Scope

The following are recognized as future work but not part of v0.9 migration:

**Migration tooling:**
- A `termin migrate` CLI for previewing diffs against a target deploy.
- IDE integration for fingerprint generation in deploy config.
- Automated rename detection (without operator mapping).

**Advanced classification:**
- Per-row data validation for type changes (the `medium` tier today is "rebuild and trust the cast"; deeper validation is a v0.10 candidate).
- Cost-aware classification (the deploy is `safe` but takes 2 hours on a 50TB table — runtime emits a warning but doesn't gate; a future tier could).

**Multi-version skipping:**
- v0.8 → v0.10 directly. Currently refused (§8.4); future versions may add a chained-migration path.

**Cross-provider migration:**
- Migrating data from one provider to another (e.g., SQLite to Postgres) at deploy time. v0.9 supports same-provider migration only. Cross-provider migration is a separate operator concern with its own tooling.

**Application-level data transformations:**
- Renaming an enum value's *meaning* without renaming the value (e.g., "active" used to mean "in-use"; now means "subscribed"). The runtime cannot detect this; app authors handle it manually.

**Multi-region / replicated migrations:**
- Coordinating migration across replicas. v0.9 assumes single-leader storage; replicated and distributed scenarios are a future BRD topic.

---

*End of migration contract spec.*
