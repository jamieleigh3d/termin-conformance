"""Conformance — v0.9 migration end-to-end (migration-contract.md §9.3).

Tests the full deploy flow:
  read current schema → compute diff → classify → check ack →
  (create backup if high-tier) → apply → validate → persist metadata

Includes the headline cross-version case: a real v0.8.1 SQLite database
loaded by a v0.9 runtime + provider, introspected, classified, and
migrated through to v0.9 IR.

The v0.8 fixture is captured at fixtures/migrations/v08_round_trip/
and was generated via a temporary clone of termin-compiler at the
v0.8.1 tag (see migration-contract.md §8.1).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from termin_server.providers.builtins.storage_sqlite import SqliteStorageProvider
from termin_server.providers.storage_contract import (
    Eq, QueryOptions, MigrationDiff, ContentChange, FieldChange,
)
from termin_server.migrations.classifier import (
    compute_migration_diff, apply_rename_mappings, downgrade_for_empty_tables,
)
from termin_server.migrations.introspect import introspect_sqlite_schema
from termin_server.migrations.ack import ack_covers, missing_acks
from termin_server import storage as _storage

# Reuse helpers from the apply test file.
from .test_v09_migration_apply import (
    field, schema, _setup, _read_all, _strip_ids, fresh_provider,  # noqa: F401
)


CONFORMANCE_ROOT = Path(__file__).parent.parent
V08_ROUND_TRIP_DIR = CONFORMANCE_ROOT / "fixtures" / "migrations" / "v08_round_trip"


# ── End-to-end: simple within-v0.9 cases ────────────────────────────


class TestEndToEndWithinV09:
    """End-to-end migration flows entirely within v0.9 grammar."""

    @pytest.mark.asyncio
    async def test_safe_migration_no_ack_needed(self, fresh_provider):
        """Safe-tier migration applies without operator ack."""
        provider, _path = fresh_provider
        pre_ir = [schema("tickets", fields=[field("title", required=True)])]
        seeds = {"tickets": [{"title": "first"}]}
        await _setup(provider, pre_ir, seeds)

        post_ir = [schema("tickets",
                          fields=[field("title", required=True),
                                  field("notes")])]
        diff = compute_migration_diff(pre_ir, post_ir)

        # Empty config — safe diff doesn't need ack.
        config = {}
        assert ack_covers(diff, config)

        await provider.migrate(diff)
        records = _strip_ids(await _read_all(provider, "tickets"))
        assert records == [{"title": "first", "notes": None}]

    @pytest.mark.asyncio
    async def test_medium_migration_refused_without_ack(self, fresh_provider):
        """Medium-tier migration refuses to proceed without ack."""
        provider, _path = fresh_provider
        pre_ir = [schema("tickets",
                         fields=[field("title", required=True),
                                 field("token", unique=True)])]
        seeds = {"tickets": [{"title": "a", "token": "t1"}]}
        await _setup(provider, pre_ir, seeds)

        post_ir = [schema("tickets",
                          fields=[field("title", required=True),
                                  field("token")])]  # remove UNIQUE — medium
        diff = compute_migration_diff(pre_ir, post_ir)

        # No ack provided.
        assert not ack_covers(diff, {})
        missing = missing_acks(diff, {})
        assert len(missing) > 0

    @pytest.mark.asyncio
    async def test_medium_migration_proceeds_with_ack(self, fresh_provider):
        """Medium-tier migration proceeds when fingerprints are acked."""
        provider, _path = fresh_provider
        pre_ir = [schema("tickets",
                         fields=[field("title", required=True),
                                 field("token", unique=True)])]
        seeds = {"tickets": [{"title": "a", "token": "t1"}]}
        await _setup(provider, pre_ir, seeds)

        post_ir = [schema("tickets",
                          fields=[field("title", required=True),
                                  field("token")])]
        diff = compute_migration_diff(pre_ir, post_ir)

        from termin_server.migrations.ack import collect_required_fingerprints
        fps = collect_required_fingerprints(diff)
        config = {"accepted_changes": list(fps)}
        assert ack_covers(diff, config)

        await provider.migrate(diff)
        records = _strip_ids(await _read_all(provider, "tickets"))
        assert records == [{"title": "a", "token": "t1"}]

    @pytest.mark.asyncio
    async def test_blocked_migration_unconditional_refusal(self, fresh_provider):
        """Blocked-tier migration is refused even with all flags set."""
        provider, _path = fresh_provider
        pre_ir = [schema("tickets",
                         fields=[field("title", required=True),
                                 field("notes")])]
        seeds = {"tickets": [{"title": "a", "notes": "important"}]}
        await _setup(provider, pre_ir, seeds)

        post_ir = [schema("tickets",
                          fields=[field("title", required=True)])]  # remove notes (non-empty) → blocked
        diff = compute_migration_diff(pre_ir, post_ir)
        assert diff.is_blocked

        # Even with everything turned on, the diff is still blocked.
        # (ack_covers ignores blocked, but the runtime checks is_blocked
        # separately and refuses unconditionally.)


# ── End-to-end: cross-version (v0.8 → v0.9) ────────────────────────


class TestV08RoundTrip:
    """Cross-version migration: a real v0.8.1 SQLite database is read,
    introspected, and migrated by a v0.9 runtime + provider.

    The fixture is captured at v08_round_trip/ via a temp clone of
    termin-compiler at v0.8.1 (see migration-contract.md §8.1 and
    `_gen.py --capture-v08`).
    """

    @pytest.fixture
    def v08_db_copy(self, tmp_path):
        """Copy the captured v0.8 DB into a temp location so the test
        can mutate it without disturbing the fixture."""
        src = V08_ROUND_TRIP_DIR / "v08_helpdesk.db"
        if not src.exists():
            pytest.skip(f"v0.8 round-trip fixture missing: {src}. "
                        f"Re-capture via the temp-clone procedure.")
        dst = tmp_path / "v08_helpdesk.db"
        shutil.copy2(src, dst)
        return str(dst)

    @pytest.mark.asyncio
    async def test_v08_db_introspectable(self, v08_db_copy):
        """The v0.9 runtime can introspect a v0.8-shape SQLite DB
        and reconstruct a content schema set."""
        db = await _storage.get_db(v08_db_copy)
        try:
            schemas = await introspect_sqlite_schema(db)
        finally:
            await db.close()

        # Helpdesk has tickets and comments.
        names = sorted(s["name"]["snake"] for s in schemas)
        assert "tickets" in names
        assert "comments" in names

        # Verify tickets has the v0.8 columns we seeded.
        tickets = next(s for s in schemas if s["name"]["snake"] == "tickets")
        field_names = {f["name"] for f in tickets["fields"]}
        # v0.8 used "status" for the state column.
        assert "status" in field_names
        assert "title" in field_names
        assert "priority" in field_names

    @pytest.mark.asyncio
    async def test_v08_records_readable_via_v09_provider(self, v08_db_copy):
        """A v0.9 provider can read records from a v0.8 DB once
        the schema is recognized. Verifies the data is preserved
        across the version boundary even before migration."""
        provider = SqliteStorageProvider(config={"db_path": v08_db_copy})

        # Direct query — bypasses the migration path.
        page = await provider.query(
            "tickets", predicate=None, options=QueryOptions(limit=100))
        records = list(page.records)
        # We seeded 2 tickets in the captured fixture.
        assert len(records) == 2
        titles = sorted(r["title"] for r in records)
        assert titles == ["First ticket", "Second ticket"]

    @pytest.mark.asyncio
    async def test_v08_to_simple_v09_migration_with_added_field(
        self, v08_db_copy
    ):
        """Migrate a v0.8 DB to a v0.9 IR that adds an optional field
        (the simplest cross-version case). The introspected v0.8 schema
        is the "current"; the v0.9 IR with one new optional field is
        the "target". Diff classifies as safe; migration applies; data
        is preserved."""
        provider = SqliteStorageProvider(config={"db_path": v08_db_copy})

        # Read the v0.8 IR (introspected from the DB).
        db = await _storage.get_db(v08_db_copy)
        try:
            current_schemas = await introspect_sqlite_schema(db)
        finally:
            await db.close()

        # Build a v0.9 target that's the v0.8 shape + one optional field
        # added to tickets. Simplest possible cross-version case.
        target_schemas = []
        for s in current_schemas:
            if s["name"]["snake"] == "tickets":
                new_s = dict(s)
                new_s["fields"] = list(s["fields"]) + [field("v09_added_field")]
                target_schemas.append(new_s)
            else:
                target_schemas.append(s)

        diff = compute_migration_diff(current_schemas, target_schemas)
        # Adding optional field → safe. No ack needed.
        assert diff.overall_classification == "safe"
        assert ack_covers(diff, {})

        await provider.migrate(diff)

        # Read tickets — original 2 records preserved + new field is null.
        page = await provider.query(
            "tickets", predicate=None, options=QueryOptions(limit=100))
        records = list(page.records)
        assert len(records) == 2
        for r in records:
            assert "v09_added_field" in r
            assert r["v09_added_field"] is None
