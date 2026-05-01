# Copyright 2026 Jamie-Leigh Blake and Termin project contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0

"""Conformance — v0.9.1 Phase 4 inbound channel auto-routing.

Companion to `specs/channel-contract.md` §6.

A channel with `direction: inbound` (or `bidirectional`) and a
non-empty `carries_content` MUST register an auto-route at
`POST /webhooks/<channel.snake>` that:

  1. Authorizes against the channel's send-direction scope clause.
  2. Parses JSON; rejects bad JSON / non-object body.
  3. Projects to the carried content's known columns; rejects empty
     projection as 422.
  4. Persists via `storage.create(carries_content, projected_data)`.
  5. Fires `<content>.created` event handlers.
  6. Broadcasts the new record to subscribers.
  7. Returns 200 `{"ok": True, "id": <id>, "channel": <display>}`.

These tests run against the conformance adapter — they exercise the
deployed app via HTTP, not the dispatcher in isolation. The
`channel_simple.termin.pkg` fixture has both an outbound webhook
("note-sync") and an inbound channel ("echo-receiver") carrying
"echoes" content with title + body fields.
"""

from __future__ import annotations

import pytest


# ── §6.1: route registration ──────────────────────────────────────


class TestInboundRouteRegistered:
    """Per channel-contract.md §6.1 — POST /webhooks/<channel-snake>
    is auto-registered for inbound channels carrying content. The
    `channel_simple` fixture has `echo-receiver` (display) →
    `echo_receiver` (snake) carrying `echoes`."""

    def test_post_to_webhook_route_returns_200(self, channel_simple):
        response = channel_simple.post(
            "/webhooks/echo_receiver",
            json={"title": "hello", "body": "world"},
        )
        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}: {response.text}"

    def test_response_body_carries_ok_and_channel(self, channel_simple):
        response = channel_simple.post(
            "/webhooks/echo_receiver",
            json={"title": "shape-check", "body": "x"},
        )
        body = response.json()
        assert body["ok"] is True
        # Channel display name appears in the response body — operators
        # tracing the request can confirm which logical channel got the
        # record.
        assert body["channel"] == "echo-receiver"

    def test_response_includes_record_id(self, channel_simple):
        response = channel_simple.post(
            "/webhooks/echo_receiver",
            json={"title": "id-check", "body": "x"},
        )
        assert "id" in response.json()


# ── §6.2: payload persists as a record ────────────────────────────


class TestInboundPersists:
    """Per §6.2 step 4 — the projected payload becomes a record of
    the carried content type, observable via the standard list
    endpoint."""

    def test_record_appears_in_list_after_post(self, channel_simple):
        # Capture the pre-state count.
        pre = channel_simple.get("/api/v1/echoes")
        assert pre.status_code == 200
        pre_count = len(pre.json())

        post = channel_simple.post(
            "/webhooks/echo_receiver",
            json={"title": "persistence-check", "body": "verify"},
        )
        assert post.status_code == 200

        post_state = channel_simple.get("/api/v1/echoes")
        assert post_state.status_code == 200
        rows = post_state.json()
        assert len(rows) == pre_count + 1
        # The most recent row carries the posted payload.
        titles = [r.get("title") for r in rows]
        assert "persistence-check" in titles


# ── §6.2: JSON validation ────────────────────────────────────────


class TestInboundJsonValidation:
    """Per §6.2 step 2 — non-object or non-JSON bodies are rejected."""

    def test_non_json_body_rejected(self, channel_simple):
        response = channel_simple.post(
            "/webhooks/echo_receiver",
            data="not-json-at-all",
            headers={"Content-Type": "text/plain"},
        )
        assert response.status_code in (400, 422), \
            f"Expected 400/422 for non-JSON body, got {response.status_code}"

    def test_array_body_rejected(self, channel_simple):
        """A JSON array is not an object — webhooks expect a single
        record envelope."""
        response = channel_simple.post(
            "/webhooks/echo_receiver",
            json=[{"title": "x"}],
        )
        assert response.status_code in (400, 422), \
            f"Expected 400/422 for array body, got {response.status_code}"


# ── §6.2: column projection ──────────────────────────────────────


class TestInboundColumnProjection:
    """Per §6.2 step 3 — extra fields silently dropped; empty
    projection rejected as 422."""

    def test_extra_fields_silently_ignored(self, channel_simple):
        """Fields not in the carried content's schema are dropped.
        The known fields still persist."""
        response = channel_simple.post(
            "/webhooks/echo_receiver",
            json={
                "title": "projection-test",
                "body": "ok",
                "this_field_does_not_exist": "should-be-ignored",
                "neither_does_this": 42,
            },
        )
        assert response.status_code == 200, \
            f"Extra fields must not break the request: {response.text}"

    def test_empty_projection_rejected(self, channel_simple):
        """A body with NO recognized fields → 422; storing an empty
        record is a silent no-op the contract refuses."""
        response = channel_simple.post(
            "/webhooks/echo_receiver",
            json={"only_unknown_fields": "x", "and_another": 1},
        )
        assert response.status_code == 422, \
            f"Expected 422 for empty projection, got {response.status_code}"


# ── §6.3: NOT idempotent in v0.9 ─────────────────────────────────


class TestInboundNonIdempotent:
    """Per channel-contract.md §6.3 — the auto-route is NOT
    idempotent in v0.9. Two POSTs with the same body create two
    distinct records. Idempotency is a v0.10+ candidate; the
    conformance pack locks in the current contract until then."""

    def test_two_posts_create_two_records(self, channel_simple):
        # Reset to a known starting count.
        pre = channel_simple.get("/api/v1/echoes")
        pre_count = len(pre.json())

        body = {"title": "duplicate-payload", "body": "same body"}
        r1 = channel_simple.post("/webhooks/echo_receiver", json=body)
        r2 = channel_simple.post("/webhooks/echo_receiver", json=body)
        assert r1.status_code == 200
        assert r2.status_code == 200

        post = channel_simple.get("/api/v1/echoes")
        assert len(post.json()) == pre_count + 2
        # Two distinct ids.
        assert r1.json()["id"] != r2.json()["id"]


# ── §6.5: empty carries_content does not register a route ─────────


class TestInboundNoCarriesContent:
    """Per channel-contract.md §6.5 — a channel with empty
    `carries_content` MUST NOT have an auto-route. The fixtures all
    declare `Carries <X>`, so this is verified indirectly: a
    nonexistent channel name (which would map to no route at all)
    returns 404, demonstrating the runtime does not register
    catch-all webhook routes."""

    def test_unknown_webhook_path_returns_404(self, channel_simple):
        response = channel_simple.post(
            "/webhooks/no_such_channel",
            json={"title": "x"},
        )
        assert response.status_code == 404
