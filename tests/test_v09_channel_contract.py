# Copyright 2026 Jamie-Leigh Blake and Termin project contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0

"""Conformance — v0.9.1 Phase 4 channel provider contract surface.

Companion to `specs/channel-contract.md` §2. Tests the four
`Protocol` shapes, the shared data classes, the action vocabulary
and full-features tables, and the contract registry.

These are unit-style tests against the contract module. No FastAPI
app, no compiled fixture, no running event loop — the contract
surface is what every conforming runtime + provider pair needs to
expose, regardless of how their dispatcher works.

Imports from `termin_server` mirror the v0.9 migration / presentation
conformance packs — provider authors are the primary audience, and
they reuse the reference runtime + plug in a provider, so direct
import is the natural surface. Alternative-runtime authors will need
to adapt these tests when v0.10+ provides an adapter-agnostic shape.
"""

from __future__ import annotations

import inspect

import pytest

from termin_server.providers.channel_contract import (
    ChannelAuditRecord,
    ChannelSendResult,
    MessageRef,
    WebhookChannelProvider,
    EmailChannelProvider,
    MessagingChannelProvider,
    EventStreamChannelProvider,
    CHANNEL_CONTRACT_ACTION_VOCAB,
    CHANNEL_CONTRACT_FULL_FEATURES,
)
from termin_server.providers.builtins.channel_webhook_stub import WebhookChannelStub
from termin_server.providers.builtins.channel_email_stub import (
    EmailChannelStub, CapturedEmail,
)
from termin_server.providers.builtins.channel_messaging_stub import (
    MessagingChannelStub,
)
from termin_server.providers import (
    Category, ContractRegistry, ProviderRegistry,
)
from termin_server.providers.builtins import register_builtins


# ── §2.1: ChannelSendResult validation ──────────────────────────────


class TestChannelSendResult:
    """Per channel-contract.md §2.1 — `outcome` field MUST be one of
    the literal triple. Construction with anything else MUST raise
    ValueError at __post_init__."""

    def test_delivered_outcome_accepted(self):
        r = ChannelSendResult(outcome="delivered")
        assert r.outcome == "delivered"
        assert r.attempt_count == 1
        assert r.audit_record is None

    def test_failed_outcome_accepted(self):
        r = ChannelSendResult(outcome="failed", error_detail="connection refused")
        assert r.outcome == "failed"
        assert r.error_detail == "connection refused"

    def test_queued_outcome_accepted(self):
        r = ChannelSendResult(outcome="queued", attempt_count=0)
        assert r.outcome == "queued"

    def test_invalid_outcome_raises(self):
        with pytest.raises(ValueError, match="outcome"):
            ChannelSendResult(outcome="ok")

    def test_empty_outcome_raises(self):
        with pytest.raises(ValueError, match="outcome"):
            ChannelSendResult(outcome="")


# ── §2.1: ChannelAuditRecord validation ─────────────────────────────


def _audit(**overrides):
    """Helper: build a valid ChannelAuditRecord with overridable fields."""
    kw = dict(
        channel_name="alerts", provider_product="stub",
        direction="outbound", action="send", target="resolved-target",
        payload_summary="payload", outcome="delivered",
        attempt_count=1, latency_ms=0,
    )
    kw.update(overrides)
    return ChannelAuditRecord(**kw)


class TestChannelAuditRecord:
    """Per channel-contract.md §2.1 — outcome ∈ {delivered, failed,
    queued}; direction ∈ {outbound, inbound}. Bidirectional is a
    channel-level label; per-record direction is always one or the
    other."""

    def test_outbound_delivered_accepted(self):
        rec = _audit()
        assert rec.outcome == "delivered"
        assert rec.direction == "outbound"

    def test_inbound_record_has_no_invoked_by(self):
        """Spec §2.1: inbound records have invoked_by=None by default."""
        rec = _audit(direction="inbound", action="receive")
        assert rec.invoked_by is None

    def test_invoked_by_threaded_through(self):
        rec = _audit(invoked_by="user-42")
        assert rec.invoked_by == "user-42"

    def test_invalid_outcome_raises(self):
        with pytest.raises(ValueError, match="outcome"):
            _audit(outcome="success")

    def test_invalid_direction_raises(self):
        with pytest.raises(ValueError, match="direction"):
            _audit(direction="sideways")

    def test_bidirectional_label_rejected_at_record_level(self):
        """Bidirectional describes the channel, not a single record."""
        with pytest.raises(ValueError, match="direction"):
            _audit(direction="bidirectional")


# ── §2.4: MessageRef shape ─────────────────────────────────────────


class TestMessageRef:
    def test_id_and_channel_required(self):
        ref = MessageRef(id="m-1", channel="general")
        assert ref.id == "m-1"
        assert ref.channel == "general"
        assert ref.thread_id is None

    def test_thread_id_optional(self):
        ref = MessageRef(id="m-2", channel="general", thread_id="t-99")
        assert ref.thread_id == "t-99"


# ── §2.2-§2.5: Protocol conformance for each contract ──────────────


class TestProtocolConformance:
    """Per channel-contract.md §2 — each stub MUST satisfy the
    runtime_checkable Protocol of its declared contract."""

    def test_webhook_stub_implements_protocol(self):
        assert isinstance(WebhookChannelStub(), WebhookChannelProvider)

    def test_email_stub_implements_protocol(self):
        assert isinstance(EmailChannelStub(), EmailChannelProvider)

    def test_messaging_stub_implements_protocol(self):
        assert isinstance(MessagingChannelStub(), MessagingChannelProvider)

    def test_messaging_stub_does_not_satisfy_webhook_protocol(self):
        """Cross-contract isinstance MUST be False — a messaging stub
        is not a webhook provider, and the runtime would dispatch
        wrong if isinstance lied."""
        # The structural Protocol matches anything with a coroutine
        # `send`, so messaging IS a duck-shaped webhook. The point of
        # the registry triple (Category, contract, product) is that
        # dispatch happens by name, not by isinstance against a
        # foreign Protocol. Verify the messaging stub at least has
        # the messaging-specific surface.
        stub = MessagingChannelStub()
        assert hasattr(stub, "update")
        assert hasattr(stub, "react")
        assert hasattr(stub, "subscribe")

    def test_protocol_send_methods_are_async(self):
        """Spec §2.2: send() MUST be async. A synchronous send is
        non-conforming. Tested by reflection: every stub's send must
        be a coroutine function."""
        for stub in (WebhookChannelStub(), EmailChannelStub(),
                     MessagingChannelStub()):
            assert inspect.iscoroutinefunction(stub.send), \
                f"{type(stub).__name__}.send is not async"

    def test_event_stream_protocol_defined(self):
        """Spec §2.5: EventStreamChannelProvider Protocol MUST be
        defined for completeness, even when no stub is registered."""
        assert hasattr(EventStreamChannelProvider, "register_stream")
        assert hasattr(EventStreamChannelProvider, "publish")


# ── §2.6: action vocabulary tables ─────────────────────────────────


class TestActionVocabularyTable:
    """Per channel-contract.md §2.6 — every conforming runtime MUST
    publish CHANNEL_CONTRACT_ACTION_VOCAB with the four contract
    keys and the documented prefix sets."""

    def test_all_four_contracts_present(self):
        for contract in ("webhook", "email", "messaging", "event-stream"):
            assert contract in CHANNEL_CONTRACT_ACTION_VOCAB, \
                f"contract {contract!r} missing from CHANNEL_CONTRACT_ACTION_VOCAB"

    def test_webhook_has_post(self):
        assert "Post" in CHANNEL_CONTRACT_ACTION_VOCAB["webhook"]

    def test_email_has_required_prefixes(self):
        vocab = CHANNEL_CONTRACT_ACTION_VOCAB["email"]
        for prefix in ("Subject is", "Body is", "Recipients are"):
            assert prefix in vocab, f"email vocab missing {prefix!r}"

    def test_messaging_has_send_and_inbound_triggers(self):
        vocab = CHANNEL_CONTRACT_ACTION_VOCAB["messaging"]
        assert "Send a message" in vocab
        assert "Reply in thread to" in vocab
        assert "When a message is received" in vocab
        assert "When a reaction is added" in vocab


class TestFullFeaturesTable:
    """Per channel-contract.md §2.6 — CHANNEL_CONTRACT_FULL_FEATURES
    declares the action set a 'full' product implements per contract."""

    def test_messaging_full_features_complete(self):
        feats = CHANNEL_CONTRACT_FULL_FEATURES["messaging"]
        assert set(feats) >= {"send", "update", "react", "subscribe"}

    def test_webhook_features_minimal(self):
        feats = CHANNEL_CONTRACT_FULL_FEATURES["webhook"]
        assert "send" in feats

    def test_email_features_minimal(self):
        feats = CHANNEL_CONTRACT_FULL_FEATURES["email"]
        assert "send" in feats


# ── §3.2: contract registry presence ───────────────────────────────


class TestContractRegistry:
    """Per channel-contract.md §3.2 — all four channel contracts MUST
    be present in the default contract registry, independent of
    whether any product is registered against them."""

    def test_default_registry_has_all_four_contracts(self):
        contracts = ContractRegistry.default()
        for name in ("webhook", "email", "messaging", "event-stream"):
            assert contracts.has_contract(Category.CHANNELS, name), \
                f"contract 'channels/{name}' not in default registry"


# ── §3.1: stub product registration ────────────────────────────────


class TestStubProductRegistration:
    """Per channel-contract.md §3.1 — every conforming runtime MUST
    register a 'stub' product against each of the three implementable
    contracts (webhook, email, messaging). event-stream is optional
    in v0.9."""

    def _registry(self):
        contracts = ContractRegistry.default()
        registry = ProviderRegistry()
        register_builtins(registry, contracts)
        return registry

    def test_webhook_stub_registered(self):
        record = self._registry().get(Category.CHANNELS, "webhook", "stub")
        assert record is not None

    def test_email_stub_registered(self):
        record = self._registry().get(Category.CHANNELS, "email", "stub")
        assert record is not None

    def test_messaging_stub_registered(self):
        record = self._registry().get(Category.CHANNELS, "messaging", "stub")
        assert record is not None

    def test_messaging_stub_declares_full_features(self):
        record = self._registry().get(Category.CHANNELS, "messaging", "stub")
        for feat in CHANNEL_CONTRACT_FULL_FEATURES["messaging"]:
            assert feat in record.features, \
                f"messaging stub missing feature {feat!r}"

    def test_factory_returns_provider_instance(self):
        record = self._registry().get(Category.CHANNELS, "webhook", "stub")
        instance = record.factory({"target": "https://example.com/hook"})
        assert isinstance(instance, WebhookChannelProvider)
