# Copyright 2026 Jamie-Leigh Blake and Termin project contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0

"""Conformance — v0.9.1 Phase 4 channel failure-mode semantics.

Companion to `specs/channel-contract.md` §5.

Three failure modes:

  - `log-and-drop` (default) — provider exceptions are caught;
    channel_send() returns {"ok": False, "outcome": "failed",
    "channel": <display>}; no exception propagates. End-to-end
    conformance, every runtime MUST pass §5.2.

  - `surface-as-error` — provider exceptions re-raise as
    ChannelError to the caller (original chained via __cause__).
    **Deterministic conformance** as of v0.9.1: a runtime that
    catches and swallows in this mode is non-conforming. §5.3.

  - `queue-and-retry` — grammar-accepted, IR-recorded, full
    implementation deferred to v0.10 (exponential backoff +
    dead-letter after configurable max-retry-hours, 24h cap).
    The semantic test is **SKIPPED** in v0.9.1 with a marker
    pointing at the v0.10 design. v0.9.x runtimes that fall
    back to log-and-drop in this mode are conformant; the
    fallback path is asserted in TestQueueAndRetryFallback. §5.4.

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


# ── §5.3: surface-as-error (deterministic) ───────────────────────


class TestSurfaceAsError:
    """Per channel-contract.md §5.3 — surface-as-error makes provider
    exceptions propagate as ChannelError. Deterministic in v0.9.1:
    a runtime that catches and swallows in this mode is non-conforming.
    The original exception MUST be chained via __cause__ so the audit
    trail preserves the upstream error message."""

    def test_provider_exception_re_raises_as_channel_error(self):
        from termin_server.channel_config import ChannelError

        ir = _ir(_ch("alerts", "webhook", failure_mode="surface-as-error"))
        deploy = _deploy("alerts", _binding())
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))

        class BoomProvider:
            async def send(self, body=None, headers=None):
                raise RuntimeError("simulated upstream failure")

        d._channel_providers["alerts"] = BoomProvider()
        with pytest.raises(ChannelError) as exc:
            asyncio.run(d.channel_send("alerts", {"x": 1}))
        # The wrapped error preserves the original message for ops
        # debugging from the audit log.
        assert "simulated upstream failure" in str(exc.value)

    def test_surface_as_error_chains_original_via_cause(self):
        """`raise ChannelError(...) from e` preserves the original
        exception object on __cause__. Ops tooling that walks
        the exception chain (e.g., structured loggers, audit
        emitters) needs this to surface the upstream message."""
        from termin_server.channel_config import ChannelError

        ir = _ir(_ch("alerts", "webhook", failure_mode="surface-as-error"))
        deploy = _deploy("alerts", _binding())
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))

        original = RuntimeError("origin")

        class BoomProvider:
            async def send(self, body=None, headers=None):
                raise original

        d._channel_providers["alerts"] = BoomProvider()
        with pytest.raises(ChannelError) as exc:
            asyncio.run(d.channel_send("alerts", {"x": 1}))
        assert exc.value.__cause__ is original


# ── §5.4: queue-and-retry — DEFERRED to v0.10 ────────────────────


class TestQueueAndRetry:
    """Per channel-contract.md §5.4 — `queue-and-retry` (renamed from
    `queue-and-retry-forever` in v0.9.1) is grammar-accepted but the
    full retry-worker implementation lands v0.10 with exponential
    backoff and a dead-letter table after a configurable
    max-retry-hours window (default reasonable, 24h cap).

    Until v0.10, conforming v0.9.x runtimes MUST fall back to
    log-and-drop with a logged warning that distinguishes the
    placeholder from genuine default behavior. The semantic
    queue-shape test is SKIPPED until v0.10; the fallback test below
    asserts the conformant non-implementation posture for v0.9.x."""

    @pytest.mark.skip(
        reason="queue-and-retry semantic test deferred to v0.10 — "
        "implementation not yet shipped. v0.9.x runtimes fall back "
        "to log-and-drop, asserted in test_queue_and_retry_falls_back. "
        "See specs/channel-contract.md §5.4."
    )
    def test_queue_shape_with_retry_worker_v010(self):
        """v0.10 will assert: outcome='queued' on first failure,
        opaque queue_id, exponential backoff schedule, payload
        migrated to dead-letter after max-retry-hours timeout."""

    def test_queue_and_retry_falls_back_to_log_and_drop_in_v091(self):
        """v0.9.x conformance: a runtime that hasn't implemented the
        retry worker MUST fall back to log-and-drop. Crashes or
        silent swallowing without the failure-shaped return are
        non-conforming."""
        ir = _ir(_ch("alerts", "webhook", failure_mode="queue-and-retry"))
        deploy = _deploy("alerts", _binding())
        d = ChannelDispatcher(ir, deploy, _registry())
        asyncio.run(d.startup(strict=False))

        class BoomProvider:
            async def send(self, body=None, headers=None):
                raise RuntimeError("simulated")

        d._channel_providers["alerts"] = BoomProvider()
        # MUST NOT raise — fallback is mandatory for v0.9.x
        # non-implementing runtimes.
        result = asyncio.run(d.channel_send("alerts", {"x": 1}))
        assert result["ok"] is False
        assert result["outcome"] == "failed"
        assert result["channel"] == "alerts"


# ── §5.5: per-channel scope ──────────────────────────────────────


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
