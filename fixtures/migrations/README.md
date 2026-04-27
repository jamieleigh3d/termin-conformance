# Migration Conformance Fixtures

Fixtures that exercise the migration contract per
[`specs/migration-contract.md`](../../specs/migration-contract.md).

The migration test pack tests a (runtime, provider) pair against four
categories of conformance:

| Subdir | Spec § | What it tests |
|---|---|---|
| `classifier/` | §9.1 | Classifier produces the expected `MigrationDiff` for a given (current schema, target IR) pair |
| `ack_gating/` | §9.1 | Operator-ack gates accept/reject correctly in dev_mode and production-strict modes |
| `apply/` | §9.2 | Provider's `migrate()` produces the expected post-apply state (compared via runtime read) |
| `fault_injection/` | §9.4 | Faults injected at any stage during `migrate()` leave the database observably identical to its pre-call state |
| `e2e/` | §9.3 | Full deploy flow (compute diff → classify → check ack → apply → validate) produces the expected outcome |
| `v08_round_trip/` | §9.3 | Specific cross-version case: a v0.8-shape on-disk database upgrades to v0.9 IR cleanly |

## Fixture format per category

### `classifier/<case-name>/`

Each case is a directory containing three files:

- `current_schema.json` — the previously-deployed IR's `content` list (or null for first-deploy)
- `target_ir.json` — the deployed IR (a `.termin.pkg`'s ir.json or a hand-authored excerpt)
- `expected_diff.json` — the exact `MigrationDiff` shape the classifier must produce
- `migrations_config.json` *(optional)* — operator config (renames, etc.) that the classifier consumes before producing the diff

Test loads the pair, runs the runtime's classifier, and asserts deep
equality with `expected_diff.json` (modulo timestamps and
runtime-specific fields).

### `ack_gating/<case-name>/`

Each case is a directory containing:

- `diff.json` — a pre-classified `MigrationDiff`
- `migrations_config.json` — the deploy config's `migrations` block
- `expected.json` — `{ "covered": bool, "missing": [<fingerprint>...] }`

Test runs `ack_covers(diff, migrations_config)` and `missing_acks(...)`,
asserts they match expected. The fixture set covers:

- Production-strict (default): per-change fingerprints work; blanket flag inert
- Dev-mode + accept_any_low: blanket-low covers low-tier changes
- Dev-mode + accept_any_low: blanket-low does NOT cover medium/high
- Half-the-world: some fingerprints present, others missing → reports missing
- Empty diff: trivially covered
- Blocked diff: never covered (separately rejected, but ack_covers still returns true since blocked changes don't need ack)

### `apply/<case-name>/`

Each case is a directory containing:

- `pre_ir.json` — the IR the pre-state was created from
- `pre_seed.json` — the seed records inserted before migration
- `post_ir.json` — the target IR
- `migrations_config.json` *(optional)* — operator ack and rename mappings
- `expected_post_state.json` — `{ <content_name>: [records...], ... }`

Test:
1. Compiles `pre_ir.json` to a `.termin.pkg` (via the compiler) — or uses a pre-built fixture
2. Boots the runtime, loads pre_seed
3. Computes diff `pre_ir → post_ir`, classifies
4. Calls `provider.migrate(diff)`
5. Reads every content type via the runtime's CRUD API
6. Asserts equality with `expected_post_state.json`

The runtime-read comparison was chosen over SQL dumps so the fixtures
are portable across providers — a Postgres or DynamoDB provider runs
the same fixtures, asserts the same record sets via the same query
contract.

### `fault_injection/<case-name>/`

Each case is a directory containing:

- `pre_ir.json` — the IR the pre-state was created from
- `pre_seed.json` — the seed records inserted before migration
- `post_ir.json` — the target IR
- `inject_at.txt` — one of `pre_apply` | `mid_apply` | `pre_commit`
- `migrations_config.json` *(optional)* — operator ack
- `expected_post_state.json` — the SAME state as pre_seed (atomicity preserves it)

Test:
1. Boots the runtime + loads pre_seed
2. Reads pre-state via runtime CRUD
3. Arms the provider via `provider._inject_fault_at(inject_at)`
4. Calls `provider.migrate(diff)` — must raise `ProviderInjectedFault`
5. Reads post-state via runtime CRUD
6. Asserts post-state == pre-state (atomicity)

### `e2e/<case-name>/`

End-to-end migration cases. Each case is a directory containing:

- `pre_ir.json` — initial IR
- `pre_seed.json` — initial data
- `post_ir.json` — target IR
- `migrations_config.json` — full deploy config migrations block
- `expected_outcome.json` — `{ "kind": "success", "post_state": {...} }` OR `{ "kind": "refused", "error_code": "TERMIN-M00X", "missing_acks": [...] }` OR `{ "kind": "blocked", "error_code": "TERMIN-M001" }`

Test runs the full deploy flow and asserts the outcome.

### `v08_round_trip/`

The headline cross-version test. Single fixture set:

- `v08_app.db` — captured from a real v0.8.1 reference runtime
- `v08_ir.json` — the v0.8 IR (introspectable from sqlite_master if missing)
- `v09_target_ir.json` — the v0.9 IR (same source compiled by v0.9 compiler)
- `migrations_config.json` — operator ack covering the v0.8 → v0.9 changes
- `expected_post_state.json` — record set after migration

This fixture is generated once via a temp clone of the compiler at the
v0.8.1 tag (per `_gen.py --capture-v08`); subsequent test runs reuse
the captured `v08_app.db`.

## Adding a fixture

1. Pick a category and create a subdir under `fixtures/migrations/<category>/<case-name>/`.
2. Author the input files per the format above. For `classifier` and `ack_gating`, hand-author the JSON. For `apply`, `fault_injection`, and `e2e`, run `_gen.py` to capture the expected outcome from the reference runtime.
3. Add the case to the corresponding test file's parametrize list (`tests/test_v09_migration_*.py`).
4. Run the test against the reference adapter to verify it passes.

## Regenerating fixtures

```bash
python fixtures/migrations/_gen.py --case <category>/<case-name>
```

The generator reads the case's `pre_ir.json` + `pre_seed.json` + `post_ir.json`
and produces or refreshes the expected outcome files. Fixtures are
deterministic — running the generator on a clean tree should produce
no diff if the runtime hasn't changed semantics.
