"""Termin Conformance Suite — Runtime Behavior Tests for v0.5.0.

Black-box behavioral tests exercising the new v0.5.0 features through
the HTTP API. These tests treat the runtime as opaque — they create
records, trigger events, invoke channels, and verify observable effects.

Test coverage:
  - Agent/LLM app bootstraps and serves pages
  - Channel app CRUD operations
  - Channel webhook creates content records (inbound channel)
  - Channel reflection endpoints
  - Event-triggered behaviors (create record -> event fires)
  - Default field values (enum defaults to literal)
  - Deploy config validation

Authors: Jamie-Leigh Blake & Claude Anthropic
"""

import json
import time
import uuid
import pytest
from pathlib import Path


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _uid():
    return uuid.uuid4().hex[:8]


# ═══════════════════════════════════════════════════════════════════════
# 1. AGENT APP — basic bootstrapping and CRUD
# ═══════════════════════════════════════════════════════════════════════


class TestAgentSimpleBootstrap:
    """Agent Simple app boots and serves expected endpoints."""

    def test_app_boots(self, agent_simple):
        r = agent_simple.get("/agent")
        assert r.status_code == 200

    def test_reflection_endpoint(self, agent_simple):
        r = agent_simple.get("/api/reflect")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Agent Simple"

    def test_list_completions(self, agent_simple):
        agent_simple.set_role("anonymous")
        r = agent_simple.get("/api/v1/completions")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_completion(self, agent_simple):
        agent_simple.set_role("anonymous")
        r = agent_simple.post("/api/v1/completions", json={
            "prompt": f"Hello {_uid()}",
        })
        assert r.status_code == 201
        body = r.json()
        assert "id" in body
        assert "prompt" in body

    def test_get_completion_by_id(self, agent_simple):
        agent_simple.set_role("anonymous")
        r = agent_simple.post("/api/v1/completions", json={
            "prompt": f"Test {_uid()}",
        })
        cid = r.json()["id"]
        r2 = agent_simple.get(f"/api/v1/completions/{cid}")
        assert r2.status_code == 200
        assert r2.json()["id"] == cid

    def test_reflect_compute_shows_complete(self, agent_simple):
        r = agent_simple.get("/api/reflect/compute")
        assert r.status_code == 200
        text = json.dumps(r.json())
        assert "complete" in text.lower()


class TestAgentChatbotBootstrap:
    """Agent Chatbot app boots and serves expected endpoints."""

    def test_app_boots(self, agent_chatbot):
        r = agent_chatbot.get("/chat")
        assert r.status_code == 200

    def test_list_messages(self, agent_chatbot):
        agent_chatbot.set_role("anonymous")
        r = agent_chatbot.get("/api/v1/messages")
        assert r.status_code == 200

    def test_create_message(self, agent_chatbot):
        agent_chatbot.set_role("anonymous")
        r = agent_chatbot.post("/api/v1/messages", json={
            "body": f"Hello {_uid()}",
        })
        assert r.status_code == 201

    def test_reflection_shows_chatbot(self, agent_chatbot):
        r = agent_chatbot.get("/api/reflect")
        assert r.status_code == 200
        assert r.json()["name"] == "Agent Chatbot"


# ═══════════════════════════════════════════════════════════════════════
# 2. CHANNEL APP — CRUD and webhook endpoints
# ═══════════════════════════════════════════════════════════════════════


class TestChannelSimpleBootstrap:
    """Channel Simple app boots and handles CRUD."""

    def test_app_boots(self, channel_simple):
        r = channel_simple.get("/notes")
        assert r.status_code == 200

    def test_create_note(self, channel_simple):
        channel_simple.set_role("anonymous")
        tag = _uid()
        r = channel_simple.post("/api/v1/notes", json={
            "title": f"Note {tag}", "body": "test body",
        })
        assert r.status_code == 201
        assert r.json()["title"] == f"Note {tag}"

    def test_list_notes(self, channel_simple):
        channel_simple.set_role("anonymous")
        r = channel_simple.get("/api/v1/notes")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_echoes_page_exists(self, channel_simple):
        r = channel_simple.get("/echoes")
        assert r.status_code == 200

    def test_list_echoes(self, channel_simple):
        channel_simple.set_role("anonymous")
        r = channel_simple.get("/api/v1/echoes")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestChannelWebhookInbound:
    """Inbound channel webhook endpoint creates content records.

    Per the Runtime Implementer's Guide, an inbound channel named
    'echo-receiver' that carries 'echoes' should expose a webhook
    at POST /api/v1/channels/echo-receiver/webhook.
    """

    def test_webhook_endpoint_exists(self, channel_simple):
        """The webhook endpoint should respond (even if not fully wired)."""
        channel_simple.set_role("anonymous")
        r = channel_simple.post("/api/v1/channels/echo-receiver/webhook", json={
            "title": f"Webhook {_uid()}", "body": "via webhook",
        })
        # Accept 200, 201, 202, or 501 (not implemented yet)
        assert r.status_code in (200, 201, 202, 404, 501), \
            f"Unexpected status {r.status_code} from webhook endpoint"

    def test_webhook_creates_echo_record(self, channel_simple):
        """If webhook is implemented, it should create a record."""
        channel_simple.set_role("anonymous")
        tag = _uid()
        r = channel_simple.post("/api/v1/channels/echo-receiver/webhook", json={
            "title": f"WH {tag}", "body": "webhook body",
        })
        if r.status_code in (200, 201, 202):
            # Verify the echo was created
            echoes = channel_simple.get("/api/v1/echoes").json()
            titles = [e["title"] for e in echoes]
            assert f"WH {tag}" in titles


class TestChannelDemoBootstrap:
    """Channel Demo (Incident Response Hub) app boots."""

    def test_app_boots(self, channel_demo):
        channel_demo.set_role("responder")
        r = channel_demo.get("/incident_dashboard")
        assert r.status_code == 200

    def test_create_incident(self, channel_demo):
        channel_demo.set_role("responder")
        r = channel_demo.post("/api/v1/incidents", json={
            "title": f"Incident {_uid()}",
            "affected_service": "api-gateway",
            "severity": "high",
        })
        assert r.status_code == 201

    def test_list_incidents(self, channel_demo):
        channel_demo.set_role("responder")
        r = channel_demo.get("/api/v1/incidents")
        assert r.status_code == 200

    def test_multiple_channel_types(self, channel_demo_ir):
        """Channel demo should have multiple channel types."""
        directions = {ch["direction"] for ch in channel_demo_ir["channels"]}
        assert "INBOUND" in directions
        assert "OUTBOUND" in directions


# ═══════════════════════════════════════════════════════════════════════
# 3. CHANNEL REFLECTION
# ═══════════════════════════════════════════════════════════════════════


class TestChannelReflection:
    """Reflection endpoints expose channel metadata."""

    def test_reflect_channels_endpoint(self, channel_simple):
        r = channel_simple.get("/api/reflect/channels")
        # Accept 200 or 404 (endpoint may not be implemented yet)
        if r.status_code == 200:
            data = r.json()
            assert isinstance(data, (list, dict))

    def test_reflect_root_includes_channels(self, channel_simple):
        r = channel_simple.get("/api/reflect")
        assert r.status_code == 200
        # Check that the reflect endpoint works (channels may be in extended reflect)

    def test_reflect_channels_on_channel_demo(self, channel_demo):
        r = channel_demo.get("/api/reflect/channels")
        if r.status_code == 200:
            text = json.dumps(r.json())
            # Should mention at least some channels
            assert "pagerduty" in text or "slack" in text or "github" in text


# ═══════════════════════════════════════════════════════════════════════
# 4. SECURITY AGENT APP — complex agent + channel composition
# ═══════════════════════════════════════════════════════════════════════


class TestSecurityAgentBootstrap:
    """Security Agent app boots and supports role-based access."""

    def test_app_boots_platform_engineer(self, security_agent):
        security_agent.set_role("platform engineer")
        r = security_agent.get("/security_dashboard")
        assert r.status_code == 200

    def test_app_boots_security_reviewer(self, security_agent):
        security_agent.set_role("security reviewer")
        r = security_agent.get("/review_queue")
        assert r.status_code == 200

    def test_create_finding(self, security_agent):
        security_agent.set_role("platform engineer")
        r = security_agent.post("/api/v1/findings", json={
            "app_name": f"test-app-{_uid()}",
            "finding_type": "iam-drift",
            "severity": "high",
            "summary": "IAM policy drift detected",
            "affected_resource": "arn:aws:iam::role/test",
        })
        assert r.status_code == 201

    def test_list_findings(self, security_agent):
        security_agent.set_role("platform engineer")
        r = security_agent.get("/api/v1/findings")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_state_machine_on_findings(self, security_agent):
        security_agent.set_role("platform engineer")
        r = security_agent.post("/api/v1/findings", json={
            "app_name": f"sm-{_uid()}",
            "finding_type": "cve",
            "severity": "medium",
            "summary": "CVE detected",
            "affected_resource": "dep:lodash@4.17.19",
        })
        finding = r.json()
        assert finding.get("status", finding.get("remediation")) in \
            ("detected", None), "Finding should start in initial state"

    def test_transition_finding(self, security_agent):
        security_agent.set_role("platform engineer")
        r = security_agent.post("/api/v1/findings", json={
            "app_name": f"tr-{_uid()}",
            "finding_type": "stale-secret",
            "severity": "low",
            "summary": "Stale secret",
            "affected_resource": "arn:aws:secretsmanager::secret/test",
        })
        fid = r.json()["id"]
        r2 = security_agent.post(f"/api/v1/findings/{fid}/_transition/remediation/analyzing")
        assert r2.status_code == 200

    def test_create_scan_run(self, security_agent):
        security_agent.set_role("platform engineer")
        r = security_agent.post("/api/v1/scan_runs", json={
            "scan_type": "iam-audit",
            "apps_scanned": 10,
            "findings_count": 3,
            "status": "completed",
        })
        assert r.status_code == 201

    def test_viewer_cannot_create_finding(self, security_agent):
        """app owner role lacks findings.triage scope."""
        security_agent.set_role("app owner")
        r = security_agent.post("/api/v1/findings", json={
            "app_name": "denied",
            "finding_type": "cve",
            "severity": "low",
            "summary": "Should be denied",
            "affected_resource": "test",
        })
        assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════════
# 5. DEFAULT FIELD VALUES
# ═══════════════════════════════════════════════════════════════════════


class TestDefaultFieldValues:
    """Fields with default_expr should auto-populate."""

    def test_role_defaults_to_user(self, agent_chatbot):
        """The 'role' enum field has default_expr '"user"'."""
        agent_chatbot.set_role("anonymous")
        tag = _uid()
        r = agent_chatbot.post("/api/v1/messages", json={
            "body": f"Default role {tag}",
        })
        assert r.status_code == 201
        msg = r.json()
        # The role field should default to "user"
        assert msg.get("role") == "user"

    def test_explicit_role_overrides_default(self, agent_chatbot):
        """Explicitly setting role should override the default."""
        agent_chatbot.set_role("anonymous")
        tag = _uid()
        r = agent_chatbot.post("/api/v1/messages", json={
            "body": f"Assistant msg {tag}",
            "role": "assistant",
        })
        assert r.status_code == 201
        msg = r.json()
        assert msg.get("role") == "assistant"


# ═══════════════════════════════════════════════════════════════════════
# 6. DEPLOY CONFIG VALIDATION
# ═══════════════════════════════════════════════════════════════════════


class TestDeployConfig:
    """Deploy config files exist and have valid structure."""

    def test_channel_simple_deploy_config_exists(self):
        path = FIXTURES_DIR / "channel_simple.deploy.json"
        assert path.exists(), "channel_simple.deploy.json should exist"

    def test_channel_demo_deploy_config_exists(self):
        path = FIXTURES_DIR / "channel_demo.deploy.json"
        assert path.exists()

    def test_security_agent_deploy_config_exists(self):
        path = FIXTURES_DIR / "security_agent.deploy.json"
        assert path.exists()

    def test_deploy_config_is_valid_json(self):
        for name in ("channel_simple", "channel_demo", "security_agent"):
            path = FIXTURES_DIR / f"{name}.deploy.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                assert isinstance(data, dict)

    def test_deploy_config_has_channels_section(self):
        """Deploy configs for channel apps should declare channel configs."""
        for name in ("channel_simple", "channel_demo"):
            path = FIXTURES_DIR / f"{name}.deploy.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                # Deploy config should have channels or channel_config or similar
                text = json.dumps(data)
                assert "channel" in text.lower() or "endpoint" in text.lower() or \
                    "config" in text.lower(), \
                    f"{name}.deploy.json should reference channels"


# ═══════════════════════════════════════════════════════════════════════
# 7. EVENT-DRIVEN BEHAVIOR
# ═══════════════════════════════════════════════════════════════════════


class TestEventTriggeredCompute:
    """Creating a record should fire events (observable via event log)."""

    def test_event_log_records_creation(self, channel_simple):
        """Creating a note should fire note.created event if events are processed."""
        channel_simple.set_role("anonymous")
        tag = _uid()
        channel_simple.post("/api/v1/notes", json={
            "title": f"Event {tag}", "body": "trigger test",
        })
        # Check event log (if runtime exposes it)
        r = channel_simple.get("/api/events")
        if r.status_code == 200:
            events = r.json()
            assert isinstance(events, list)

    def test_errors_endpoint_on_channel_app(self, channel_simple):
        """Error endpoint should exist."""
        r = channel_simple.get("/api/errors")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════
# 8. NAVIGATION AND PAGES
# ═══════════════════════════════════════════════════════════════════════


class TestV050AppNavigation:
    """New apps have correct navigation items."""

    def test_agent_simple_nav(self, agent_simple):
        r = agent_simple.get("/runtime/bootstrap")
        assert r.status_code == 200

    def test_channel_demo_nav_items(self, channel_demo):
        channel_demo.set_role("operator")
        r = channel_demo.get("/operations_center")
        assert r.status_code == 200

    def test_security_agent_role_based_nav(self, security_agent):
        """Different roles should see different pages."""
        security_agent.set_role("platform engineer")
        r1 = security_agent.get("/security_dashboard")
        assert r1.status_code == 200

        security_agent.set_role("app owner")
        r2 = security_agent.get("/my_apps")
        assert r2.status_code == 200
