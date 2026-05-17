"""Termin Conformance — v0.9.4 Phase 3 C3 compute-invoked trigger.

Validates that any conforming runtime correctly implements the new
`When <compute> called [with <cel-filter>]:` event trigger:

  1. After a compute completes successfully, the runtime emits a
     synthetic `<compute>.invoked` event and dispatches every
     When-rule whose `trigger_compute` matches the compute name.
  2. An unfiltered rule (no `with <cel>` clause) fires on every
     invocation, regardless of the input args.
  3. A filtered rule fires only when its CEL filter — evaluated
     against an event context binding `args`, `result`, and the
     source-record singular — returns truthy.
  4. The dispatcher is failure-isolated: a When-rule body may write
     records that touch the same content the compute returned;
     the rule's writes are observable on the next read.

Fixture: `compute_invoked_trigger.termin.pkg`. One content type
(rounds) with two yes/no flags as write witnesses. A Transform
compute (`test_tool`) returns a tiny dict echoing the marker. Two
When-rules: one unfiltered flips `triggered_flag`, one filtered
on `args.marker == "filter_me"` flips `filtered_flag`.

Authors: Jamie-Leigh Blake & Claude Anthropic
"""

import pytest


def _set_role(client, name="alice"):
    """Set the player role with a user-name distinguisher so each test
    sees a session-bearing-anonymous principal unique per name —
    same pattern transition_action / detail_page use."""
    client.set_role("player", name)


def _create_round(client) -> dict:
    """Create a fresh round and return the record dict. Both flags
    start at "no" by content schema default."""
    r = client.post("/api/v1/rounds", json={})
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["triggered_flag"] == "no", rec
    assert rec["filtered_flag"] == "no", rec
    return rec


def _trigger_compute(client, record, marker):
    """Invoke `test_tool` via the manual trigger endpoint with
    `marker` carried on the input record so the When-rule filter's
    `args.marker` reference resolves. Returns the trigger envelope."""
    payload = {
        "record": dict(record, marker=marker),
        "content_name": "rounds",
    }
    r = client.post("/api/v1/compute/test_tool/trigger", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "completed", body
    return body


def _read_round(client, rid):
    r = client.get(f"/api/v1/rounds/{rid}")
    assert r.status_code == 200, r.text
    return r.json()


class TestComputeInvokedUnfilteredRule:
    """The unfiltered `When test_tool called:` rule must fire on
    every successful invocation, regardless of the input marker."""

    def test_unfiltered_rule_fires_with_any_marker(
        self, compute_invoked_trigger,
    ):
        client = compute_invoked_trigger
        _set_role(client, "cinv_a")
        rec = _create_round(client)
        _trigger_compute(client, rec, marker="anything_works")
        post = _read_round(client, rec["id"])
        assert post["triggered_flag"] == "yes", (
            f"Unfiltered When-rule should have flipped triggered_flag "
            f"on any invocation; got: {post!r}"
        )


class TestComputeInvokedFilteredRule:
    """The filtered `When test_tool called with `args.marker ==
    "filter_me"`:` rule must fire only when its CEL filter matches
    against the event context."""

    def test_filtered_rule_fires_when_filter_matches(
        self, compute_invoked_trigger,
    ):
        client = compute_invoked_trigger
        _set_role(client, "cinv_b")
        rec = _create_round(client)
        _trigger_compute(client, rec, marker="filter_me")
        post = _read_round(client, rec["id"])
        # Both rules should have fired — the unfiltered always plus
        # the filtered on a matching marker.
        assert post["triggered_flag"] == "yes", post
        assert post["filtered_flag"] == "yes", (
            f"Filtered When-rule should have flipped filtered_flag "
            f"when args.marker == 'filter_me'; got: {post!r}"
        )

    def test_filtered_rule_skips_when_filter_misses(
        self, compute_invoked_trigger,
    ):
        client = compute_invoked_trigger
        _set_role(client, "cinv_c")
        rec = _create_round(client)
        _trigger_compute(client, rec, marker="some_other_value")
        post = _read_round(client, rec["id"])
        # Unfiltered still fires.
        assert post["triggered_flag"] == "yes", post
        # Filtered should be inert — marker didn't match.
        assert post["filtered_flag"] == "no", (
            f"Filtered When-rule should NOT have fired for a "
            f"non-matching marker; got: {post!r}"
        )
