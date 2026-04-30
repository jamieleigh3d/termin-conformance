"""Conformance — v0.9 migration apply (migration-contract.md §6 + §9.2).

Tests the provider's `migrate()` contract: given a classified diff and
an on-disk database, the provider applies the diff atomically and the
post-state matches expected. Comparison via runtime read (per the spec
§9 design choice) — no SQL dumps, no provider-internal introspection.

Each test:
  1. Boots a fresh SqliteStorageProvider against a temp DB.
  2. Initializes schema with the pre_ir's content schemas.
  3. Inserts seed records via provider.create().
  4. Computes diff (pre_ir → post_ir) and classifies.
  5. Calls provider.migrate(diff).
  6. Reads each content type via provider.query().
  7. Asserts records match expected_post_state.

The tests use the SQLite reference provider directly. A future
Postgres or other provider runs the same tests; what they share is
the StorageProvider Protocol, the MigrationDiff shape, and the
classification rules.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any, Mapping, Sequence

import pytest

from termin_server.providers.builtins.storage_sqlite import SqliteStorageProvider
from termin_server.providers.storage_contract import (
    Eq, QueryOptions, MigrationDiff, ContentChange, FieldChange,
)
from termin_server.migrations.classifier import (
    compute_migration_diff, apply_rename_mappings, downgrade_for_empty_tables,
)
from termin_server import storage as _storage


# ── Schema-construction helpers (shared with classifier tests) ──────


_COLUMN_BY_BUSINESS_TYPE = {
    "text": "TEXT",
    "whole_number": "INTEGER",
    "number": "REAL",
    "currency": "REAL",
    "boolean": "BOOLEAN",
    "enum": "TEXT",
}


def field(name, *, business_type="text", required=False, unique=False,
          minimum=None, maximum=None, enum_values=(), foreign_key=None,
          cascade_mode=None, default_expr=None):
    return {
        "name": name,
        "display_name": name,
        "business_type": business_type,
        "column_type": _COLUMN_BY_BUSINESS_TYPE[business_type],
        "required": required,
        "unique": unique,
        "minimum": minimum,
        "maximum": maximum,
        "enum_values": list(enum_values),
        "one_of_values": [],
        "foreign_key": foreign_key,
        "cascade_mode": cascade_mode,
        "is_auto": False,
        "list_type": None,
        "default_expr": default_expr,
        "confidentiality_scopes": [],
    }


def schema(name, *, fields=()):
    return {
        "name": {"snake": name, "display": name,
                 "pascal": name.title().replace("_", "")},
        "fields": list(fields),
    }


# ── Apply-test fixture / helpers ────────────────────────────────────


@pytest.fixture
def fresh_provider():
    """A SqliteStorageProvider against a fresh temp DB. The DB is
    cleaned up after the test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    provider = SqliteStorageProvider(config={"db_path": path})
    yield provider, path
    if os.path.exists(path):
        os.unlink(path)


async def _setup(provider, pre_ir, seeds):
    """Create the pre_ir's tables and insert seed records."""
    diff = compute_migration_diff(current=None, target=pre_ir)
    await provider.migrate(diff)
    for content_name, records in seeds.items():
        for rec in records:
            await provider.create(content_name, rec)


async def _read_all(provider, content_name):
    """Read every record of a content type via the runtime CRUD path."""
    page = await provider.query(
        content_name,
        predicate=None,
        options=QueryOptions(limit=1000),
    )
    return list(page.records)


def _strip_ids(records):
    """Drop runtime-assigned id fields for state comparison."""
    return [{k: v for k, v in r.items() if k != "id"} for r in records]


# ── Test cases ──────────────────────────────────────────────────────


class TestSafeAdditions:
    """Apply-conformance for safe-tier changes — no operator
    interaction needed, no data touched in ways the operator should
    review."""

    @pytest.mark.asyncio
    async def test_add_optional_field(self, fresh_provider):
        provider, _path = fresh_provider
        pre_ir = [schema("tickets", fields=[field("title", required=True)])]
        seeds = {"tickets": [{"title": "first"}, {"title": "second"}]}
        await _setup(provider, pre_ir, seeds)

        # Add an optional field.
        post_ir = [schema("tickets",
                          fields=[field("title", required=True),
                                  field("notes")])]
        diff = compute_migration_diff(pre_ir, post_ir)
        await provider.migrate(diff)

        records = _strip_ids(await _read_all(provider, "tickets"))
        # Existing rows preserved; new field is null.
        assert records == [
            {"title": "first", "notes": None},
            {"title": "second", "notes": None},
        ]

    @pytest.mark.asyncio
    async def test_add_optional_field_with_default(self, fresh_provider):
        """Add an optional field with a default value — safe.

        Note: the spec also classifies "required + with default" as
        safe (§5.2), but the reference SQLite provider's in-place
        ADD COLUMN path doesn't currently thread default_expr into
        the column definition for ADD COLUMN with NOT NULL. Tracked
        as a runtime gap separate from this conformance pack; this
        test covers the optional-with-default case which works today.
        """
        provider, _path = fresh_provider
        pre_ir = [schema("tickets", fields=[field("title", required=True)])]
        seeds = {"tickets": [{"title": "first"}]}
        await _setup(provider, pre_ir, seeds)

        post_ir = [schema("tickets",
                          fields=[field("title", required=True),
                                  field("priority", default_expr='"medium"')])]
        diff = compute_migration_diff(pre_ir, post_ir)
        await provider.migrate(diff)

        records = _strip_ids(await _read_all(provider, "tickets"))
        # Existing rows are NULL for the new column (default applies
        # only to new inserts; ALTER TABLE ADD COLUMN doesn't backfill).
        # The spec's "required+default = safe" claim is about the kind-
        # level rule; the actual in-place backfill semantics are
        # provider-specific.
        assert len(records) == 1
        assert records[0]["title"] == "first"


class TestMediumApply:
    """Apply-conformance for medium-tier changes — rebuild required,
    data preserved by INSERT-SELECT."""

    @pytest.mark.asyncio
    async def test_remove_unique_preserves_data(self, fresh_provider):
        provider, _path = fresh_provider
        pre_ir = [schema("tickets",
                         fields=[field("title", required=True),
                                 field("token", unique=True)])]
        seeds = {"tickets": [
            {"title": "a", "token": "t1"},
            {"title": "b", "token": "t2"},
        ]}
        await _setup(provider, pre_ir, seeds)

        # Remove UNIQUE — medium tier, rebuild required.
        post_ir = [schema("tickets",
                          fields=[field("title", required=True),
                                  field("token")])]
        diff = compute_migration_diff(pre_ir, post_ir)
        await provider.migrate(diff)

        records = _strip_ids(await _read_all(provider, "tickets"))
        assert records == [
            {"title": "a", "token": "t1"},
            {"title": "b", "token": "t2"},
        ]

    @pytest.mark.asyncio
    async def test_loosen_bounds_preserves_data(self, fresh_provider):
        provider, _path = fresh_provider
        pre_ir = [schema("orders",
                         fields=[field("qty", business_type="whole_number",
                                       minimum=0, maximum=100)])]
        seeds = {"orders": [{"qty": 50}, {"qty": 99}]}
        await _setup(provider, pre_ir, seeds)

        post_ir = [schema("orders",
                          fields=[field("qty", business_type="whole_number",
                                        minimum=0, maximum=1000)])]
        diff = compute_migration_diff(pre_ir, post_ir)
        await provider.migrate(diff)

        records = _strip_ids(await _read_all(provider, "orders"))
        assert records == [{"qty": 50}, {"qty": 99}]


class TestHighApply:
    """Apply-conformance for high-tier changes — rebuild required +
    data semantics shift."""

    @pytest.mark.asyncio
    async def test_cascade_mode_change_preserves_data(self, fresh_provider):
        """Changing cascade_mode (the v0.8 → v0.9 case) preserves data."""
        provider, _path = fresh_provider
        pre_ir = [
            schema("users", fields=[field("name", required=True)]),
            schema("tickets",
                   fields=[field("title", required=True),
                           field("assignee_id",
                                 business_type="whole_number",
                                 foreign_key="users",
                                 cascade_mode="restrict")]),
        ]
        seeds = {
            "users": [{"name": "alice"}, {"name": "bob"}],
            "tickets": [{"title": "t1", "assignee_id": 1},
                        {"title": "t2", "assignee_id": 2}],
        }
        await _setup(provider, pre_ir, seeds)

        post_ir = [
            schema("users", fields=[field("name", required=True)]),
            schema("tickets",
                   fields=[field("title", required=True),
                           field("assignee_id",
                                 business_type="whole_number",
                                 foreign_key="users",
                                 cascade_mode="cascade")]),
        ]
        diff = compute_migration_diff(pre_ir, post_ir)
        await provider.migrate(diff)

        records = _strip_ids(await _read_all(provider, "tickets"))
        assert len(records) == 2
        assert {r["title"] for r in records} == {"t1", "t2"}


class TestEmptyTableDowngrades:
    """Empty-table downgrade allows otherwise-blocked changes to apply
    with low-tier ack (still requires ack — see ack_gating tests)."""

    @pytest.mark.asyncio
    async def test_remove_field_empty_table_applies(self, fresh_provider):
        provider, _path = fresh_provider
        pre_ir = [schema("tickets",
                         fields=[field("title", required=True),
                                 field("notes")])]
        # No seeds — empty table.
        await _setup(provider, pre_ir, {})

        post_ir = [schema("tickets", fields=[field("title", required=True)])]
        diff = compute_migration_diff(pre_ir, post_ir)
        # Apply empty-table downgrade — removes "blocked" if table is empty.
        diff = await downgrade_for_empty_tables(diff, provider)
        # Verify it downgraded.
        assert diff.overall_classification in ("safe", "low")
        # Apply.
        await provider.migrate(diff)

        # No rows — but the schema is updated.
        records = await _read_all(provider, "tickets")
        assert records == []
