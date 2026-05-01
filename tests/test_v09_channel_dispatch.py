# Copyright 2026 Jamie-Leigh Blake and Termin project contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0

"""Conformance — v0.9.1 Phase 4 channel dispatcher.

Companion to `specs/channel-contract.md` §3 (registry surface +
binding shape) and §7 (dispatcher's public contract).

Tests:
- startup() wires providers from bindings.channels (§7.2)
- channel_send() routes to the right provider method per contract (§7.3)
- messaging dispatch returns a message_ref id (§2.4 / §7.3)
- provider isolation: two channels of the same contract get distinct
  provider instances (§3.5)

Synthetic IR + synthetic deploy config — no compiled fixtures.
This is the layer that exercises the dispatcher's contract directly.
"""

from __future__ import annotations

import asyncio

import pytest

from termin_server.channels import ChannelDispatcher
from termin_server.providers import (
    Category, ContractRegistry, ProviderRegistry,
)
from termin_server.providers.builtins import register_builtins
from termin_server.providers.builtins.channel_webhook_stub import WebhookChannelStub
from termin_server.providers.builtins.channel_email_stub import EmailChannelStub
from termin_server.providers.builtins.channel_messaging_stub import (
    MessagingChannelStub,
)


# ── Helpers: synthetic IR + deploy fragments ──


def _ch(display: str, contract: str | None,
        direction: str = "OUTBOUND") -> dict:
    snake = display.replace(" ", "_").replace("-", "_")
    pascal = "".join(p.title() for p in display.replace("-", " ").split())
    return {
        "name": {"display": display, "snake": snake, "pascal": pascal},
        "direction": direction,
        "delivery": "AUTO",
        "provider_contract": contract,
        "failure_mode": "log-and-drop",
        "carries_content": "",
        "requirements": [],
        "actions": [],
    }


def _ir(*channels) -> dict:
    return {
        "name": "Test App",
        "channels": list(channels),
        "auth": {"scopes": ["admin"],
                 "roles": [{"name": "admin", "scopes": ["admin"]}]},
        "content": [],
        "events": [],
        "computes": [],
    }


def _binding(provider: str = "stub", config: dict | None = None) -> dict:
    return {"provider": provider, "config": config or {}}


def _deploy(*name_binding_pairs) -> dict:
    """Build a v0.9 deploy config: pass alternating name, binding."""
    channels = {}
    it = iter(name_binding_pairs)
    for name in it:
        binding = next(it)
        channels[name] = binding
    return {"version": "0.9.0", "bindings": {"channels": channels}}


def _registry() -> ProviderRegistry:
    contracts = ContractRegistry.default()
    registry = ProviderRegistry()
    register_builtins(registry, contracts)
    return registry


# ── §7.2: startup() wires providers ────────────────────────────────


class TestStartupWiring:
    """Per channel-contract.md §7.2 — startup() reads
    bindings.channels.<display> for each channel with a non-null
    provider_contract and constructs one provider per channel via
    `(Category.CHANNELS, contract, product)` lookup."""

    def test_webhook_channel_gets_webhook_provider(self):
        ir = _ir(_ch("alerts", "webhook"))
        deploy = _deploy("alerts", _binding())
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))
        assert isinstance(d._channel_providers.get("alerts"), WebhookChannelStub)

    def test_email_channel_gets_email_provider(self):
        ir = _ir(_ch("digests", "email"))
        deploy = _deploy("digests", _binding())
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))
        assert isinstance(d._channel_providers.get("digests"), EmailChannelStub)

    def test_messaging_channel_gets_messaging_provider(self):
        ir = _ir(_ch("team chat", "messaging"))
        deploy = _deploy("team chat", _binding())
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))
        assert isinstance(d._channel_providers.get("team chat"),
                          MessagingChannelStub)

    def test_channel_with_no_provider_contract_is_skipped(self):
        """Spec §3.4 / §7.2: internal channels (no provider_contract) are
        not wired through the registry — the distributed runtime
        layer handles them."""
        ir = _ir(_ch("event-bus", contract=None, direction="INTERNAL"))
        d = ChannelDispatcher(ir, _deploy(), _registry())
        asyncio.run(d.startup(strict=False))
        assert "event-bus" not in d._channel_providers

    def test_factory_receives_binding_config(self):
        """Spec §3.3: the deploy config's `config` sub-dict is passed
        verbatim to the provider factory. Verified observably by
        sending — the webhook stub stamps the configured target into
        every audit record."""
        ir = _ir(_ch("alerts", "webhook"))
        deploy = _deploy("alerts", _binding(config={"target": "https://x.example/h"}))
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))
        asyncio.run(d.channel_send("alerts", {"event": "x"}))
        stub = d._channel_providers["alerts"]
        # The stub records the configured target on every send.
        assert stub.sent_calls[0]["target"] == "https://x.example/h"


# ── §7.3: channel_send routes through provider ────────────────────


class TestSendDispatch:
    """Per channel-contract.md §7.3 — channel_send dispatches by
    contract: webhook → provider.send(body), email → provider.send(
    recipients, subject, body, ...), messaging → provider.send(
    target, message_text)."""

    def test_webhook_send_routes_body_to_provider(self):
        ir = _ir(_ch("alerts", "webhook"))
        deploy = _deploy("alerts", _binding())
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))
        result = asyncio.run(d.channel_send("alerts", {"event": "stock_low"}))
        assert result["ok"] is True
        assert result["channel"] == "alerts"
        assert result["outcome"] == "delivered"
        stub = d._channel_providers["alerts"]
        assert len(stub.sent_calls) == 1
        assert stub.sent_calls[0]["body"] == {"event": "stock_low"}

    def test_email_send_unpacks_data_dict(self):
        """Email dispatch maps data['recipients'], data['subject'],
        data['body'] (and optional html_body) to the provider call."""
        ir = _ir(_ch("digests", "email"))
        deploy = _deploy("digests", _binding())
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))
        asyncio.run(d.channel_send("digests", {
            "recipients": ["alice@example.com", "bob@example.com"],
            "subject": "Weekly digest",
            "body": "Plain body",
            "html_body": "<b>HTML body</b>",
        }))
        stub = d._channel_providers["digests"]
        assert len(stub.inbox) == 1
        captured = stub.inbox[0]
        assert captured.recipients == ["alice@example.com", "bob@example.com"]
        assert captured.subject == "Weekly digest"
        assert captured.body == "Plain body"
        assert captured.html_body == "<b>HTML body</b>"

    def test_messaging_send_resolves_target_from_config(self):
        """Spec §2.4: target is the physical platform identifier
        resolved from the binding's config.target — not the source
        logical channel name."""
        ir = _ir(_ch("ops chat", "messaging"))
        deploy = _deploy("ops chat",
                         _binding(config={"target": "supplier-team-prod"}))
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))
        asyncio.run(d.channel_send("ops chat",
                                   {"text": "Reorder needed"}))
        stub = d._channel_providers["ops chat"]
        assert len(stub.sent_messages) == 1
        # Resolved target — NOT "ops chat".
        assert stub.sent_messages[0]["target"] == "supplier-team-prod"
        assert stub.sent_messages[0]["text"] == "Reorder needed"

    def test_messaging_send_returns_message_ref(self):
        """Spec §7.3: messaging dispatch returns
        {"ok": True, "outcome": "delivered", "message_ref": <id>}."""
        ir = _ir(_ch("ops chat", "messaging"))
        deploy = _deploy("ops chat", _binding(config={"target": "ops"}))
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))
        result = asyncio.run(d.channel_send("ops chat", {"text": "hi"}))
        assert result["ok"] is True
        assert result["outcome"] == "delivered"
        assert "message_ref" in result
        assert result["message_ref"].startswith("stub-msg-")

    def test_webhook_send_lookup_by_snake_name(self):
        """Spec §3.3: snake-case lookup MAY be supported as a fallback
        to the canonical display form."""
        ir = _ir(_ch("team chat", "messaging"))
        deploy = _deploy("team chat", _binding(config={"target": "ops"}))
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))
        # Send by snake form
        result = asyncio.run(d.channel_send("team_chat", {"text": "hi"}))
        assert result["ok"] is True
        # Provider stored by display name; both forms address the same provider
        stub = d._channel_providers["team chat"]
        assert len(stub.sent_messages) == 1


# ── §3.5: provider isolation ────────────────────────────────────


class TestProviderIsolation:
    """Per channel-contract.md §3.5 — two channels of the same
    contract get distinct provider instances. State held on one does
    not bleed into the other."""

    def test_two_webhooks_get_distinct_instances(self):
        ir = _ir(_ch("hook-a", "webhook"), _ch("hook-b", "webhook"))
        deploy = _deploy("hook-a", _binding(), "hook-b", _binding())
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))
        a = d._channel_providers["hook-a"]
        b = d._channel_providers["hook-b"]
        assert a is not b

    def test_send_on_one_does_not_appear_on_other(self):
        ir = _ir(_ch("hook-a", "webhook"), _ch("hook-b", "webhook"))
        deploy = _deploy("hook-a", _binding(), "hook-b", _binding())
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))
        asyncio.run(d.channel_send("hook-a", {"x": 1}))
        a = d._channel_providers["hook-a"]
        b = d._channel_providers["hook-b"]
        assert len(a.sent_calls) == 1
        assert len(b.sent_calls) == 0

    def test_two_messaging_channels_independent(self):
        """Messaging providers carry per-channel send counters that
        must not overlap."""
        ir = _ir(_ch("alpha", "messaging"), _ch("beta", "messaging"))
        deploy = _deploy("alpha", _binding(config={"target": "ch-a"}),
                         "beta", _binding(config={"target": "ch-b"}))
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))
        for _ in range(3):
            asyncio.run(d.channel_send("alpha", {"text": "msg"}))
        asyncio.run(d.channel_send("beta", {"text": "msg"}))
        assert len(d._channel_providers["alpha"].sent_messages) == 3
        assert len(d._channel_providers["beta"].sent_messages) == 1
