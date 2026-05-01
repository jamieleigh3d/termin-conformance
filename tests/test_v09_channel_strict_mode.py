# Copyright 2026 Jamie-Leigh Blake and Termin project contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0

"""Conformance — v0.9.1 Phase 4 channel strict-mode binding validation.

Companion to `specs/channel-contract.md` §4 (strict mode) + §3.4
(v0.8 fallback rejected) + §3.6 (stub fallback for unknown product).

The strict-mode contract:
- An OUTBOUND or BIDIRECTIONAL channel with provider_contract MUST
  have a deploy binding when strict=True; missing → ChannelConfigError.
- INBOUND channels are exempt from strict mode (no outbound dispatch).
- INTERNAL channels are exempt (no provider).
- Top-level v0.8 `channels:` shape is not honored for provider-contract
  channels.
- Unknown product name falls back to the stub product for the same
  contract.
"""

from __future__ import annotations

import asyncio

import pytest

from termin_server.channels import ChannelDispatcher
from termin_server.channel_config import ChannelConfigError
from termin_server.providers import (
    Category, ContractRegistry, ProviderRegistry,
)
from termin_server.providers.builtins import register_builtins
from termin_server.providers.builtins.channel_webhook_stub import WebhookChannelStub


# ── Helpers ──


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


def _deploy_v09(*name_binding_pairs) -> dict:
    """v0.9 shape: bindings.channels.<name>."""
    channels = {}
    it = iter(name_binding_pairs)
    for name in it:
        channels[name] = next(it)
    return {"version": "0.9.0", "bindings": {"channels": channels}}


def _deploy_v08(*name_binding_pairs) -> dict:
    """v0.8 shape: top-level `channels:` with url/protocol — NOT a
    provider binding. Conformance §3.4 says this MUST NOT be honored
    for provider-contract channels."""
    channels = {}
    it = iter(name_binding_pairs)
    for name in it:
        channels[name] = next(it)
    return {"channels": channels}


def _registry() -> ProviderRegistry:
    contracts = ContractRegistry.default()
    registry = ProviderRegistry()
    register_builtins(registry, contracts)
    return registry


# ── §4.1: strict=True raises on missing binding ────────────────────


class TestStrictModeRaises:
    """Per channel-contract.md §4.1 — strict_channels=True with an
    OUTBOUND or BIDIRECTIONAL provider_contract channel that has no
    deploy binding MUST raise ChannelConfigError at startup."""

    def test_outbound_without_binding_raises(self):
        ir = _ir(_ch("alerts", "webhook", direction="OUTBOUND"))
        d = ChannelDispatcher(ir, _deploy_v09(), _registry())
        with pytest.raises(ChannelConfigError):
            asyncio.run(d.startup(strict=True))

    def test_bidirectional_without_binding_raises(self):
        """Bidirectional has an outbound side; strict applies."""
        ir = _ir(_ch("ops", "messaging", direction="BIDIRECTIONAL"))
        d = ChannelDispatcher(ir, _deploy_v09(), _registry())
        with pytest.raises(ChannelConfigError):
            asyncio.run(d.startup(strict=True))

    def test_strict_error_names_the_channel(self):
        """Spec §4.1: error message MUST name the channel and contract."""
        ir = _ir(_ch("alerts", "webhook"))
        d = ChannelDispatcher(ir, _deploy_v09(), _registry())
        with pytest.raises(ChannelConfigError) as exc_info:
            asyncio.run(d.startup(strict=True))
        msg = str(exc_info.value)
        assert "alerts" in msg
        assert "webhook" in msg


# ── §4.1: strict=True succeeds when bindings are present ──────────


class TestStrictModeOk:
    def test_strict_ok_with_binding(self):
        ir = _ir(_ch("alerts", "webhook"))
        deploy = _deploy_v09("alerts", _binding())
        d = ChannelDispatcher(ir, deploy, _registry())
        # Must not raise.
        asyncio.run(d.startup(strict=True))
        assert "alerts" in d._channel_providers


# ── §4.1: strict=False is silent on missing binding ────────────────


class TestNonStrictMode:
    """Per channel-contract.md §4.1 — strict=False with a missing
    binding MUST log and continue. Subsequent channel_send MUST
    log-and-drop."""

    def test_non_strict_skips_missing_binding(self):
        ir = _ir(_ch("alerts", "webhook"))
        d = ChannelDispatcher(ir, _deploy_v09(), _registry())
        # Must not raise.
        asyncio.run(d.startup(strict=False))
        assert "alerts" not in d._channel_providers

    def test_non_strict_send_returns_not_configured(self):
        """The log-and-drop posture for missing-provider returns a
        success-shaped dict so the app keeps running."""
        ir = _ir(_ch("alerts", "webhook"))
        d = ChannelDispatcher(ir, _deploy_v09(), _registry())
        asyncio.run(d.startup(strict=False))
        result = asyncio.run(d.channel_send("alerts", {"event": "x"}))
        assert result["ok"] is True
        assert result["status"] == "not_configured"


# ── §4.3: inbound channels are exempt ──────────────────────────────


class TestInboundExempt:
    """Per channel-contract.md §4.3 — INBOUND channels do not require
    a deploy binding. Strict mode succeeds with an inbound-only IR
    and an empty bindings.channels."""

    def test_inbound_only_ir_starts_under_strict(self):
        # Inbound channels with no provider_contract have no outbound
        # provider to wire — only the auto-route gets registered (§6).
        ir = _ir(_ch("inbound-hook", contract=None, direction="INBOUND"))
        d = ChannelDispatcher(ir, _deploy_v09(), _registry())
        asyncio.run(d.startup(strict=True))
        # Empty providers map; no exception.
        assert d._channel_providers == {}


# ── §4.4: internal channels are exempt ─────────────────────────────


class TestInternalExempt:
    """Per channel-contract.md §4.4 — INTERNAL channels with no
    provider_contract use the distributed runtime layer. Strict mode
    does not require a binding."""

    def test_internal_channel_no_binding_starts_under_strict(self):
        ir = _ir(_ch("event-bus", contract=None, direction="INTERNAL"))
        d = ChannelDispatcher(ir, _deploy_v09(), _registry())
        asyncio.run(d.startup(strict=True))
        assert "event-bus" not in d._channel_providers


# ── §3.4: v0.8 fallback explicitly rejected ───────────────────────


class TestV08FallbackRejected:
    """Per channel-contract.md §3.4 — v0.8 top-level `channels:` shape
    is NOT honored for provider-contract channels. A deploy that puts
    a binding only at the top level MUST be treated as if there were
    no binding at all."""

    def test_v08_only_deploy_under_strict_raises(self):
        """Deploy has only top-level `channels:` (no
        bindings.channels). Strict mode treats this as no binding."""
        ir = _ir(_ch("alerts", "webhook"))
        deploy = _deploy_v08("alerts",
                             {"url": "https://hook.example.com",
                              "protocol": "http"})
        d = ChannelDispatcher(ir, deploy, _registry())
        with pytest.raises(ChannelConfigError):
            asyncio.run(d.startup(strict=True))

    def test_v08_only_deploy_non_strict_log_and_drops(self):
        ir = _ir(_ch("alerts", "webhook"))
        deploy = _deploy_v08("alerts",
                             {"url": "https://hook.example.com",
                              "protocol": "http"})
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))
        # Provider not wired — v0.8 shape is invisible to v0.9
        # provider-contract dispatch.
        assert "alerts" not in d._channel_providers


# ── §3.6: unknown product falls back to stub ──────────────────────


class TestUnknownProductFallback:
    """Per channel-contract.md §3.6 — when a binding names a product
    the registry doesn't know, the runtime falls back to the
    `(Category.CHANNELS, contract, "stub")` lookup. This MUST NOT
    raise."""

    def test_unknown_webhook_product_falls_back_to_stub(self):
        ir = _ir(_ch("alerts", "webhook"))
        deploy = _deploy_v09("alerts",
                             _binding(provider="nonexistent-product"))
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))
        # Falls back to webhook stub.
        assert isinstance(d._channel_providers.get("alerts"),
                          WebhookChannelStub)

    def test_unknown_product_under_strict_does_not_raise(self):
        """Strict mode is about binding presence, not about the
        binding naming a known product. The stub fallback satisfies
        strict mode because the channel is observably wired up."""
        ir = _ir(_ch("alerts", "webhook"))
        deploy = _deploy_v09("alerts",
                             _binding(provider="nonexistent-product"))
        d = ChannelDispatcher(ir, deploy, _registry())
        # Must not raise — stub fallback wires the channel.
        asyncio.run(d.startup(strict=True))
        assert "alerts" in d._channel_providers
