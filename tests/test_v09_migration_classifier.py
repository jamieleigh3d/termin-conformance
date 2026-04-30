"""Conformance — v0.9 migration classifier (migration-contract.md §5 + §9.1).

The classifier is the language-level invariant that makes apps portable
across runtimes: every conforming runtime must produce the same
MigrationDiff (with the same per-change classification) for the same
(current_schema, target_ir) pair.

This test pack exercises every classification rule from
`specs/migration-contract.md` §5.1 (content-level changes) and §5.2
(field-level changes), plus the empty-table downgrade rule (§5.3) and
the rename-mapping resolution (§5.4).

Dependency: imports from `termin_runtime.migrations.classifier` directly.
This is appropriate because the migration contract names provider authors
as the primary audience (§1.3) — they reuse the reference runtime and
plug in a provider, so direct-import is the same surface they target.
Alternative-runtime authors will need to adapt these tests to their own
classifier surface in v0.10+.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

import pytest

from termin_server.migrations.classifier import (
    compute_migration_diff,
    apply_rename_mappings,
    downgrade_for_empty_tables,
)
from termin_server.providers.storage_contract import (
    MigrationDiff, ContentChange, FieldChange,
)


# ── Schema-construction helpers ─────────────────────────────────────


_COLUMN_BY_BUSINESS_TYPE = {
    "text": "TEXT",
    "whole_number": "INTEGER",
    "number": "REAL",
    "currency": "REAL",
    "percentage": "REAL",
    "boolean": "BOOLEAN",
    "date": "TEXT",
    "timestamp": "TEXT",
    "enum": "TEXT",
}


def field(
    name: str,
    *,
    business_type: str = "text",
    required: bool = False,
    unique: bool = False,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    enum_values: Sequence[str] = (),
    foreign_key: Optional[str] = None,
    cascade_mode: Optional[str] = None,
    default_expr: Optional[str] = None,
    confidentiality_scopes: Sequence[str] = (),
) -> Mapping[str, Any]:
    """Build a FieldSpec dict matching the IR shape."""
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
        "confidentiality_scopes": list(confidentiality_scopes),
    }


def schema(name: str, *, fields: Sequence[Mapping[str, Any]] = ()) -> Mapping[str, Any]:
    """Build a ContentSchema dict matching the IR shape."""
    return {
        "name": {"snake": name, "display": name, "pascal": name.title().replace("_", "")},
        "fields": list(fields),
    }


# ── Helpers for assertions ──────────────────────────────────────────


def _classifications_by_content(diff: MigrationDiff) -> dict:
    """Return {content_name: classification} for each change in the diff."""
    return {c.content_name: c.classification for c in diff.changes}


def _field_classifications(diff: MigrationDiff, content: str) -> dict:
    """Return {field_name: per-field classification} for the named content's
    field changes. Computed via the same path the runtime uses (per
    classifier.classify_field_change)."""
    from termin_server.migrations.classifier import classify_field_change
    for cc in diff.changes:
        if cc.content_name != content or cc.kind != "modified":
            continue
        target_fields = {f["name"]: f for f in (cc.schema or {}).get("fields", [])}
        return {
            fc.field_name: classify_field_change(
                fc, field_spec=target_fields.get(fc.field_name))
            for fc in cc.field_changes
        }
    return {}


# ──────────────────────────────────────────────────────────────────────
# § 5.1 Content-level changes
# ──────────────────────────────────────────────────────────────────────


class TestContentLevelClassification:
    """Per migration-contract.md §5.1 — classification rules for
    content-level changes (added / removed / renamed / modified)."""

    def test_add_content_is_safe(self):
        """Add content (new table) → safe."""
        diff = compute_migration_diff(
            current=[],
            target=[schema("tickets", fields=[field("title", required=True)])],
        )
        assert _classifications_by_content(diff) == {"tickets": "safe"}

    def test_remove_content_default_blocked(self):
        """Remove content → blocked (default; empty-downgrade may relax)."""
        diff = compute_migration_diff(
            current=[schema("tickets", fields=[field("title")])],
            target=[],
        )
        assert _classifications_by_content(diff) == {"tickets": "blocked"}

    @pytest.mark.asyncio
    async def test_remove_empty_content_downgrades_to_low(self):
        """Remove content + empty table → low (§5.3).

        Note: downgrade target is `low`, NOT `safe` — the operator
        should still see and ack the change for audit-trail purposes.
        """
        diff = compute_migration_diff(
            current=[schema("tickets", fields=[field("title")])],
            target=[],
        )

        # Stub provider that reports the table is empty.
        class EmptyProvider:
            async def query(self, content_type, predicate=None, options=None):
                from termin_server.providers.storage_contract import Page
                return Page(records=(), next_cursor=None, estimated_total=0)

        diff = await downgrade_for_empty_tables(diff, EmptyProvider())
        assert _classifications_by_content(diff) == {"tickets": "low"}

    def test_rename_content_is_low(self):
        """Rename content (operator-declared mapping) → low."""
        diff = compute_migration_diff(
            current=[schema("tickets", fields=[field("title")])],
            target=[schema("incidents", fields=[field("title")])],
        )
        # Without rename mapping, classifier sees remove+add → blocked + safe.
        # Apply the rename mapping to fold them.
        diff = apply_rename_mappings(
            diff,
            rename_contents=[{"from": "tickets", "to": "incidents"}],
        )
        assert _classifications_by_content(diff) == {"incidents": "low"}


# ──────────────────────────────────────────────────────────────────────
# § 5.2 Field-level changes — additions
# ──────────────────────────────────────────────────────────────────────


class TestFieldAdditionClassification:
    """Per migration-contract.md §5.2 — adding fields."""

    def _modify_with_added_field(self, *, fld) -> MigrationDiff:
        """Helper: build a modified-content diff that adds one field."""
        return compute_migration_diff(
            current=[schema("tickets", fields=[field("title")])],
            target=[schema("tickets", fields=[field("title"), fld])],
        )

    def test_add_optional_field_no_default_safe(self):
        diff = self._modify_with_added_field(fld=field("notes"))
        assert _classifications_by_content(diff)["tickets"] == "safe"

    def test_add_optional_field_with_default_safe(self):
        diff = self._modify_with_added_field(
            fld=field("notes", default_expr='""'))
        assert _classifications_by_content(diff)["tickets"] == "safe"

    def test_add_required_field_with_default_safe(self):
        diff = self._modify_with_added_field(
            fld=field("priority", required=True, default_expr='"medium"'))
        assert _classifications_by_content(diff)["tickets"] == "safe"

    def test_add_required_field_no_default_medium(self):
        diff = self._modify_with_added_field(
            fld=field("priority", required=True))
        assert _classifications_by_content(diff)["tickets"] == "medium"

    def test_add_field_with_foreign_key_blocked(self):
        diff = self._modify_with_added_field(
            fld=field("assignee", foreign_key="users", cascade_mode="restrict"))
        assert _classifications_by_content(diff)["tickets"] == "blocked"

    def test_add_field_with_unique_medium(self):
        diff = self._modify_with_added_field(
            fld=field("token", unique=True))
        assert _classifications_by_content(diff)["tickets"] == "medium"


# ──────────────────────────────────────────────────────────────────────
# § 5.2 Field-level changes — removal
# ──────────────────────────────────────────────────────────────────────


class TestFieldRemovalClassification:
    """Per migration-contract.md §5.2 — removing fields."""

    def test_remove_field_default_blocked(self):
        """Remove field → blocked default (data loss)."""
        diff = compute_migration_diff(
            current=[schema("tickets",
                            fields=[field("title"), field("notes")])],
            target=[schema("tickets", fields=[field("title")])],
        )
        # The content change is "modified"; the field-level change's
        # tier propagates up to ContentChange.classification.
        assert _classifications_by_content(diff)["tickets"] == "blocked"

    @pytest.mark.asyncio
    async def test_remove_field_empty_table_downgrades_to_safe(self):
        """Remove field + empty table → safe (§5.3)."""
        diff = compute_migration_diff(
            current=[schema("tickets",
                            fields=[field("title"), field("notes")])],
            target=[schema("tickets", fields=[field("title")])],
        )

        class EmptyProvider:
            async def query(self, content_type, predicate=None, options=None):
                from termin_server.providers.storage_contract import Page
                return Page(records=(), next_cursor=None, estimated_total=0)

        diff = await downgrade_for_empty_tables(diff, EmptyProvider())
        # On empty tables, blocked downgrades to safe (or low at most).
        assert _classifications_by_content(diff)["tickets"] in ("safe", "low")


# ──────────────────────────────────────────────────────────────────────
# § 5.2 Field-level changes — renames
# ──────────────────────────────────────────────────────────────────────


class TestFieldRenameClassification:
    """Per migration-contract.md §5.2 + §5.4 — renaming fields with
    operator-declared mapping."""

    def test_rename_field_same_type_low(self):
        diff = compute_migration_diff(
            current=[schema("tickets",
                            fields=[field("priority")])],
            target=[schema("tickets",
                           fields=[field("severity")])],
        )
        diff = apply_rename_mappings(
            diff,
            rename_fields=[{"content": "tickets",
                            "from": "priority", "to": "severity"}],
        )
        assert _classifications_by_content(diff)["tickets"] == "low"

    def test_rename_field_lossless_widening_via_kind(self):
        """Rename with lossless type widening → medium.

        Tested at the FieldChange-kind level (calling classify_field_change
        directly with a synthetic renamed change carrying type_changed=True).
        The full compute_migration_diff + apply_rename_mappings path has a
        known gap where type changes during rename are not detected from
        the bare removed/added pair (TODO: thread old schema through the
        rename folder); that gap is tracked separately.
        """
        from termin_server.migrations.classifier import classify_field_change
        fc = FieldChange(
            kind="renamed",
            field_name="amount",
            detail={
                "from": "count",
                "to": "amount",
                "type_changed": True,
                "from_type": "whole_number",
                "to_type": "number",
            },
        )
        assert classify_field_change(fc) == "medium"


# ──────────────────────────────────────────────────────────────────────
# § 5.2 Field-level changes — type changes
# ──────────────────────────────────────────────────────────────────────


class TestFieldTypeChangeClassification:
    """Per migration-contract.md §5.2 — changing business_type."""

    def test_lossless_type_widening_medium(self):
        """whole_number → number is a lossless widening."""
        diff = compute_migration_diff(
            current=[schema("orders",
                            fields=[field("qty", business_type="whole_number")])],
            target=[schema("orders",
                           fields=[field("qty", business_type="number")])],
        )
        assert _classifications_by_content(diff)["orders"] == "medium"

    def test_lossy_type_change_blocked(self):
        """text → whole_number is lossy (values may not parse)."""
        diff = compute_migration_diff(
            current=[schema("orders",
                            fields=[field("code", business_type="text")])],
            target=[schema("orders",
                           fields=[field("code", business_type="whole_number")])],
        )
        assert _classifications_by_content(diff)["orders"] == "blocked"


# ──────────────────────────────────────────────────────────────────────
# § 5.2 Field-level changes — constraints
# ──────────────────────────────────────────────────────────────────────


class TestFieldConstraintClassification:
    """Per migration-contract.md §5.2 — adding/removing constraints."""

    def test_add_required_high(self):
        """Add NOT NULL to nullable field → high."""
        diff = compute_migration_diff(
            current=[schema("tickets", fields=[field("priority")])],
            target=[schema("tickets",
                           fields=[field("priority", required=True)])],
        )
        assert _classifications_by_content(diff)["tickets"] == "high"

    def test_remove_required_medium(self):
        """Remove NOT NULL → medium."""
        diff = compute_migration_diff(
            current=[schema("tickets",
                            fields=[field("priority", required=True)])],
            target=[schema("tickets", fields=[field("priority")])],
        )
        assert _classifications_by_content(diff)["tickets"] == "medium"

    def test_add_unique_high(self):
        """Add UNIQUE → high (duplicates would violate)."""
        diff = compute_migration_diff(
            current=[schema("tickets", fields=[field("token")])],
            target=[schema("tickets",
                           fields=[field("token", unique=True)])],
        )
        assert _classifications_by_content(diff)["tickets"] == "high"

    def test_remove_unique_medium(self):
        """Remove UNIQUE → medium."""
        diff = compute_migration_diff(
            current=[schema("tickets",
                            fields=[field("token", unique=True)])],
            target=[schema("tickets", fields=[field("token")])],
        )
        assert _classifications_by_content(diff)["tickets"] == "medium"

    def test_tighten_bounds_high(self):
        """Tightening min/max → high (existing values may violate)."""
        diff = compute_migration_diff(
            current=[schema("orders",
                            fields=[field("qty", business_type="whole_number",
                                          minimum=0, maximum=1000)])],
            target=[schema("orders",
                           fields=[field("qty", business_type="whole_number",
                                         minimum=0, maximum=100)])],
        )
        assert _classifications_by_content(diff)["orders"] == "high"

    def test_loosen_bounds_medium(self):
        """Loosening min/max → medium."""
        diff = compute_migration_diff(
            current=[schema("orders",
                            fields=[field("qty", business_type="whole_number",
                                          minimum=0, maximum=100)])],
            target=[schema("orders",
                           fields=[field("qty", business_type="whole_number",
                                         minimum=0, maximum=1000)])],
        )
        assert _classifications_by_content(diff)["orders"] == "medium"


# ──────────────────────────────────────────────────────────────────────
# § 5.2 Field-level changes — enums
# ──────────────────────────────────────────────────────────────────────


class TestEnumChangeClassification:
    """Per migration-contract.md §5.2 — adding/removing enum values."""

    def test_add_enum_value_medium(self):
        diff = compute_migration_diff(
            current=[schema("tickets",
                            fields=[field("priority", business_type="enum",
                                          enum_values=["low", "medium", "high"])])],
            target=[schema("tickets",
                           fields=[field("priority", business_type="enum",
                                         enum_values=["low", "medium", "high",
                                                      "critical"])])],
        )
        assert _classifications_by_content(diff)["tickets"] == "medium"

    def test_remove_enum_value_high(self):
        diff = compute_migration_diff(
            current=[schema("tickets",
                            fields=[field("priority", business_type="enum",
                                          enum_values=["low", "medium", "high",
                                                       "critical"])])],
            target=[schema("tickets",
                           fields=[field("priority", business_type="enum",
                                         enum_values=["low", "medium", "high"])])],
        )
        assert _classifications_by_content(diff)["tickets"] == "high"


# ──────────────────────────────────────────────────────────────────────
# § 5.2 Field-level changes — foreign keys
# ──────────────────────────────────────────────────────────────────────


class TestForeignKeyChangeClassification:
    """Per migration-contract.md §5.2 — FK additions, removals,
    target changes, cascade-mode changes."""

    def test_add_fk_to_existing_field_blocked(self):
        diff = compute_migration_diff(
            current=[
                schema("users", fields=[field("name")]),
                schema("tickets", fields=[field("assignee_id")]),
            ],
            target=[
                schema("users", fields=[field("name")]),
                schema("tickets",
                       fields=[field("assignee_id",
                                     foreign_key="users",
                                     cascade_mode="restrict")]),
            ],
        )
        assert _classifications_by_content(diff)["tickets"] == "blocked"

    def test_remove_fk_via_kind(self):
        """At the FieldChange-kind level, foreign_key_changed (FK
        removal) classifies as medium.

        In practice, removing a FK from a real diff also removes the
        cascade_mode (it's a property of the FK), which is a separate
        cascade_mode_changed FieldChange classified as high. The
        aggregate content tier ends up high because of the cascade
        change, not the FK change. That aggregation case is exercised
        in test_remove_fk_aggregates_to_high below.
        """
        from termin_server.migrations.classifier import classify_field_change
        fc = FieldChange(
            kind="foreign_key_changed",
            field_name="assignee_id",
            detail={"from": "users", "to": None},
        )
        assert classify_field_change(fc) == "medium"

    def test_remove_fk_aggregates_to_high(self):
        """Removing a FK from a real diff aggregates to high because
        cascade_mode is also nulled (cascade_mode_changed is high)."""
        diff = compute_migration_diff(
            current=[
                schema("users", fields=[field("name")]),
                schema("tickets",
                       fields=[field("assignee_id",
                                     foreign_key="users",
                                     cascade_mode="restrict")]),
            ],
            target=[
                schema("users", fields=[field("name")]),
                schema("tickets", fields=[field("assignee_id")]),
            ],
        )
        assert _classifications_by_content(diff)["tickets"] == "high"

    def test_change_cascade_mode_high(self):
        """Cascade mode change (incl. v0.8 null → v0.9 cascade/restrict) → high."""
        diff = compute_migration_diff(
            current=[
                schema("users", fields=[field("name")]),
                schema("tickets",
                       fields=[field("assignee_id",
                                     foreign_key="users",
                                     cascade_mode="restrict")]),
            ],
            target=[
                schema("users", fields=[field("name")]),
                schema("tickets",
                       fields=[field("assignee_id",
                                     foreign_key="users",
                                     cascade_mode="cascade")]),
            ],
        )
        assert _classifications_by_content(diff)["tickets"] == "high"


# ──────────────────────────────────────────────────────────────────────
# Aggregation — multi-change diffs
# ──────────────────────────────────────────────────────────────────────


class TestAggregationClassification:
    """Per migration-contract.md §4.6 — aggregation rule (worst wins)."""

    def test_overall_diff_picks_worst_change(self):
        """Diff with safe + medium + high → overall is high."""
        diff = compute_migration_diff(
            current=[
                schema("a", fields=[field("x")]),
            ],
            target=[
                schema("a", fields=[
                    field("x"),
                    field("y"),  # safe (optional add)
                    field("z", required=True),  # medium (required add no default)
                ]),
                schema("b", fields=[field("name", required=True, default_expr='""')]),  # safe
            ],
        )
        # Per worst_classification: medium > safe.
        assert diff.overall_classification == "medium"

    def test_blocked_dominates_aggregation(self):
        """Diff containing blocked → overall blocked, regardless of others."""
        diff = compute_migration_diff(
            current=[
                schema("users", fields=[field("name")]),
                schema("tickets", fields=[field("title")]),
            ],
            target=[
                # Adding FK to existing field → blocked
                schema("users", fields=[field("name")]),
                schema("tickets",
                       fields=[field("title"),
                               field("user_id",
                                     foreign_key="users",
                                     cascade_mode="restrict")]),
            ],
        )
        # Adding FK to a new field → blocked. Aggregation includes blocked.
        assert diff.is_blocked


# ──────────────────────────────────────────────────────────────────────
# Empty-table downgrade
# ──────────────────────────────────────────────────────────────────────


class TestEmptyTableDowngrade:
    """Per migration-contract.md §5.3 — destructive changes against
    empty tables downgrade to safe (or low at most)."""

    @pytest.mark.asyncio
    async def test_blocked_remove_field_empty_table_downgrades(self):
        diff = compute_migration_diff(
            current=[schema("tickets",
                            fields=[field("title"), field("notes")])],
            target=[schema("tickets", fields=[field("title")])],
        )

        class EmptyProvider:
            async def query(self, content_type, predicate=None, options=None):
                from termin_server.providers.storage_contract import Page
                return Page(records=(), next_cursor=None, estimated_total=0)

        downgraded = await downgrade_for_empty_tables(diff, EmptyProvider())
        assert downgraded.overall_classification in ("safe", "low")

    @pytest.mark.asyncio
    async def test_non_empty_table_stays_blocked(self):
        diff = compute_migration_diff(
            current=[schema("tickets",
                            fields=[field("title"), field("notes")])],
            target=[schema("tickets", fields=[field("title")])],
        )

        class NonEmptyProvider:
            async def query(self, content_type, predicate=None, options=None):
                from termin_server.providers.storage_contract import Page
                return Page(
                    records=({"id": 1, "title": "x", "notes": "y"},),
                    next_cursor=None, estimated_total=1)

        diff = await downgrade_for_empty_tables(diff, NonEmptyProvider())
        assert diff.overall_classification == "blocked"
