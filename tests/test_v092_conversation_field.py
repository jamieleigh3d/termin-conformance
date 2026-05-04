# Copyright 2026 Jamie-Leigh Blake and Termin project contributors
# Licensed under the Apache License, Version 2.0 (the "License");

"""Conformance — v0.9.2 conversation field surface
(`conversation-field-contract.md`).

Adapter-agnostic tests for:

  - The `conversation` base type lands a JSON-array-shaped field on
    the parent ContentSchema (§2 + §3).
  - The Append CRUD verb's REST shape: kind validation against the
    closed enum, runtime-stamped id/created_at/appended_by_principal_id,
    and HTTP 400 / 404 / 403 surfaces (§4.2).
  - The `<content>.<field>.appended` event channel id is field-scoped
    (§5.1) and trigger predicate has access to `appended_entry`
    (§5.3).
  - The end-to-end refusal-as-assistant-with-type=refusal path: when
    an ai-agent compute with `Conversation is X.Y` calls
    system_refuse, the runtime appends a `kind: "assistant",
    type: "refusal"` entry to the field with parent_id linkage to
    the triggering user entry (§6).
  - The retired `compute_refusals` sidecar Content type is NOT
    auto-generated for v0.9.2 conformance fixtures (§6, §9).
  - Compile-time invariants that the runtime can rely on (§8): no
    conversation-mode compute's IR carries both conversation_source
    and accesses on the same content, and conversation-mode computes
    don't carry output_fields.

These tests exercise the front-door HTTP surface where possible and
the IR shape where the behavior is structural. The agent-loop side
uses the conformance adapter's `deploy_with_agent_mock` (extended in
v0.9.2 to mock `agent_loop_with_conversation` too), so live API keys
are not required.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
_WAIT = 1.5  # seconds for the background agent thread to drain


def _get_adapter():
    adapter_name = os.environ.get("TERMIN_ADAPTER", "reference")
    if adapter_name == "reference":
        from adapter_reference import ReferenceAdapter
        return ReferenceAdapter()
    elif adapter_name == "served-reference":
        from adapter_served_reference import ServedReferenceAdapter
        return ServedReferenceAdapter()
    elif adapter_name == "template":
        from adapter_template import MyRuntimeAdapter
        return MyRuntimeAdapter()
    raise ValueError(f"Unknown adapter: {adapter_name}")


_adapter = _get_adapter()


# ── helpers ──


def _content_by_snake(ir: dict, snake: str) -> dict | None:
    for cs in ir.get("content", []):
        name = cs.get("name", {})
        if isinstance(name, dict) and name.get("snake") == snake:
            return cs
    return None


def _field_by_name(content_schema: dict, name: str) -> dict | None:
    for f in content_schema.get("fields", []):
        if f.get("name") == name:
            return f
    return None


def _entries_from_record(record: dict, field_name: str) -> list:
    """Pull the conversation entry list off a record, parsing JSON if
    the runtime returns the raw column string (SQLite-shape) or the
    materialized list (richer runtimes)."""
    raw = record.get(field_name)
    if raw in (None, ""):
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


# ──────────────────────────────────────────────────────────────────────
# § 2 + § 3 — `conversation` base type lands as a JSON-array field
# ──────────────────────────────────────────────────────────────────────


class TestConversationFieldShape:
    """Per §2: `which is conversation` lowers to a JSON-array-backed
    field on the parent ContentSchema. Per §3: the read endpoint
    returns either a list or a stringified JSON list."""

    def test_field_appears_in_ir(self, agent_chatbot_ir):
        chat_threads = _content_by_snake(agent_chatbot_ir, "chat_threads")
        assert chat_threads is not None, (
            "agent_chatbot fixture must declare a chat_threads content"
        )
        conv_field = _field_by_name(chat_threads, "conversation")
        assert conv_field is not None, (
            "chat_threads must have a `conversation` field"
        )
        # business_type carries the source-level type label; runtimes
        # may map it to JSON or a richer column type for storage.
        # Conformance: the source-level discriminator survives lower.
        assert conv_field.get("business_type") in (
            "conversation", "structured", "json",
        ), conv_field

    def test_read_returns_list_or_json_array(self, agent_chatbot):
        """A freshly-created chat_thread has an empty conversation
        field; the read endpoint surfaces it as either an empty list
        or an empty JSON-encoded list."""
        agent_chatbot.set_role("anonymous")
        create = agent_chatbot.post(
            "/api/v1/chat_threads", json={"title": "shape test"})
        assert create.status_code in (200, 201), create.text
        thread_id = create.json()["id"]

        get = agent_chatbot.get(f"/api/v1/chat_threads/{thread_id}")
        assert get.status_code == 200
        record = get.json()
        # Empty conversation: either omitted, null, "", "[]", or [].
        raw = record.get("conversation")
        entries = _entries_from_record(record, "conversation")
        assert entries == [], (
            f"expected empty conversation list, got {raw!r}"
        )


# ──────────────────────────────────────────────────────────────────────
# § 4 — Append verb: REST shape, kind validation, error surfaces
# ──────────────────────────────────────────────────────────────────────


class TestAppendVerbRestShape:
    """Per §4.2: POST /<resource>/{id}/<field>:append accepts the
    entry payload, returns the persisted entry (with runtime-stamped
    metadata), and rejects malformed shapes with HTTP 400."""

    def test_user_entry_round_trip(self, agent_chatbot):
        agent_chatbot.set_role("anonymous")
        create = agent_chatbot.post(
            "/api/v1/chat_threads", json={"title": "round trip"})
        thread_id = create.json()["id"]

        ap = agent_chatbot.post(
            f"/api/v1/chat_threads/{thread_id}/conversation:append",
            json={"kind": "user", "body": "hello"})
        assert ap.status_code == 201, ap.text
        entry = ap.json()
        # § 3.1 — runtime-stamped fields.
        assert entry["kind"] == "user"
        assert entry["body"] == "hello"
        assert isinstance(entry.get("id"), str) and entry["id"]
        assert isinstance(entry.get("created_at"), str) and "T" in entry["created_at"]
        # appended_by_principal_id is non-null but may be empty/anonymous.
        assert "appended_by_principal_id" in entry

        # Read-back verifies the entry landed in the field.
        get = agent_chatbot.get(f"/api/v1/chat_threads/{thread_id}")
        entries = _entries_from_record(get.json(), "conversation")
        assert len(entries) == 1
        assert entries[0]["id"] == entry["id"]

    def test_invalid_kind_rejected_with_400(self, agent_chatbot):
        """Per §3.2: kind enum is closed. Any other value MUST be
        rejected with a 400-class error."""
        agent_chatbot.set_role("anonymous")
        create = agent_chatbot.post(
            "/api/v1/chat_threads", json={"title": "bad kind"})
        thread_id = create.json()["id"]

        ap = agent_chatbot.post(
            f"/api/v1/chat_threads/{thread_id}/conversation:append",
            json={"kind": "narrator", "body": "..."})
        assert ap.status_code == 400, ap.text

    def test_missing_body_rejected_with_400(self, agent_chatbot):
        """body is required (§3.1)."""
        agent_chatbot.set_role("anonymous")
        create = agent_chatbot.post(
            "/api/v1/chat_threads", json={"title": "no body"})
        thread_id = create.json()["id"]

        ap = agent_chatbot.post(
            f"/api/v1/chat_threads/{thread_id}/conversation:append",
            json={"kind": "user"})
        assert ap.status_code == 400, ap.text

    def test_unknown_record_rejected_with_404(self, agent_chatbot):
        agent_chatbot.set_role("anonymous")
        ap = agent_chatbot.post(
            "/api/v1/chat_threads/no-such-id-xyz/conversation:append",
            json={"kind": "user", "body": "ghost"})
        assert ap.status_code == 404, ap.text

    def test_optional_fields_pass_through(self, agent_chatbot):
        """Per §3.3: optional fields (parent_id, tool_call_id, etc.)
        pass through to the persisted entry without runtime mangling."""
        agent_chatbot.set_role("anonymous")
        create = agent_chatbot.post(
            "/api/v1/chat_threads", json={"title": "optional fields"})
        thread_id = create.json()["id"]

        # First, a parent user entry.
        first = agent_chatbot.post(
            f"/api/v1/chat_threads/{thread_id}/conversation:append",
            json={"kind": "user", "body": "what time?"}).json()
        # Then a tool_call entry that references it.
        ap = agent_chatbot.post(
            f"/api/v1/chat_threads/{thread_id}/conversation:append",
            json={
                "kind": "tool_call",
                "body": "current_time({})",
                "tool_call_id": "toolu_abc",
                "tool_name": "current_time",
                "tool_args": {},
                "parent_id": first["id"],
            })
        assert ap.status_code == 201, ap.text
        entry = ap.json()
        assert entry["tool_call_id"] == "toolu_abc"
        assert entry["tool_name"] == "current_time"
        assert entry["tool_args"] == {}
        assert entry["parent_id"] == first["id"]


# ──────────────────────────────────────────────────────────────────────
# § 5 — `<content>.<field>.appended` event class
# ──────────────────────────────────────────────────────────────────────


class TestAppendedEventTriggerPredicate:
    """Per §5.3: trigger predicates have access to `appended_entry`.
    The agent_chatbot fixture exercises this — its `reply` compute
    triggers on `chat_threads.conversation.appended where
    appended_entry.kind == "user"`. Verify by appending a non-user
    entry and confirming the agent did NOT fire."""

    def test_predicate_filters_non_user_appends(self, tmp_path):
        """If the predicate didn't bind appended_entry properly, the
        agent would fire on every append. Verify it filters out an
        assistant-kind append."""
        info, tool_results = _adapter.deploy_with_agent_mock(
            FIXTURES_DIR / "agent_chatbot.termin.pkg",
            "agent_chatbot",
            tool_calls=[],  # mock writes a single assistant reply via
                            # on_writeback in conversation mode.
        )
        try:
            session = _adapter.create_session(info)
            session.set_role("anonymous")
            create = session.post(
                "/api/v1/chat_threads", json={"title": "predicate"})
            thread_id = create.json()["id"]

            # Append a non-user entry — the predicate should filter
            # this out so the agent does NOT auto-reply.
            ap = session.post(
                f"/api/v1/chat_threads/{thread_id}/conversation:append",
                json={"kind": "system_event", "body": "noise",
                      "source": "TEST"})
            assert ap.status_code == 201
            time.sleep(_WAIT)

            entries = _entries_from_record(
                session.get(
                    f"/api/v1/chat_threads/{thread_id}").json(),
                "conversation")
            kinds = [e["kind"] for e in entries]
            # The system_event landed; nothing else fired.
            assert kinds == ["system_event"], (
                f"agent should not fire on non-user appends; "
                f"saw {kinds!r}"
            )
        finally:
            if info.cleanup:
                info.cleanup()


class TestAppendedEventDispatchesAgent:
    """A user-kind append on a field a conversation-mode agent watches
    triggers the agent (auto-write-back lands an assistant reply)."""

    def test_user_append_auto_writes_assistant_reply(self, tmp_path):
        info, tool_results = _adapter.deploy_with_agent_mock(
            FIXTURES_DIR / "agent_chatbot.termin.pkg",
            "agent_chatbot",
            tool_calls=[],
        )
        try:
            session = _adapter.create_session(info)
            session.set_role("anonymous")
            create = session.post(
                "/api/v1/chat_threads", json={"title": "dispatch"})
            thread_id = create.json()["id"]

            ap = session.post(
                f"/api/v1/chat_threads/{thread_id}/conversation:append",
                json={"kind": "user", "body": "hi"})
            user_entry = ap.json()
            time.sleep(_WAIT)

            entries = _entries_from_record(
                session.get(
                    f"/api/v1/chat_threads/{thread_id}").json(),
                "conversation")
            kinds = [e["kind"] for e in entries]
            assert kinds == ["user", "assistant"], entries
            # § 5.5: parent_id linkage.
            assert entries[1].get("parent_id") == user_entry["id"]
        finally:
            if info.cleanup:
                info.cleanup()


# ──────────────────────────────────────────────────────────────────────
# § 6 — Refusal surfaces
# ──────────────────────────────────────────────────────────────────────


class TestRefusalAppendedToConversation:
    """Per §6: when system_refuse fires inside a conversation-mode
    ai-agent compute, the runtime appends a
    `kind: "assistant", type: "refusal"` entry to the conversation
    field with parent_id pointing at the triggering user entry.
    The compute_refusals sidecar is NOT involved (retired in v0.9.2)."""

    def test_refusal_lands_as_assistant_type_refusal(self, tmp_path):
        info, tool_results = _adapter.deploy_with_agent_mock(
            FIXTURES_DIR / "agent_chatbot.termin.pkg",
            "agent_chatbot",
            tool_calls=[
                ("system_refuse",
                 {"reason": "off-policy fabrication request"}),
            ],
        )
        try:
            session = _adapter.create_session(info)
            session.set_role("anonymous")
            create = session.post(
                "/api/v1/chat_threads", json={"title": "refusal"})
            thread_id = create.json()["id"]

            ap = session.post(
                f"/api/v1/chat_threads/{thread_id}/conversation:append",
                json={"kind": "user",
                      "body": "Make up a real-sounding citation."})
            user_entry = ap.json()
            time.sleep(_WAIT)

            entries = _entries_from_record(
                session.get(
                    f"/api/v1/chat_threads/{thread_id}").json(),
                "conversation")
            kinds = [e["kind"] for e in entries]
            assert kinds == ["user", "assistant"], entries
            assert entries[1].get("type") == "refusal"
            assert entries[1].get("body") == (
                "off-policy fabrication request")
            assert entries[1].get("parent_id") == user_entry["id"]
        finally:
            if info.cleanup:
                info.cleanup()


class TestComputeRefusalsSidecarRetired:
    """Per §6 + §9: the v0.9.1 `compute_refusals` Content type is
    retired in v0.9.2. v0.9.2-shaped fixtures MUST NOT auto-generate
    it."""

    def test_sidecar_not_in_v092_agent_chatbot_ir(self, agent_chatbot_ir):
        cr = _content_by_snake(agent_chatbot_ir, "compute_refusals")
        assert cr is None, (
            "compute_refusals sidecar Content type was retired in "
            "v0.9.2 (per L7.5); v0.9.2-shaped agent_chatbot must not "
            "carry it. Found: " + str(cr)
        )


# ──────────────────────────────────────────────────────────────────────
# § 8 — Compile-time invariants the runtime can rely on
# ──────────────────────────────────────────────────────────────────────


class TestConversationModeIRInvariants:
    """Per §8: structural assertions on the IR shape that means the
    compiler enforced TERMIN-S057, S058, S061. Runtimes can rely on
    these holding in any IR produced by a conforming compiler."""

    def _reply_compute(self, ir: dict) -> dict:
        for c in ir.get("computes", []):
            if c["name"]["snake"] == "reply":
                return c
        pytest.fail("agent_chatbot fixture must declare a `reply` compute")

    def test_conversation_source_set_for_chat_threads(self, agent_chatbot_ir):
        reply = self._reply_compute(agent_chatbot_ir)
        cs = reply.get("conversation_source")
        assert cs is not None, "reply compute must wire Conversation is"
        # Tuple/list of [content_snake, field_snake].
        assert len(cs) == 2
        assert cs[0] in ("chat_threads", "chat_thread")
        assert cs[1] == "conversation"

    def test_no_accesses_on_chat_threads_when_conversation_wired(
            self, agent_chatbot_ir):
        """TERMIN-S057 ensures no overlap between conversation_source
        and accesses; conformance asserts the runtime sees a clean IR."""
        reply = self._reply_compute(agent_chatbot_ir)
        cs = reply.get("conversation_source") or [None]
        accesses = reply.get("accesses") or []
        # Either no accesses, or accesses don't include the parent
        # content of conversation_source.
        if accesses:
            assert cs[0] not in accesses, (
                f"TERMIN-S057 violation in IR: reply compute carries "
                f"conversation_source={cs!r} AND accesses={accesses!r}"
            )

    def test_no_output_fields_on_conversation_mode_compute(
            self, agent_chatbot_ir):
        """TERMIN-S061 ensures conversation-mode computes don't carry
        output_fields. Runtimes can skip the legacy set_output dispatch."""
        reply = self._reply_compute(agent_chatbot_ir)
        if reply.get("conversation_source"):
            output_fields = reply.get("output_fields") or []
            assert output_fields == [], (
                f"TERMIN-S061 violation in IR: conversation-mode reply "
                f"carries output_fields={output_fields!r}"
            )

    def test_trigger_event_aligns_with_conversation_source(
            self, agent_chatbot_ir):
        """TERMIN-S058 ensures the trigger event matches the
        conversation field's .appended event."""
        reply = self._reply_compute(agent_chatbot_ir)
        cs = reply.get("conversation_source")
        assert cs and len(cs) == 2
        trigger = (reply.get("trigger") or "").strip()
        # Accept either the `event "X.Y.appended"` form or a bare
        # `X.Y.appended` form (both are documented in the analyzer).
        expected_suffix = f'{cs[0]}.{cs[1]}.appended'
        assert expected_suffix in trigger, (
            f"trigger {trigger!r} must reference {expected_suffix!r}"
        )
