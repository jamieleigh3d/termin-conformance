"""Conformance — v0.9 migration ack gating (migration-contract.md §7.2 + §9.1).

Operator acknowledgment is the gate that lets a non-safe migration
proceed. The contract specifies two ack mechanisms:

  - **Per-change fingerprint ack** — operator lists each change's
    fingerprint in `migrations.accepted_changes`. Always honored,
    in any environment, for any tier (low/medium/high).

  - **Blanket-low flag** — `migrations.accept_any_low: true` covers
    every low-tier change, but only when `migrations.dev_mode: true`
    is also set. Refused in production (default `dev_mode: false`).
    Does NOT cover medium, high, or blocked changes regardless of
    dev_mode.

This test pack exercises the gating matrix:

  | dev_mode | accept_any_low | per-change ack | low covered | medium/high covered |
  |----------|----------------|----------------|-------------|----------------------|
  | false    | false          | none           | NO          | NO                   |
  | false    | true (inert)   | none           | NO          | NO                   |
  | true     | false          | none           | NO          | NO                   |
  | true     | true           | none           | YES         | NO                   |
  | any      | any            | matching       | YES         | YES                  |

Plus blocked never gets covered by anything.
"""

from __future__ import annotations

import pytest

from termin_server.migrations.ack import (
    ack_covers, missing_acks, fingerprint_change, collect_required_fingerprints,
)
from termin_server.providers.storage_contract import (
    MigrationDiff, ContentChange, FieldChange,
)


# ── Diff builders ───────────────────────────────────────────────────


def _low_diff():
    """A diff with a single low-tier change (a renamed field, same type)."""
    return MigrationDiff(changes=(
        ContentChange(kind="modified", content_name="tickets",
                      classification="low",
                      field_changes=(
                          FieldChange(kind="renamed",
                                      field_name="severity",
                                      detail={"from": "priority",
                                              "to": "severity",
                                              "type_changed": False}),
                      )),
    ))


def _medium_diff():
    """A diff with a single medium-tier change (loosen min/max)."""
    return MigrationDiff(changes=(
        ContentChange(kind="modified", content_name="orders",
                      classification="medium",
                      field_changes=(
                          FieldChange(kind="bounds_changed",
                                      field_name="qty",
                                      detail={"from": {"min": 0, "max": 100},
                                              "to": {"min": 0, "max": 1000},
                                              "tightening": False}),
                      )),
    ))


def _high_diff():
    """A diff with a single high-tier change (add NOT NULL)."""
    return MigrationDiff(changes=(
        ContentChange(kind="modified", content_name="x",
                      classification="high",
                      field_changes=(
                          FieldChange(kind="required_added", field_name="y"),
                      )),
    ))


def _blocked_diff():
    """A diff with a blocked change."""
    return MigrationDiff(changes=(
        ContentChange(kind="modified", content_name="x",
                      classification="blocked",
                      field_changes=(
                          FieldChange(kind="removed", field_name="y"),
                      )),
    ))


def _safe_diff():
    """A diff with only safe changes — never needs ack."""
    return MigrationDiff(changes=(
        ContentChange(kind="added", content_name="x", classification="safe"),
    ))


# ── Production-strict tests (default: dev_mode == false) ────────────


class TestProductionStrict:
    """The default posture is production-strict: only per-change ack
    is honored. Blanket flags are ignored regardless of value."""

    def test_no_ack_low_uncovered(self):
        assert not ack_covers(_low_diff(), {})
        assert missing_acks(_low_diff(), {})

    def test_no_ack_medium_uncovered(self):
        assert not ack_covers(_medium_diff(), {})

    def test_no_ack_high_uncovered(self):
        assert not ack_covers(_high_diff(), {})

    def test_blanket_low_inert_without_dev_mode(self):
        """accept_any_low alone (without dev_mode) is ignored."""
        assert not ack_covers(_low_diff(), {"accept_any_low": True})
        # And it doesn't accidentally cover medium either.
        assert not ack_covers(_medium_diff(), {"accept_any_low": True})

    def test_per_change_ack_covers_low(self):
        diff = _low_diff()
        fps = collect_required_fingerprints(diff)
        assert ack_covers(diff, {"accepted_changes": list(fps)})

    def test_per_change_ack_covers_medium_in_strict_mode(self):
        diff = _medium_diff()
        fps = collect_required_fingerprints(diff)
        assert ack_covers(diff, {"accepted_changes": list(fps)})

    def test_per_change_ack_covers_high_in_strict_mode(self):
        diff = _high_diff()
        fps = collect_required_fingerprints(diff)
        assert ack_covers(diff, {"accepted_changes": list(fps)})


# ── Dev-mode tests ──────────────────────────────────────────────────


class TestDevMode:
    """When dev_mode: true is set, the accept_any_low flag becomes
    operative for low-tier changes. Medium/high still require
    per-change ack."""

    def test_dev_mode_alone_does_not_unlock_anything(self):
        """dev_mode without accept_any_low is inert."""
        assert not ack_covers(_low_diff(), {"dev_mode": True})

    def test_blanket_low_covers_low_in_dev_mode(self):
        assert ack_covers(_low_diff(),
                          {"dev_mode": True, "accept_any_low": True})

    def test_blanket_low_does_not_cover_medium_in_dev_mode(self):
        """Even with both flags set, medium-tier changes require
        per-change ack."""
        assert not ack_covers(_medium_diff(),
                              {"dev_mode": True, "accept_any_low": True})

    def test_blanket_low_does_not_cover_high_in_dev_mode(self):
        """Even with both flags set, high-tier changes require
        per-change ack."""
        assert not ack_covers(_high_diff(),
                              {"dev_mode": True, "accept_any_low": True})

    def test_dev_mode_per_change_works(self):
        """Per-change ack still works in dev_mode; the dev flag is
        purely additive."""
        diff = _high_diff()
        fps = collect_required_fingerprints(diff)
        assert ack_covers(diff,
                          {"dev_mode": True, "accepted_changes": list(fps)})


# ── Coverage of the entire gating matrix from migration-contract §7.2 ─


@pytest.mark.parametrize("dev_mode,blanket,per_change,low_ok,medium_ok,high_ok", [
    # dev_mode | blanket | per_change | low | medium | high
    (False,    False,    False,        False, False,  False),  # nothing
    (False,    True,     False,        False, False,  False),  # blanket inert
    (True,     False,    False,        False, False,  False),  # dev_mode alone
    (True,     True,     False,        True,  False,  False),  # dev + blanket: low only
    (False,    False,    True,         True,  True,   True),   # per-change covers all
    (True,     True,     True,         True,  True,   True),   # everything set
])
def test_gating_matrix(dev_mode, blanket, per_change, low_ok, medium_ok, high_ok):
    """Exhaustive matrix of dev_mode × accept_any_low × per_change_ack
    against low/medium/high tier diffs."""
    cases = [
        (_low_diff(), low_ok, "low"),
        (_medium_diff(), medium_ok, "medium"),
        (_high_diff(), high_ok, "high"),
    ]
    for diff, expected_covered, tier_label in cases:
        config = {"dev_mode": dev_mode, "accept_any_low": blanket}
        if per_change:
            config["accepted_changes"] = list(collect_required_fingerprints(diff))
        actual = ack_covers(diff, config)
        assert actual is expected_covered, (
            f"tier={tier_label} dev_mode={dev_mode} "
            f"blanket={blanket} per_change={per_change}: "
            f"expected covered={expected_covered}, got {actual}"
        )


# ── Edge cases ─────────────────────────────────────────────────────


class TestEdgeCases:
    def test_safe_diff_trivially_covered(self):
        """A diff with only safe changes needs no ack."""
        assert ack_covers(_safe_diff(), {})

    def test_empty_diff_trivially_covered(self):
        """An empty diff needs no ack."""
        assert ack_covers(MigrationDiff(changes=()), {})

    def test_blocked_diff_ignored_by_ack_check(self):
        """ack_covers ignores blocked changes (they're separately
        rejected). A diff with only a blocked change has no
        ack-required entries, so the check returns True."""
        assert ack_covers(_blocked_diff(), {})

    def test_partial_ack_reports_missing(self):
        """When some fingerprints are acked but others aren't, the
        missing list is populated correctly."""
        diff = MigrationDiff(changes=(
            ContentChange(kind="modified", content_name="x",
                          classification="medium",
                          field_changes=(
                              FieldChange(kind="bounds_changed",
                                          field_name="a",
                                          detail={"from": {"min": 0, "max": 10},
                                                  "to": {"min": 0, "max": 100},
                                                  "tightening": False}),
                              FieldChange(kind="bounds_changed",
                                          field_name="b",
                                          detail={"from": {"min": 0, "max": 10},
                                                  "to": {"min": 0, "max": 100},
                                                  "tightening": False}),
                          )),
        ))
        all_fps = collect_required_fingerprints(diff)
        # Only ack the first one.
        partial = list(all_fps)[:1]
        missing = missing_acks(diff, {"accepted_changes": partial})
        assert len(missing) == 1
        assert missing[0] not in partial
