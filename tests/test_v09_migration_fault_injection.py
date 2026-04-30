"""Conformance — v0.9 migration fault injection (migration-contract.md §6.2 + §9.4).

Tests the atomicity guarantee in the provider's `migrate()` contract:
a fault injected at any stage during migration must leave the database
observably identical to its pre-call state.

Three canonical stages (per migration-contract.md §6.2):

  - **pre_apply**  — fault before any change has been applied.
  - **mid_apply**  — fault after applying the first change but before all.
  - **pre_commit** — fault after all changes are applied but before commit.

The provider's `_inject_fault_at(stage)` test hook arms the next
`migrate()` call to raise `ProviderInjectedFault` at the named stage.
After the fault, post-call state read via runtime CRUD must equal the
pre-call state.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from termin_server.providers.builtins.storage_sqlite import SqliteStorageProvider
from termin_server.providers.storage_contract import (
    QueryOptions, ProviderInjectedFault,
)
from termin_server.migrations.classifier import compute_migration_diff

# Reuse helpers from the apply test file.
from .test_v09_migration_apply import (
    field, schema, _setup, _read_all, _strip_ids, fresh_provider,  # noqa: F401
)


# ── Multi-change diff helper (mid_apply requires multiple changes) ──


async def _multi_change_setup(provider):
    """Set up a pre-state with two content types so a 2-change diff
    can exercise mid_apply (which fires after the first change has
    been applied)."""
    pre_ir = [
        schema("widgets",
               fields=[field("name", required=True),
                       field("color")]),
        schema("gadgets",
               fields=[field("model", required=True),
                       field("size", business_type="whole_number",
                             minimum=0, maximum=100)]),
    ]
    seeds = {
        "widgets": [{"name": "w1", "color": "red"},
                    {"name": "w2", "color": "blue"}],
        "gadgets": [{"model": "g1", "size": 50},
                    {"model": "g2", "size": 75}],
    }
    await _setup(provider, pre_ir, seeds)
    return pre_ir, seeds


def _multi_change_target():
    """Target IR that triggers a modified change for both content
    types — gives us at least two changes for the mid_apply test."""
    return [
        # widgets: remove UNIQUE-less constraint (no-op shape change)
        schema("widgets",
               fields=[field("name", required=True),
                       field("color"),
                       field("notes")]),  # add optional field
        # gadgets: loosen bounds (medium tier rebuild)
        schema("gadgets",
               fields=[field("model", required=True),
                       field("size", business_type="whole_number",
                             minimum=0, maximum=1000)]),
    ]


async def _capture_state(provider, content_types):
    """Snapshot the records of multiple content types for comparison."""
    state = {}
    for ct in content_types:
        state[ct] = _strip_ids(await _read_all(provider, ct))
    return state


# ── Fault injection tests ───────────────────────────────────────────


class TestPreApplyFault:
    """Fault before any change has been applied — DB must be untouched."""

    @pytest.mark.asyncio
    async def test_pre_apply_preserves_state(self, fresh_provider):
        provider, _path = fresh_provider
        pre_ir, _seeds = await _multi_change_setup(provider)

        before = await _capture_state(provider, ["widgets", "gadgets"])

        post_ir = _multi_change_target()
        diff = compute_migration_diff(pre_ir, post_ir)

        provider._inject_fault_at("pre_apply")
        with pytest.raises(ProviderInjectedFault) as exc_info:
            await provider.migrate(diff)
        assert exc_info.value.stage == "pre_apply"

        after = await _capture_state(provider, ["widgets", "gadgets"])
        assert after == before


class TestMidApplyFault:
    """Fault after first change applied but before all — partial work
    must be rolled back."""

    @pytest.mark.asyncio
    async def test_mid_apply_preserves_state(self, fresh_provider):
        provider, _path = fresh_provider
        pre_ir, _seeds = await _multi_change_setup(provider)

        before = await _capture_state(provider, ["widgets", "gadgets"])

        post_ir = _multi_change_target()
        diff = compute_migration_diff(pre_ir, post_ir)
        # Sanity check: must have multiple changes for mid_apply
        # to fire meaningfully.
        assert len(diff.changes) >= 2

        provider._inject_fault_at("mid_apply")
        with pytest.raises(ProviderInjectedFault) as exc_info:
            await provider.migrate(diff)
        assert exc_info.value.stage == "mid_apply"

        # Atomicity: even though the first change had been applied,
        # the rollback must restore everything.
        after = await _capture_state(provider, ["widgets", "gadgets"])
        assert after == before


class TestPreCommitFault:
    """Fault after all changes applied but before commit — full
    rollback expected."""

    @pytest.mark.asyncio
    async def test_pre_commit_preserves_state(self, fresh_provider):
        provider, _path = fresh_provider
        pre_ir, _seeds = await _multi_change_setup(provider)

        before = await _capture_state(provider, ["widgets", "gadgets"])

        post_ir = _multi_change_target()
        diff = compute_migration_diff(pre_ir, post_ir)

        provider._inject_fault_at("pre_commit")
        with pytest.raises(ProviderInjectedFault) as exc_info:
            await provider.migrate(diff)
        assert exc_info.value.stage == "pre_commit"

        after = await _capture_state(provider, ["widgets", "gadgets"])
        assert after == before


class TestFaultIsOneShot:
    """The fault flag is one-shot — cleared after migrate() observes
    it. A subsequent migrate() runs unfaulted unless re-armed."""

    @pytest.mark.asyncio
    async def test_fault_does_not_persist(self, fresh_provider):
        provider, _path = fresh_provider
        pre_ir, _seeds = await _multi_change_setup(provider)

        post_ir = _multi_change_target()
        diff = compute_migration_diff(pre_ir, post_ir)

        # Fire a pre_apply fault.
        provider._inject_fault_at("pre_apply")
        with pytest.raises(ProviderInjectedFault):
            await provider.migrate(diff)

        # Second migrate() with the same diff should succeed (the
        # fault flag was cleared).
        await provider.migrate(diff)

        # And the migration applied — verify the new field exists.
        widgets = await _read_all(provider, "widgets")
        # First record should have the "notes" column (None default).
        assert widgets and "notes" in widgets[0]


class TestFaultStageValidation:
    """The provider validates the stage name."""

    @pytest.mark.asyncio
    async def test_unknown_stage_rejected(self, fresh_provider):
        provider, _path = fresh_provider
        with pytest.raises(ValueError, match="unknown fault-injection stage"):
            provider._inject_fault_at("not_a_real_stage")

    @pytest.mark.asyncio
    async def test_disarm_with_none(self, fresh_provider):
        """Pass None to disarm an armed fault."""
        provider, _path = fresh_provider
        pre_ir, _seeds = await _multi_change_setup(provider)
        post_ir = _multi_change_target()
        diff = compute_migration_diff(pre_ir, post_ir)

        provider._inject_fault_at("pre_apply")
        provider._inject_fault_at(None)  # disarm

        # Should run cleanly with no fault.
        await provider.migrate(diff)
