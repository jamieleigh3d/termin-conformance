"""Termin Conformance — v0.9.4 cross-content updates.

Validates that any conforming runtime correctly implements:

  1. The state-machine entered-event When-rule trigger
     (`When <singular> <field> enters <state>:`).
  2. The owner-keyed Update action
     (`Update the user's <singular>: <field> = `<cel>``)
     with single-target lookup, upsert-on-miss semantics, and
     owner-scoping correctness.

Fixture: `owner_keyed_update.termin.pkg`. Two contents (rounds,
profiles) related by player_principal ownership. A state-entered
When-rule on `rounds.status.done.entered` projects per-round data
into the singleton owner-keyed profile.

Authors: Jamie-Leigh Blake & Claude Anthropic
"""

import pytest


def _set_role(client, name="alice"):
    """Set the player role with a user-name distinguisher so each test
    sees a session-bearing-anonymous principal that's unique per
    name. The TerminSession.set_role signature accepts user_name
    as the second positional arg."""
    client.set_role("player", name)


class TestStateEnteredTrigger:
    """The new trigger fires once per state-machine transition into
    the named state."""

    def test_trigger_fires_on_transition(self, owner_keyed_update):
        client = owner_keyed_update
        _set_role(client, "trig_a")
        # Profile shouldn't exist yet.
        r = client.get("/api/v1/profiles")
        assert r.status_code == 200
        assert r.json() == [], f"Expected no profile pre-trigger, got {r.json()}"

        # Create + transition a round.
        r = client.post("/api/v1/rounds", json={"points": 5})
        assert r.status_code == 201, r.text
        rid = r.json()["id"]
        r = client.post(f"/_transition/rounds/status/{rid}/done")
        assert r.status_code == 200, r.text

        # The When-rule should have upserted alice's profile.
        r = client.get("/api/v1/profiles")
        assert r.status_code == 200
        profiles = r.json()
        assert len(profiles) == 1, (
            f"Expected one profile after first transition, got "
            f"{len(profiles)}: {profiles}"
        )
        assert profiles[0]["games_played"] == 1
        assert profiles[0]["best_score"] == 5

    def test_trigger_does_not_fire_on_create_only(self, owner_keyed_update):
        """Creating a round (state stays in_progress) must not fire
        the When-rule. The trigger is bound to ENTERING the `done`
        state, not to round creation."""
        client = owner_keyed_update
        _set_role(client, "trig_b")
        r = client.post("/api/v1/rounds", json={"points": 99})
        assert r.status_code == 201
        # Profile should still be empty for this player.
        r = client.get("/api/v1/profiles")
        assert r.json() == [], f"Spurious profile on create-only: {r.json()}"


class TestOwnerKeyedUpdateUpsert:
    """The owner-keyed Update upserts on first match, updates on
    subsequent matches."""

    def test_first_play_upserts_with_defaults_then_patch(
        self, owner_keyed_update,
    ):
        client = owner_keyed_update
        _set_role(client, "upsert_a")
        r = client.post("/api/v1/rounds", json={"points": 7})
        rid = r.json()["id"]
        client.post(f"/_transition/rounds/status/{rid}/done")

        r = client.get("/api/v1/profiles")
        profiles = r.json()
        assert len(profiles) == 1
        # games_played = profile.games_played + 1; default 0 + 1 = 1.
        assert profiles[0]["games_played"] == 1
        # best_score = max(0 default, round.points 7) = 7.
        assert profiles[0]["best_score"] == 7

    def test_second_play_increments_existing(self, owner_keyed_update):
        client = owner_keyed_update
        _set_role(client, "upsert_b")
        # First play.
        r = client.post("/api/v1/rounds", json={"points": 3})
        rid = r.json()["id"]
        client.post(f"/_transition/rounds/status/{rid}/done")
        # Second play with higher points.
        r = client.post("/api/v1/rounds", json={"points": 8})
        rid = r.json()["id"]
        client.post(f"/_transition/rounds/status/{rid}/done")

        r = client.get("/api/v1/profiles")
        profiles = r.json()
        assert len(profiles) == 1, (
            "Owner-keyed Update must update the existing profile, "
            f"not create a duplicate. Got: {profiles}"
        )
        assert profiles[0]["games_played"] == 2
        assert profiles[0]["best_score"] == 8

    def test_lower_score_does_not_decrease_best(self, owner_keyed_update):
        """max() correctness — a worse subsequent score must not
        replace the best."""
        client = owner_keyed_update
        _set_role(client, "upsert_c")
        # First: high score.
        r = client.post("/api/v1/rounds", json={"points": 50})
        rid = r.json()["id"]
        client.post(f"/_transition/rounds/status/{rid}/done")
        # Second: low score.
        r = client.post("/api/v1/rounds", json={"points": 5})
        rid = r.json()["id"]
        client.post(f"/_transition/rounds/status/{rid}/done")

        r = client.get("/api/v1/profiles")
        profiles = r.json()
        assert profiles[0]["best_score"] == 50, (
            "max() must keep the higher value across plays"
        )
        assert profiles[0]["games_played"] == 2


class TestOwnerScoping:
    """The owner-keyed lookup is owner-scoped — players' profiles
    don't cross."""

    def test_two_players_have_independent_profiles(
        self, owner_keyed_update,
    ):
        client = owner_keyed_update
        # Alice plays.
        _set_role(client, "scope_alice")
        r = client.post("/api/v1/rounds", json={"points": 10})
        rid = r.json()["id"]
        client.post(f"/_transition/rounds/status/{rid}/done")

        # Bob plays.
        _set_role(client, "scope_bob")
        r = client.post("/api/v1/rounds", json={"points": 20})
        rid = r.json()["id"]
        client.post(f"/_transition/rounds/status/{rid}/done")

        # Bob sees only his own profile (their-own ownership filter).
        r = client.get("/api/v1/profiles")
        bob_profiles = r.json()
        assert len(bob_profiles) == 1
        assert bob_profiles[0]["best_score"] == 20

        # Switch back to alice.
        _set_role(client, "scope_alice")
        r = client.get("/api/v1/profiles")
        alice_profiles = r.json()
        assert len(alice_profiles) == 1
        assert alice_profiles[0]["best_score"] == 10

    def test_round_row_visibility_unaffected(self, owner_keyed_update):
        """Sanity: rounds are also owned-per-player. Each player
        sees only their own rounds (the owner-keyed projection
        doesn't disturb the existing ownership filtering)."""
        client = owner_keyed_update
        _set_role(client, "rounds_alice")
        r = client.post("/api/v1/rounds", json={"points": 1})
        rid_alice = r.json()["id"]

        _set_role(client, "rounds_bob")
        r = client.post("/api/v1/rounds", json={"points": 2})
        rid_bob = r.json()["id"]

        # Bob sees only his round.
        r = client.get("/api/v1/rounds")
        ids = [r["id"] for r in r.json()]
        assert rid_bob in ids
        assert rid_alice not in ids
