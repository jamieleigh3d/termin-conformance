"""Agent Tool API Conformance Tests — the "back door".

Tests the behavioral contract of the agent tool API: content_query,
content_create, content_update, state_transition. These tools are the
interface between AI agents and the runtime — any conforming runtime
that supports Level 3 agents must implement them correctly.

The test flow:
1. Deploy an app with a mock AI provider (predetermined tool calls)
2. Create a record via HTTP (front door) to trigger the agent Compute
3. Wait for the background agent to execute the mock tool calls
4. Verify tool results and side effects via HTTP (front door)

This exercises: transaction staging, Before/After snapshots, postcondition
evaluation, tool access control (Accesses), boundary enforcement from
tools, and event propagation from tool-created records.
"""

import json
import time
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _get_adapter():
    """Get the runtime adapter."""
    import os
    adapter_name = os.environ.get("TERMIN_ADAPTER", "reference")
    if adapter_name == "reference":
        from adapter_reference import ReferenceAdapter
        return ReferenceAdapter()
    raise ValueError(f"Unknown adapter: {adapter_name}")


_adapter = _get_adapter()
_WAIT = 1.5  # seconds to wait for background agent thread


# ── Fixtures ──

@pytest.fixture(scope="module")
def agent_query_app():
    """App where agent calls content_query on trigger."""
    pkg = FIXTURES_DIR / "agent_chatbot.termin.pkg"
    if not pkg.exists():
        pytest.skip("agent_chatbot fixture not found")
    info, results = _adapter.deploy_with_agent_mock(
        pkg, "agent_chatbot",
        [("content_query", {"content_name": "messages"})]
    )
    session = _adapter.create_session(info)
    yield session, info, results
    if info.cleanup:
        info.cleanup()


@pytest.fixture(scope="module")
def agent_create_app():
    """App where agent calls content_create on trigger."""
    pkg = FIXTURES_DIR / "agent_chatbot.termin.pkg"
    if not pkg.exists():
        pytest.skip("agent_chatbot fixture not found")
    info, results = _adapter.deploy_with_agent_mock(
        pkg, "agent_chatbot_create",
        [("content_create", {"content_name": "messages",
                              "data": {"role": "assistant", "body":"Agent created this"}})]
    )
    session = _adapter.create_session(info)
    yield session, info, results
    if info.cleanup:
        info.cleanup()


@pytest.fixture(scope="module")
def agent_multi_tool_app():
    """App where agent calls multiple tools in sequence."""
    pkg = FIXTURES_DIR / "agent_chatbot.termin.pkg"
    if not pkg.exists():
        pytest.skip("agent_chatbot fixture not found")
    info, results = _adapter.deploy_with_agent_mock(
        pkg, "agent_chatbot_multi",
        [
            ("content_query", {"content_name": "messages"}),
            ("content_create", {"content_name": "messages",
                                 "data": {"role": "assistant", "body":"First reply"}}),
            ("content_create", {"content_name": "messages",
                                 "data": {"role": "assistant", "body":"Second reply"}}),
        ]
    )
    session = _adapter.create_session(info)
    yield session, info, results
    if info.cleanup:
        info.cleanup()


@pytest.fixture(scope="module")
def agent_denied_app():
    """App where agent tries to access content not in its Accesses."""
    pkg = FIXTURES_DIR / "agent_chatbot.termin.pkg"
    if not pkg.exists():
        pytest.skip("agent_chatbot fixture not found")
    # Try to query a content type that doesn't exist or isn't in Accesses
    info, results = _adapter.deploy_with_agent_mock(
        pkg, "agent_chatbot_denied",
        [("content_query", {"content_name": "nonexistent_content"})]
    )
    session = _adapter.create_session(info)
    yield session, info, results
    if info.cleanup:
        info.cleanup()


# ── content_query tool ──

class TestAgentContentQuery:
    """Agent tool: content_query returns records from the database."""

    def test_query_returns_list(self, agent_query_app):
        """content_query should return a list of records."""
        session, info, results = agent_query_app
        session.set_role("anonymous")
        # Trigger the agent by creating a message
        r = session.post("/api/v1/messages",
                         json={"role": "user", "body":"trigger query"})
        assert r.status_code == 201
        time.sleep(_WAIT)

        # The mock agent called content_query — check results
        assert len(results) >= 1
        query_result = results[0]
        assert query_result["tool"] == "content_query"
        assert isinstance(query_result["result"], list)

    def test_query_includes_triggering_record(self, agent_query_app):
        """content_query after create should include the new record."""
        _, _, results = agent_query_app
        if results:
            records = results[0]["result"]
            assert any("trigger" in str(r) for r in records)


# ── content_create tool ──

class TestAgentContentCreate:
    """Agent tool: content_create inserts records into the database."""

    def test_create_inserts_record(self, agent_create_app):
        """content_create should insert a new record."""
        session, info, results = agent_create_app
        session.set_role("anonymous")
        r = session.post("/api/v1/messages",
                         json={"role": "user", "body":"trigger create"})
        assert r.status_code == 201
        time.sleep(_WAIT)

        assert len(results) >= 1
        create_result = results[0]
        assert create_result["tool"] == "content_create"
        assert isinstance(create_result["result"], dict)
        assert "id" in create_result["result"]

    def test_created_record_visible_via_api(self, agent_create_app):
        """Record created by agent should be visible through the front door."""
        session, _, results = agent_create_app
        session.set_role("anonymous")
        # List messages — should include agent-created one
        r = session.get("/api/v1/messages")
        assert r.status_code == 200
        messages = r.json()
        agent_msgs = [m for m in messages if m.get("body") == "Agent created this"]
        assert len(agent_msgs) >= 1, f"Agent-created message not found in {len(messages)} messages"


# ── Multi-tool sequence ──

class TestAgentMultiToolSequence:
    """Agent executes multiple tool calls in sequence (transaction behavior)."""

    def test_multiple_tools_all_execute(self, agent_multi_tool_app):
        """All tool calls in the sequence should execute."""
        session, info, results = agent_multi_tool_app
        session.set_role("anonymous")
        r = session.post("/api/v1/messages",
                         json={"role": "user", "body":"trigger multi"})
        assert r.status_code == 201
        time.sleep(_WAIT)

        assert len(results) >= 3, f"Expected 3 tool calls, got {len(results)}"
        assert results[0]["tool"] == "content_query"
        assert results[1]["tool"] == "content_create"
        assert results[2]["tool"] == "content_create"

    def test_all_created_records_visible(self, agent_multi_tool_app):
        """All records from multi-tool sequence should be in the database."""
        session, _, results = agent_multi_tool_app
        session.set_role("anonymous")
        r = session.get("/api/v1/messages")
        assert r.status_code == 200
        messages = r.json()
        replies = [m for m in messages if m.get("role") == "assistant"]
        assert len(replies) >= 2, f"Expected 2 assistant replies, found {len(replies)}"

    def test_tool_results_contain_ids(self, agent_multi_tool_app):
        """Each content_create result should have an id."""
        _, _, results = agent_multi_tool_app
        create_results = [r for r in results if r["tool"] == "content_create"]
        for cr in create_results:
            assert "id" in cr["result"], f"content_create result missing id: {cr['result']}"


# ── Access control ──

class TestAgentAccessControl:
    """Agent tools respect Accesses declarations."""

    def test_query_denied_for_unlisted_content(self, agent_denied_app):
        """content_query for content not in Accesses should return error."""
        session, info, results = agent_denied_app
        session.set_role("anonymous")
        r = session.post("/api/v1/messages",
                         json={"role": "user", "body":"trigger denied"})
        assert r.status_code == 201
        time.sleep(_WAIT)

        assert len(results) >= 1
        denied_result = results[0]
        assert "error" in denied_result["result"], (
            f"Expected access denied error, got: {denied_result['result']}"
        )
        assert "denied" in str(denied_result["result"]["error"]).lower() or \
               "not in accesses" in str(denied_result["result"]["error"]).lower()


# ── Tool contract shape validation ──

class TestAgentToolResultShapes:
    """Verify the shape of tool call results matches the contract."""

    def test_content_query_returns_list_of_dicts(self, agent_query_app):
        """content_query result is a list of record dicts."""
        _, _, results = agent_query_app
        if results:
            qr = results[0]["result"]
            assert isinstance(qr, list)
            if qr:
                assert isinstance(qr[0], dict)
                assert "id" in qr[0]

    def test_content_create_returns_record_with_id(self, agent_create_app):
        """content_create result is a dict with at least 'id'."""
        _, _, results = agent_create_app
        if results:
            cr = results[0]["result"]
            assert isinstance(cr, dict)
            assert "id" in cr

    def test_access_denied_returns_error_dict(self, agent_denied_app):
        """Access denied result is a dict with 'error' key."""
        _, _, results = agent_denied_app
        if results:
            dr = results[0]["result"]
            assert isinstance(dr, dict)
            assert "error" in dr
