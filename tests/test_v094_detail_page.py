"""Termin Conformance — v0.9.4 Phase 2 detail-page primitive.

Validates that any conforming runtime correctly implements:

  1. `Show a detail page for <plural> called "<name>"` lowers to
     a page registered at `/<page-slug>/{id}` (not `/<page-slug>`).
  2. The runtime fetches the bound record server-side before
     rendering — so missing ids return 404 (rather than a hydrated
     shell that fails its own client-side fetch).
  3. Ownership-scoped fetch: when the bound content declares `is
     owned by <field>`, a request for a record owned by another
     principal returns 404 (NOT 403 — ownership doesn't leak
     existence; same surface as the auto-CRUD GET handler and the
     append-to-field handler).
  4. Regular non-detail pages on the same app still serve at
     `/<page-slug>` — the dispatcher distinguishes by the IR's
     `record_binding` field on each PageEntry.

Fixture: `detail_page.termin.pkg`. One content type (notes) with
ownership; one list page (`/notes`) and one detail page
(`/note_detail/{id}`).

Authors: Jamie-Leigh Blake & Claude Anthropic
"""

import pytest


def _set_role(client, name="alice"):
    """Set the player role with a user-name distinguisher so each test
    sees a session-bearing-anonymous principal that's unique per name.
    Matches the helper in test_v094_owner_keyed_update.py."""
    client.set_role("player", name)


class TestDetailPageRoute:
    def test_detail_route_serves_existing_record(self, detail_page):
        """Creating a note then requesting `/note_detail/{id}` for it
        returns 200. Proves the route is registered at the right path
        shape and the server-side fetch succeeds for a valid id."""
        client = detail_page
        _set_role(client, "alice")
        # Create a note via the auto-CRUD endpoint.
        r = client.post(
            "/api/v1/notes",
            json={"title": "Hello", "body": "World"},
        )
        assert r.status_code == 201, r.text
        note_id = r.json()["id"]
        # Detail page route serves the record.
        r = client.get(f"/note_detail/{note_id}")
        assert r.status_code == 200, r.text

    def test_detail_route_returns_404_for_missing_id(self, detail_page):
        """Missing id must 404 server-side (not render a shell that
        hydrates and then fails its own client-side fetch)."""
        client = detail_page
        _set_role(client, "alice")
        r = client.get("/note_detail/nonexistent-id-here")
        assert r.status_code == 404, (
            f"Expected 404 for missing id; got {r.status_code}: {r.text}"
        )

    def test_detail_route_returns_404_for_other_principals_record(
        self, detail_page,
    ):
        """Ownership-filtered fetch: a record owned by another principal
        surfaces as 404, NOT 403. Ownership must not leak existence.
        Matches the auto-CRUD GET handler and append-route behavior."""
        client = detail_page
        # Create as alice.
        _set_role(client, "alice_owner")
        r = client.post(
            "/api/v1/notes",
            json={"title": "alices-secret", "body": "private content"},
        )
        assert r.status_code == 201
        alice_note_id = r.json()["id"]
        # Switch to bob — same role, different user-name.
        _set_role(client, "bob_other")
        # bob's GET for alice's note must 404 (not 403).
        r = client.get(f"/note_detail/{alice_note_id}")
        assert r.status_code == 404, (
            f"Ownership-scoped fetch must 404 on other-principal "
            f"record (not leak existence); got {r.status_code}: {r.text}"
        )

    def test_regular_list_page_still_routes_at_bare_slug(self, detail_page):
        """The same app has a regular list page (/notes) AND a detail
        page (/note_detail/{id}). The dispatcher must serve both
        correctly — adding detail-page support must not break the
        regular page routing."""
        client = detail_page
        _set_role(client, "alice")
        # The list page is bare /<slug> with no id segment.
        r = client.get("/notes")
        assert r.status_code == 200, r.text
