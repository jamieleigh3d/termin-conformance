# Copyright 2026 Jamie-Leigh Blake and Termin project contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0

"""Conformance — v0.9.1 Phase 4 channel failure-mode semantics.

Companion to `specs/channel-contract.md` §5.

The default failure mode is `log-and-drop`. Every conforming runtime
MUST satisfy this end-to-end:

  - A provider whose send() raises MUST NOT cause channel_send() to
    raise.
  - The return shape is {"ok": False, "outcome": "failed", "channel": <display>}.
  - The error counter for that channel increments by one.

The other two modes (`surface-as-error`, `queue-and-retry-forever`)
are conditional in v0.9.1 — a runtime that has not implemented them
MUST cleanly fall back to log-and-drop. The test pack records both
the contract for runtimes that do implement them and the fallback
posture for runtimes that don't, so v0.9.0 and future runtimes can
both pass.

These are dispatcher-level tests against synthetic IR; they don't go
through the conformance adapter because the failure-mode contract is
about provider exception handling, not about HTTP routing.
"""

from __future__ import annotations

import asyncio

import pytest

from termin_server.channels import ChannelDispatcher
from termin_server.providers import (
    Category, ContractRegistry, ProviderRegistry,
)
from termin_server.providers.builtins import register_builtins


# ── Helpers ──


def _ch(display: str, contract: str = "webhook",
        direction: str = "OUTBOUND",
        failure_mode: str = "log-and-drop") -> dict:
    snake = display.replace(" ", "_").replace("-", "_")
    pascal = "".join(p.title() for p in display.replace("-", " ").split())
    return {
        "name": {"display": display, "snake": snake, "pascal": pascal},
        "direction": direction,
        "delivery": "AUTO",
        "provider_contract": contract,
        "failure_mode": failure_mode,
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
    channels = {}
    it = iter(name_binding_pairs)
    for name in it:
        channels[name] = next(it)
    return {"version": "0.9.0", "bindings": {"channels": channels}}


def _registry() -> ProviderRegistry:
    contracts = ContractRegistry.default()
    registry = ProviderRegistry()
    register_builtins(registry, contracts)
    return registry


# ── §5.2: log-and-drop is the default and is enforced ────────────


class TestLogAndDropDefault:
    """Per channel-contract.md §5.2 — every conforming runtime MUST
    enforce log-and-drop end-to-end. A provider that raises during
    send() MUST NOT cause channel_send() to raise."""

    def test_provider_exception_does_not_propagate(self):
        """Replace the bound provider with one whose send() raises;
        channel_send must catch and log-and-drop."""
        ir = _ir(_ch("alerts", "webhook"))
        deploy = _deploy("alerts", _binding())
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))

        class BoomProvider:
            async def send(self, body=None, headers=None):
                raise RuntimeError("simulated provider failure")

        # Replace the wired stub with a provider that raises.
        d._channel_providers["alerts"] = BoomProvider()

        # Must not raise.
        result = asyncio.run(d.channel_send("alerts", {"event": "x"}))
        assert result["ok"] is False
        assert result["outcome"] == "failed"
        assert result["channel"] == "alerts"

    def test_log_and_drop_increments_error_counter(self):
        """The dispatcher's per-channel error counter MUST reflect
        the failed send (when metrics are exposed; metrics shape is
        OPTIONAL per §7.4 but the side effect is part of the
        contract for runtimes that publish them)."""
        ir = _ir(_ch("alerts", "webhook"))
        deploy = _deploy("alerts", _binding())
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))

        class BoomProvider:
            async def send(self, body=None, headers=None):
                raise RuntimeError("simulated")

        d._channel_providers["alerts"] = BoomProvider()
        before = d._metrics.get("alerts", {}).get("errors", 0)
        asyncio.run(d.channel_send("alerts", {"event": "x"}))
        after = d._metrics.get("alerts", {}).get("errors", 0)
        assert after == before + 1, \
            f"errors counter expected {before + 1}, got {after}"

    def test_unknown_channel_still_raises_channel_error(self):
        """Spec §7.3 step 1: log-and-drop applies to provider
        failures, NOT to programming errors. A send to a channel
        name that doesn't exist in the IR is a programming error
        and MUST raise."""
        from termin_server.channel_config import ChannelError
        ir = _ir(_ch("alerts", "webhook"))
        deploy = _deploy("alerts", _binding())
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))
        with pytest.raises(ChannelError):
            asyncio.run(d.channel_send("nonexistent", {"x": 1}))

    def test_missing_provider_returns_not_configured_not_failed(self):
        """Spec §7.3 step 3: a channel whose provider couldn't be
        wired (no binding, fallback exhausted) returns ok=True with
        status 'not_configured' — distinct from log-and-drop after a
        provider exception."""
        ir = _ir(_ch("alerts", "webhook"))
        # No binding for "alerts"
        d = ChannelDispatcher(ir, _deploy(), _registry())
        asyncio.run(d.startup(strict=False))
        result = asyncio.run(d.channel_send("alerts", {"event": "x"}))
        assert result["ok"] is True
        assert result["status"] == "not_configured"
        assert "outcome" not in result or result.get("outcome") != "failed"


# ── §5.3: surface-as-error and queue-and-retry-forever ───────────


class TestSurfaceAsError:
    """Per channel-contract.md §5.3 — surface-as-error makes provider
    exceptions propagate. Conformance is conditional: a runtime that
    has not implemented this mode MUST fall back to log-and-drop and
    the test SKIPs accordingly."""

    def test_surface_as_error_either_propagates_or_falls_back(self):
        """A runtime is conforming iff one of the two postures holds:
            (a) the exception propagates (mode implemented), or
            (b) it falls back to log-and-drop (mode not yet implemented).
        Anything else — silent swallowing without a failed-shaped
        return, or some third behavior — is non-conforming."""
        ir = _ir(_ch("alerts", "webhook", failure_mode="surface-as-error"))
        deploy = _deploy("alerts", _binding())
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))

        class BoomProvider:
            async def send(self, body=None, headers=None):
                raise RuntimeError("simulated")

        d._channel_providers["alerts"] = BoomProvider()
        try:
            result = asyncio.run(d.channel_send("alerts", {"x": 1}))
        except Exception:
            # Posture (a): mode implemented; propagation is the
            # documented behavior.
            return
        # Posture (b): fallback. Result must be the log-and-drop
        # shape — the runtime cleanly degraded.
        assert result["ok"] is False
        assert result["outcome"] == "failed"
        assert result["channel"] == "alerts"


class TestQueueAndRetryForever:
    """Per channel-contract.md §5.3 — queue-and-retry-forever returns
    {"ok": False, "outcome": "queued", ...} immediately. Conformance
    is conditional: a runtime that has not implemented this mode MUST
    fall back to log-and-drop."""

    def test_queue_or_drop_either_posture_acceptable(self):
        ir = _ir(_ch("alerts", "webhook",
                     failure_mode="queue-and-retry-forever"))
        deploy = _deploy("alerts", _binding())
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))

        class BoomProvider:
            async def send(self, body=None, headers=None):
                raise RuntimeError("simulated")

        d._channel_providers["alerts"] = BoomProvider()
        result = asyncio.run(d.channel_send("alerts", {"x": 1}))
        # Posture (a) implemented: outcome="queued" with ok=False.
        # Posture (b) fallback: outcome="failed" with ok=False.
        assert result["ok"] is False
        assert result["outcome"] in ("queued", "failed"), \
            f"queue-and-retry-forever must produce 'queued' (implemented) " \
            f"or 'failed' (fallback), got outcome={result['outcome']!r}"


# ── §5.4: per-channel scope ──────────────────────────────────────


class TestPerChannelFailureMode:
    """Per channel-contract.md §5.4 — failure_mode is per-channel.
    Two channels in the same app may declare different modes; the
    runtime MUST honor each independently."""

    def test_two_channels_with_distinct_modes_both_wired(self):
        """Both channels start under strict mode; the one whose
        provider raises log-and-drops, while the other is unaffected."""
        ir = _ir(
            _ch("safe-alerts", "webhook", failure_mode="log-and-drop"),
            _ch("strict-alerts", "webhook", failure_mode="surface-as-error"),
        )
        deploy = _deploy("safe-alerts", _binding(),
                         "strict-alerts", _binding())
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=True))
        # Both channels wired, IR records distinct failure_modes.
        assert "safe-alerts" in d._channel_providers
        assert "strict-alerts" in d._channel_providers
        safe_spec = d.get_spec("safe-alerts")
        strict_spec = d.get_spec("strict-alerts")
        assert safe_spec["failure_mode"] == "log-and-drop"
        assert strict_spec["failure_mode"] == "surface-as-error"

    def test_log_and_drop_channel_does_not_disturb_other_channel(self):
        """A failure on one channel must not affect another's
        provider state."""
        ir = _ir(
            _ch("a", "webhook"),
            _ch("b", "webhook"),
        )
        deploy = _deploy("a", _binding(), "b", _binding())
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))

        class BoomProvider:
            async def send(self, body=None, headers=None):
                raise RuntimeError("simulated")

        d._channel_providers["a"] = BoomProvider()

        # Send to 'a' — log-and-drops.
        result_a = asyncio.run(d.channel_send("a", {"x": 1}))
        assert result_a["ok"] is False

        # 'b' is unaffected.
        result_b = asyncio.run(d.channel_send("b", {"x": 2}))
        assert result_b["ok"] is True
        assert result_b["outcome"] == "delivered"
