"""Termin Conformance — v0.9.4 Phase 3 C1 Transition action verb.

Validates that any conforming runtime correctly implements the new
`Transition <content> [<field>] to <state>` action verb usable in
any When-rule body:

  1. The action dispatches through the runtime's state-machine
     transition path — the same path the HTTP /_transition/...
     route uses.
  2. Cascading transitions across state machines on the same
     content compose cleanly (state-entered on machine A fires a
     Transition on machine B; the second transition publishes its
     own entered event which can trigger further rules).
  3. The When-rule does NOT fire on irrelevant state changes
     (only the specific (content, field, state) tuple subscribed
     by the rule triggers the action).

Fixture: `transition_action.termin.pkg`. One content type (rounds)
with two state machines (status + archive_status). A state-entered
When-rule on status.done.entered fires a Transition action that
moves archive_status from live to archived.

Authors: Jamie-Leigh Blake & Claude Anthropic
"""

import pytest


def _set_role(client, name="alice"):
    """Set the player role with a user-name distinguisher so each test
    sees a session-bearing-anonymous principal that's unique per name."""
    client.set_role("player", name)


class TestTransitionActionRuntime:
    def test_transition_action_fires_on_state_entered_trigger(
        self, transition_action,
    ):
        """When status enters done, the When-rule's Transition action
        moves archive_status from live to archived."""
        client = transition_action
        _set_role(client, "trans_a")
        r = client.post("/api/v1/rounds", json={"points": 5})
        assert r.status_code == 201, r.text
        rid = r.json()["id"]
        # Initial state: status=in_progress, archive_status=live.
        assert r.json()["status"] == "in_progress"
        assert r.json()["archive_status"] == "live"

        # Trigger the cascade.
        r = client.post(f"/_transition/rounds/status/{rid}/done")
        assert r.status_code == 200, r.text

        # Verify both writes happened.
        r = client.get(f"/api/v1/rounds/{rid}")
        assert r.status_code == 200
        record = r.json()
        assert record["status"] == "done"
        assert record["archive_status"] == "archived", (
            f"Expected archive_status='archived' after cascading "
            f"transition; got {record!r}"
        )

    def test_transition_does_not_fire_on_unrelated_state_changes(
        self, transition_action,
    ):
        """Creating a round (no transition) must not fire the
        When-rule. archive_status stays 'live'."""
        client = transition_action
        _set_role(client, "trans_b")
        r = client.post("/api/v1/rounds", json={"points": 9})
        assert r.status_code == 201
        rid = r.json()["id"]
        # No transition fired; verify no spurious cascade.
        r = client.get(f"/api/v1/rounds/{rid}")
        assert r.status_code == 200
        assert r.json()["archive_status"] == "live"

    def test_each_round_gets_independent_cascade(
        self, transition_action,
    ):
        """Per-record cascade: transitioning round A must not affect
        round B's archive_status. The When-rule binds to the
        triggering record."""
        client = transition_action
        _set_role(client, "trans_c")
        r1 = client.post("/api/v1/rounds", json={"points": 1})
        r2 = client.post("/api/v1/rounds", json={"points": 2})
        id1, id2 = r1.json()["id"], r2.json()["id"]
        # Transition only round 1.
        client.post(f"/_transition/rounds/status/{id1}/done")
        # Round 1: archive_status archived. Round 2: still live.
        rec1 = client.get(f"/api/v1/rounds/{id1}").json()
        rec2 = client.get(f"/api/v1/rounds/{id2}").json()
        assert rec1["archive_status"] == "archived"
        assert rec2["archive_status"] == "live"
