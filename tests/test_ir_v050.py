"""Termin Conformance Suite — IR Structure Tests for v0.5.0.

Validates that the IR JSON emitted by the Termin compiler contains
the new fields and structures introduced in v0.5.0:

  - ComputeSpec: directive, trigger_where, accesses, input_fields,
    output_fields, output_creates, shape=NONE, provider (llm, ai-agent)
  - ContentSchema: singular
  - ChannelSpec: actions (ChannelActionSpec)
  - EventActionSpec: send_content, send_channel
  - semantic_mark component type (if present in pages)
  - Deploy config validation

These are pure IR introspection tests — no HTTP calls, no runtime.
They verify the compiler's output contract.

Authors: Jamie-Leigh Blake & Claude Anthropic
"""

import json
import pytest


# ═══════════════════════════════════════════════════════════════════════
# 1. CONTENT SCHEMA — singular field
# ═══════════════════════════════════════════════════════════════════════


class TestContentSchemaSingular:
    """Every ContentSchema must have a 'singular' field (v0.5.0+)."""

    def test_singular_present_on_agent_simple(self, agent_simple_ir):
        for content in agent_simple_ir["content"]:
            assert "singular" in content, f"Missing 'singular' on {content['name']}"
            assert isinstance(content["singular"], str)
            assert len(content["singular"]) > 0

    def test_singular_value_completions(self, agent_simple_ir):
        """'completions' content should have singular 'completion'."""
        completions = [c for c in agent_simple_ir["content"]
                       if c["name"]["snake"] == "completions"]
        assert len(completions) == 1
        assert completions[0]["singular"] == "completion"

    def test_singular_value_echoes(self, channel_simple_ir):
        """'echoes' content should have singular 'echo'."""
        echoes = [c for c in channel_simple_ir["content"]
                  if c["name"]["snake"] == "echoes"]
        assert len(echoes) == 1
        assert echoes[0]["singular"] == "echo"

    def test_singular_value_notes(self, channel_simple_ir):
        """'notes' content should have singular 'note'."""
        notes = [c for c in channel_simple_ir["content"]
                 if c["name"]["snake"] == "notes"]
        assert len(notes) == 1
        assert notes[0]["singular"] == "note"

    def test_singular_present_on_channel_demo(self, channel_demo_ir):
        for content in channel_demo_ir["content"]:
            assert "singular" in content, f"Missing 'singular' on {content['name']}"

    def test_singular_present_on_security_agent(self, security_agent_ir):
        for content in security_agent_ir["content"]:
            assert "singular" in content

    def test_singular_present_on_warehouse_if_recompiled(self, warehouse_ir):
        """Existing apps have singular after recompilation with v0.5.0+ compiler.

        This test is advisory — warehouse may not have been recompiled yet.
        Skip if the first content lacks 'singular'.
        """
        if warehouse_ir["content"] and "singular" not in warehouse_ir["content"][0]:
            pytest.skip("warehouse IR not yet recompiled with v0.5.0+ compiler")
        for content in warehouse_ir["content"]:
            assert "singular" in content

    def test_singular_present_on_helpdesk_if_recompiled(self, helpdesk_ir):
        """Advisory — helpdesk may not have been recompiled yet."""
        if helpdesk_ir["content"] and "singular" not in helpdesk_ir["content"][0]:
            pytest.skip("helpdesk IR not yet recompiled with v0.5.0+ compiler")
        for content in helpdesk_ir["content"]:
            assert "singular" in content

    def test_singular_present_on_agent_chatbot(self, agent_chatbot_ir):
        messages = [c for c in agent_chatbot_ir["content"]
                    if c["name"]["snake"] == "messages"]
        assert len(messages) == 1
        assert messages[0]["singular"] == "message"


# ═══════════════════════════════════════════════════════════════════════
# 2. COMPUTE SPEC — new fields (directive, trigger_where, accesses, etc.)
# ═══════════════════════════════════════════════════════════════════════


class TestComputeSpecNewFields:
    """ComputeSpec must contain the v0.5.0 fields."""

    def _get_compute(self, ir, snake_name):
        matches = [c for c in ir.get("computes", [])
                   if c["name"]["snake"] == snake_name]
        assert len(matches) == 1, f"Expected 1 compute named '{snake_name}', got {len(matches)}"
        return matches[0]

    def test_directive_present_on_llm_compute(self, agent_simple_ir):
        compute = self._get_compute(agent_simple_ir, "complete")
        assert "directive" in compute
        assert compute["directive"] is not None
        assert isinstance(compute["directive"], str)
        assert len(compute["directive"]) > 0

    def test_directive_null_on_cel_compute(self, compute_demo_ir):
        """CEL computes should have directive=null."""
        for compute in compute_demo_ir.get("computes", []):
            if compute.get("provider") is None or compute.get("provider") == "cel":
                assert compute.get("directive") is None

    def test_trigger_where_field_present(self, agent_simple_ir):
        compute = self._get_compute(agent_simple_ir, "complete")
        assert "trigger_where" in compute

    def test_accesses_field_present(self, agent_simple_ir):
        compute = self._get_compute(agent_simple_ir, "complete")
        assert "accesses" in compute
        assert isinstance(compute["accesses"], list)

    def test_accesses_contains_completions(self, agent_simple_ir):
        compute = self._get_compute(agent_simple_ir, "complete")
        assert "completions" in compute["accesses"]

    def test_input_fields_present(self, agent_simple_ir):
        compute = self._get_compute(agent_simple_ir, "complete")
        assert "input_fields" in compute
        assert isinstance(compute["input_fields"], list)

    def test_input_fields_value(self, agent_simple_ir):
        """input_fields should be [['completion', 'prompt']] for agent_simple."""
        compute = self._get_compute(agent_simple_ir, "complete")
        assert len(compute["input_fields"]) >= 1
        # Each entry is a [content_ref, field_name] pair
        first = compute["input_fields"][0]
        assert len(first) == 2
        assert first[0] == "completion"
        assert first[1] == "prompt"

    def test_output_fields_present(self, agent_simple_ir):
        compute = self._get_compute(agent_simple_ir, "complete")
        assert "output_fields" in compute
        assert isinstance(compute["output_fields"], list)

    def test_output_fields_value(self, agent_simple_ir):
        """output_fields should be [['completion', 'response']] for agent_simple."""
        compute = self._get_compute(agent_simple_ir, "complete")
        assert len(compute["output_fields"]) >= 1
        first = compute["output_fields"][0]
        assert first[0] == "completion"
        assert first[1] == "response"

    def test_output_creates_field_present(self, agent_simple_ir):
        compute = self._get_compute(agent_simple_ir, "complete")
        assert "output_creates" in compute

    def test_output_creates_null_when_not_creating(self, agent_simple_ir):
        compute = self._get_compute(agent_simple_ir, "complete")
        assert compute["output_creates"] is None


class TestComputeShapeNone:
    """ComputeSpec.shape can be NONE for LLM/agent providers."""

    def test_shape_none_on_llm_compute(self, agent_simple_ir):
        compute = [c for c in agent_simple_ir["computes"]
                   if c["name"]["snake"] == "complete"][0]
        assert compute["shape"] == "NONE"

    def test_shape_not_none_on_cel_compute(self, compute_demo_ir):
        """CEL computes must not have NONE shape (reserved for LLM/agent)."""
        for compute in compute_demo_ir.get("computes", []):
            if compute.get("provider") is None or compute.get("provider") == "cel":
                assert compute["shape"] != "NONE", \
                    f"CEL compute '{compute['name']['snake']}' should not have NONE shape"
                assert isinstance(compute["shape"], str) and len(compute["shape"]) > 0


class TestComputeProvider:
    """Provider field distinguishes CEL, LLM, and AI-agent computes."""

    def test_provider_llm(self, agent_simple_ir):
        compute = [c for c in agent_simple_ir["computes"]
                   if c["name"]["snake"] == "complete"][0]
        assert compute["provider"] == "llm"

    def test_provider_ai_agent(self, security_agent_ir):
        scanner = [c for c in security_agent_ir["computes"]
                   if c["name"]["snake"] == "scanner"][0]
        assert scanner["provider"] == "ai-agent"

    def test_provider_ai_agent_remediator(self, security_agent_ir):
        remediator = [c for c in security_agent_ir["computes"]
                      if c["name"]["snake"] == "remediator"][0]
        assert remediator["provider"] == "ai-agent"

    def test_provider_null_for_cel(self, compute_demo_ir):
        """Legacy CEL computes may have provider=null or provider='cel'."""
        for compute in compute_demo_ir.get("computes", []):
            if compute["shape"] == "TRANSFORM" and compute.get("body_lines"):
                assert compute.get("provider") in (None, "cel")

    def test_provider_ai_agent_on_channel_demo(self, channel_demo_ir):
        """auto-mitigate compute should be ai-agent provider."""
        auto_mitigate = [c for c in channel_demo_ir["computes"]
                         if c["name"]["snake"] == "auto_mitigate"]
        if auto_mitigate:
            assert auto_mitigate[0]["provider"] == "ai-agent"


class TestComputeObjectiveStrategy:
    """AI agent computes should have objective and optionally strategy."""

    def test_objective_present_on_llm(self, agent_simple_ir):
        compute = [c for c in agent_simple_ir["computes"]
                   if c["name"]["snake"] == "complete"][0]
        assert "objective" in compute
        assert compute["objective"] is not None

    def test_objective_present_on_agent(self, security_agent_ir):
        scanner = [c for c in security_agent_ir["computes"]
                   if c["name"]["snake"] == "scanner"][0]
        assert scanner["objective"] is not None

    def test_strategy_present_on_agent(self, security_agent_ir):
        scanner = [c for c in security_agent_ir["computes"]
                   if c["name"]["snake"] == "scanner"][0]
        assert "strategy" in scanner
        assert scanner["strategy"] is not None

    def test_strategy_null_on_llm(self, agent_simple_ir):
        compute = [c for c in agent_simple_ir["computes"]
                   if c["name"]["snake"] == "complete"][0]
        assert compute.get("strategy") is None


class TestComputeTrigger:
    """Trigger and trigger_where on ComputeSpec."""

    def test_event_trigger_on_llm(self, agent_simple_ir):
        compute = [c for c in agent_simple_ir["computes"]
                   if c["name"]["snake"] == "complete"][0]
        assert "trigger" in compute
        assert "event" in compute["trigger"].lower() or "completion" in compute["trigger"].lower()

    def test_schedule_trigger_on_scanner(self, security_agent_ir):
        scanner = [c for c in security_agent_ir["computes"]
                   if c["name"]["snake"] == "scanner"][0]
        assert "schedule" in scanner["trigger"].lower()

    def test_trigger_where_null_when_unfiltered(self, agent_simple_ir):
        compute = [c for c in agent_simple_ir["computes"]
                   if c["name"]["snake"] == "complete"][0]
        assert compute["trigger_where"] is None


class TestComputePrePostConditions:
    """Pre/post conditions on agent computes."""

    def test_preconditions_present(self, security_agent_ir):
        scanner = [c for c in security_agent_ir["computes"]
                   if c["name"]["snake"] == "scanner"][0]
        assert "preconditions" in scanner
        assert isinstance(scanner["preconditions"], list)
        assert len(scanner["preconditions"]) >= 1

    def test_postconditions_present(self, security_agent_ir):
        scanner = [c for c in security_agent_ir["computes"]
                   if c["name"]["snake"] == "scanner"][0]
        assert "postconditions" in scanner
        assert isinstance(scanner["postconditions"], list)
        assert len(scanner["postconditions"]) >= 1


# ═══════════════════════════════════════════════════════════════════════
# 3. CHANNEL SPEC — actions
# ═══════════════════════════════════════════════════════════════════════


class TestChannelActions:
    """ChannelSpec.actions array with ChannelActionSpec entries."""

    def _get_channel(self, ir, snake_name):
        matches = [ch for ch in ir.get("channels", [])
                   if ch["name"]["snake"] == snake_name]
        assert len(matches) == 1, f"Expected 1 channel named '{snake_name}'"
        return matches[0]

    def test_actions_field_present(self, security_agent_ir):
        channel = self._get_channel(security_agent_ir, "security_tools")
        assert "actions" in channel
        assert isinstance(channel["actions"], list)

    def test_security_tools_has_three_actions(self, security_agent_ir):
        channel = self._get_channel(security_agent_ir, "security_tools")
        assert len(channel["actions"]) == 3

    def test_action_has_name(self, security_agent_ir):
        channel = self._get_channel(security_agent_ir, "security_tools")
        for action in channel["actions"]:
            assert "name" in action
            assert "snake" in action["name"]
            assert "display" in action["name"]

    def test_action_has_takes_and_returns(self, security_agent_ir):
        channel = self._get_channel(security_agent_ir, "security_tools")
        for action in channel["actions"]:
            assert "takes" in action
            assert "returns" in action
            assert isinstance(action["takes"], list)
            assert isinstance(action["returns"], list)

    def test_action_takes_param_structure(self, security_agent_ir):
        channel = self._get_channel(security_agent_ir, "security_tools")
        restrict = [a for a in channel["actions"]
                    if a["name"]["snake"] == "restrict_policy"][0]
        assert len(restrict["takes"]) == 2
        for param in restrict["takes"]:
            assert "name" in param
            assert "param_type" in param

    def test_action_returns_param_structure(self, security_agent_ir):
        channel = self._get_channel(security_agent_ir, "security_tools")
        restrict = [a for a in channel["actions"]
                    if a["name"]["snake"] == "restrict_policy"][0]
        assert len(restrict["returns"]) == 1
        assert restrict["returns"][0]["name"] == "result"

    def test_action_required_scopes(self, security_agent_ir):
        channel = self._get_channel(security_agent_ir, "security_tools")
        restrict = [a for a in channel["actions"]
                    if a["name"]["snake"] == "restrict_policy"][0]
        assert "required_scopes" in restrict
        assert "findings.remediate" in restrict["required_scopes"]

    def test_describe_iam_policy_action(self, security_agent_ir):
        channel = self._get_channel(security_agent_ir, "security_tools")
        describe = [a for a in channel["actions"]
                    if a["name"]["snake"] == "describe_iam_policy"][0]
        assert describe["takes"][0]["name"] == "role"
        assert describe["returns"][0]["name"] == "policy"
        assert "findings.view" in describe["required_scopes"]

    def test_channel_demo_cloud_provider_actions(self, channel_demo_ir):
        channel = self._get_channel(channel_demo_ir, "cloud_provider")
        assert len(channel["actions"]) == 3
        action_names = {a["name"]["snake"] for a in channel["actions"]}
        assert "restart_service" in action_names
        assert "scale_service" in action_names
        assert "rollback_deployment" in action_names

    def test_channel_demo_slack_actions(self, channel_demo_ir):
        channel = self._get_channel(channel_demo_ir, "slack")
        action_names = {a["name"]["snake"] for a in channel["actions"]}
        assert "post_message" in action_names
        assert "update_status" in action_names

    def test_empty_actions_on_data_channel(self, channel_simple_ir):
        """Data-only channels have empty actions array."""
        for channel in channel_simple_ir["channels"]:
            assert "actions" in channel
            assert channel["actions"] == []

    def test_empty_actions_on_inbound_data_channel(self, channel_demo_ir):
        channel = self._get_channel(channel_demo_ir, "github_webhooks")
        assert channel["actions"] == []


class TestChannelDirection:
    """Channel direction values including INTERNAL."""

    def test_outbound_direction(self, channel_simple_ir):
        note_sync = [ch for ch in channel_simple_ir["channels"]
                     if ch["name"]["snake"] == "note_sync"][0]
        assert note_sync["direction"] == "OUTBOUND"

    def test_inbound_direction(self, channel_simple_ir):
        echo_recv = [ch for ch in channel_simple_ir["channels"]
                     if ch["name"]["snake"] == "echo_receiver"][0]
        assert echo_recv["direction"] == "INBOUND"

    def test_bidirectional_direction(self, channel_demo_ir):
        slack = [ch for ch in channel_demo_ir["channels"]
                 if ch["name"]["snake"] == "slack"][0]
        assert slack["direction"] == "BIDIRECTIONAL"

    def test_internal_direction(self, channel_demo_ir):
        bus = [ch for ch in channel_demo_ir["channels"]
               if ch["name"]["snake"] == "incident_bus"][0]
        assert bus["direction"] == "INTERNAL"


class TestChannelRequirements:
    """Channel requirements include direction field."""

    def test_requirement_has_direction(self, channel_simple_ir):
        for channel in channel_simple_ir["channels"]:
            for req in channel.get("requirements", []):
                assert "direction" in req
                assert req["direction"] in ("send", "receive", "invoke")


# ═══════════════════════════════════════════════════════════════════════
# 4. EVENT SPEC — send_content and send_channel
# ═══════════════════════════════════════════════════════════════════════


class TestEventSendAction:
    """EventActionSpec with send_content and send_channel for channel sends."""

    def test_send_content_present(self, channel_simple_ir):
        for event in channel_simple_ir["events"]:
            assert "action" in event
            action = event["action"]
            assert "send_content" in action

    def test_send_channel_present(self, channel_simple_ir):
        for event in channel_simple_ir["events"]:
            action = event["action"]
            assert "send_channel" in action

    def test_send_content_value_note(self, channel_simple_ir):
        event = channel_simple_ir["events"][0]
        assert event["action"]["send_content"] == "note"

    def test_send_channel_value_note_sync(self, channel_simple_ir):
        event = channel_simple_ir["events"][0]
        assert event["action"]["send_channel"] == "note-sync"

    def test_channel_demo_pagerduty_send(self, channel_demo_ir):
        """Critical incidents should send to pagerduty."""
        pagerduty_events = [e for e in channel_demo_ir["events"]
                            if e["action"].get("send_channel") == "pagerduty"]
        assert len(pagerduty_events) >= 1
        assert pagerduty_events[0]["action"]["send_content"] == "incident"

    def test_channel_demo_slack_send(self, channel_demo_ir):
        """Resolved incidents should send to slack."""
        slack_events = [e for e in channel_demo_ir["events"]
                        if e["action"].get("send_channel") == "slack"]
        assert len(slack_events) >= 1

    def test_security_agent_flagged_event_sends_to_slack(self, security_agent_ir):
        slack_events = [e for e in security_agent_ir["events"]
                        if e["action"].get("send_channel") == "slack"]
        assert len(slack_events) >= 1
        assert slack_events[0]["action"]["send_content"] == "finding"

    def test_event_condition_expr_present(self, channel_demo_ir):
        for event in channel_demo_ir["events"]:
            assert "condition_expr" in event
            assert isinstance(event["condition_expr"], str)

    def test_event_log_level_present(self, channel_demo_ir):
        for event in channel_demo_ir["events"]:
            assert "log_level" in event
            assert event["log_level"] in ("TRACE", "DEBUG", "INFO", "WARN", "ERROR")


# ═══════════════════════════════════════════════════════════════════════
# 5. CROSS-CUTTING: all new fixtures validate top-level IR structure
# ═══════════════════════════════════════════════════════════════════════


class TestIRTopLevelStructure:
    """All IR files have required top-level fields."""

    @pytest.mark.parametrize("ir_fixture", [
        "agent_simple_ir", "agent_chatbot_ir", "channel_simple_ir",
        "channel_demo_ir", "security_agent_ir",
    ])
    def test_ir_version(self, ir_fixture, request):
        ir = request.getfixturevalue(ir_fixture)
        assert ir["ir_version"] == "0.7.0"

    @pytest.mark.parametrize("ir_fixture", [
        "agent_simple_ir", "agent_chatbot_ir", "channel_simple_ir",
        "channel_demo_ir", "security_agent_ir",
    ])
    def test_has_app_id(self, ir_fixture, request):
        ir = request.getfixturevalue(ir_fixture)
        assert "app_id" in ir
        assert len(ir["app_id"]) > 0

    @pytest.mark.parametrize("ir_fixture", [
        "agent_simple_ir", "agent_chatbot_ir", "channel_simple_ir",
        "channel_demo_ir", "security_agent_ir",
    ])
    def test_has_required_sections(self, ir_fixture, request):
        ir = request.getfixturevalue(ir_fixture)
        for key in ("auth", "content", "routes", "pages", "channels",
                     "computes", "events"):
            assert key in ir, f"Missing top-level key '{key}'"


class TestComputeFieldsAllFixtures:
    """All compute specs across all fixtures have v0.5.0 fields."""

    @pytest.mark.parametrize("ir_fixture", [
        "agent_simple_ir", "channel_demo_ir", "security_agent_ir",
    ])
    def test_all_computes_have_v050_fields(self, ir_fixture, request):
        """All computes in v0.5.0-compiled apps have new fields."""
        ir = request.getfixturevalue(ir_fixture)
        for compute in ir.get("computes", []):
            for field in ("directive", "trigger_where", "accesses",
                          "input_fields", "output_fields", "output_creates",
                          "provider", "objective", "strategy"):
                assert field in compute, \
                    f"Compute '{compute['name']['snake']}' missing '{field}'"

    def test_pre_v050_computes_may_lack_new_fields(self, compute_demo_ir):
        """Computes from pre-v0.5.0 apps may not have new fields.

        This is advisory — compute_demo may not have been recompiled.
        """
        for compute in compute_demo_ir.get("computes", []):
            if "directive" not in compute:
                pytest.skip("compute_demo IR not yet recompiled with v0.5.0+ compiler")
            break
