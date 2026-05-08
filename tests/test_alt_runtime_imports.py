# Copyright 2026 Jamie-Leigh Blake and Termin project contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Item 10 of v0.9.3 — alt-runtime import-stability conformance pack.

The whole point of v0.9.3 is to make alt-runtime dependence on
`termin-core` viable. This test pack pins the alt-runtime-facing
public surface of `termin-core` so an inadvertent rename or
relocation in a later release fails conformance loudly.

These tests are **import-only** — they don't exercise the runtime,
they just assert that every public name an alt runtime depends on
is importable from the documented namespace. If a symbol moves,
the import fails immediately and the test catches the regression.

Coverage areas (one section each):

  1. Runtime infrastructure — events, scheduler, transaction,
     reflection (moved from termin-server in v0.9.3 item 5).
  2. Security + accessibility — boundaries, markdown_sanitizer,
     colorblind (item 6).
  3. IR migrations — classifier, validate, introspect, ack, errors
     (item 7).
  4. Channel dispatch — channels, channel_config, channel_ws
     (item 8).
  5. Expression / page composition — build_compute_js,
     extract_page_reqs (items 1 + 4).
  6. HTTP routing surface — TerminRequest/Response, RouteSpec,
     per-class handlers, build_route_specs, dispatch_http_request,
     append_to_field (item 2).
  7. Compute orchestration — ComputeDispatcher Protocols (already
     in core), materialize helpers (item 3).
  8. Provider Protocols — the contract surfaces (already in core
     pre-v0.9.3; pinned here for completeness).
  9. Anti-shim guard — assert no `termin_server.X` re-export shim
     exists for the modules in scope. Catches a future slip-up
     where someone adds a shim back "for compatibility" — pre-v1.0
     policy says no shims.

If any assertion in this file fires, an alt-runtime build that
depends on the pinned name has just broken. Bump the dependency
contract in CHANGELOG and add a migration note before releasing.
"""

from __future__ import annotations

import importlib

import pytest


# ── 1. Runtime infrastructure (item 5) ──

def test_events_eventbus_importable_from_core():
    from termin_core.events import EventBus
    assert callable(EventBus)


def test_scheduler_importable_from_core():
    from termin_core.scheduler import Scheduler, parse_schedule_interval
    assert callable(Scheduler)
    assert callable(parse_schedule_interval)


def test_transaction_importable_from_core():
    from termin_core.transaction import (
        Transaction, ContentSnapshot, StagedWrite,
    )
    assert callable(Transaction)
    assert callable(ContentSnapshot)
    assert callable(StagedWrite)


def test_reflection_engine_importable_from_core():
    from termin_core.reflection import (
        ReflectionEngine, register_reflection_with_expr_eval,
    )
    assert callable(ReflectionEngine)
    assert callable(register_reflection_with_expr_eval)


# ── 2. Security + accessibility (item 6) ──

def test_boundaries_importable_from_core():
    from termin_core.boundaries import (
        build_boundary_maps,
        check_boundary_access,
        check_boundary_identity,
    )
    assert callable(build_boundary_maps)
    assert callable(check_boundary_access)
    assert callable(check_boundary_identity)


def test_markdown_sanitizer_importable_from_core():
    from termin_core.presentation.markdown_sanitizer import sanitize_markdown
    assert callable(sanitize_markdown)
    # Functional smoke: it does sanitize.
    out = sanitize_markdown("**hello**")
    assert "<strong>" in out


def test_colorblind_importable_from_core():
    from termin_core.colorblind import (
        contrast_ratio, simulate_cvd, relative_luminance,
        cvd_distinguishable, hex_to_rgb,
    )
    assert callable(contrast_ratio)
    assert callable(simulate_cvd)


# ── 3. IR migrations (item 7) ──

def test_migrations_top_level_importable_from_core():
    from termin_core.migrations import (
        compute_migration_diff, apply_rename_mappings,
        downgrade_for_empty_tables, ack_covers,
        format_blocked_error, format_unacked_error,
    )
    assert callable(compute_migration_diff)


def test_migrations_classifier_importable_from_core():
    from termin_core.migrations.classifier import (
        classify_field_change, compute_migration_diff,
    )
    assert callable(classify_field_change)
    assert callable(compute_migration_diff)


def test_migrations_introspect_importable_from_core():
    from termin_core.migrations.introspect import introspect_sqlite_schema
    assert callable(introspect_sqlite_schema)


def test_migrations_ack_importable_from_core():
    from termin_core.migrations.ack import (
        ack_covers, missing_acks, collect_required_fingerprints,
    )
    assert callable(ack_covers)


def test_migrations_errors_importable_from_core():
    from termin_core.migrations.errors import (
        MigrationBlockedError, MigrationAckRequiredError,
        MigrationBackupRefusedError,
    )
    assert issubclass(MigrationBlockedError, Exception)


# ── 4. Channel dispatch (item 8) ──

def test_channels_importable_from_core():
    from termin_core.channels import (
        ChannelDispatcher, load_deploy_config, check_deploy_config_warnings,
    )
    assert callable(ChannelDispatcher)


def test_channel_config_importable_from_core():
    from termin_core.channel_config import (
        ChannelConfig, ChannelError, ChannelConfigError,
        ChannelScopeError, ChannelValidationError,
        ChannelAuthConfig, validate_channel_config,
    )
    assert callable(ChannelConfig)
    assert issubclass(ChannelError, Exception)


def test_channel_ws_importable_from_core():
    from termin_core.channel_ws import WebSocketConnection
    assert callable(WebSocketConnection)


# ── 5. Expression + page composition (items 1 + 4) ──

def test_build_compute_js_importable_from_core():
    from termin_core.expression.compute_js import build_compute_js
    assert callable(build_compute_js)
    # Functional smoke: empty IR → empty string.
    assert build_compute_js({"computes": []}) == ""


def test_extract_page_reqs_importable_from_core():
    from termin_core.presentation.compose import extract_page_reqs
    assert callable(extract_page_reqs)
    # Functional smoke: shape is a dict with the documented keys.
    out = extract_page_reqs({"children": []})
    assert set(out.keys()) >= {
        "sources", "form_target", "ref_lists",
        "create_as", "unique_fields", "after_save",
    }


# ── 6. HTTP routing surface (item 2) ──

def test_routing_value_types_importable_from_core():
    from termin_core.routing import (
        TerminRequest, TerminResponse, AuthContext,
        build_the_user_for_cel, RouteSpec, WebSocketRouteSpec,
    )
    assert callable(TerminRequest)
    assert callable(TerminResponse)


def test_routing_crud_handlers_importable_from_core():
    from termin_core.routing import (
        create_content_handler, delete_content_handler,
        get_content_handler, list_content_handler,
        transition_content_handler, update_content_handler,
    )
    assert callable(create_content_handler)
    assert callable(list_content_handler)


def test_routing_channel_handlers_importable_from_core():
    from termin_core.routing import (
        channel_send_handler, invoke_channel_action_handler,
        webhook_receive_handler,
    )
    assert callable(channel_send_handler)


def test_routing_compute_handler_importable_from_core():
    from termin_core.routing import trigger_compute_handler
    assert callable(trigger_compute_handler)


def test_routing_websocket_dispatch_importable_from_core():
    from termin_core.routing import (
        TerminWebSocket, dispatch_websocket_session,
        ConnectionManager, filter_owned_rows,
    )
    assert callable(dispatch_websocket_session)
    assert callable(ConnectionManager)


def test_routing_append_handler_importable_from_core():
    from termin_core.routing import (
        append_to_field, AppendValidationError, AppendNotFoundError,
        CANONICAL_KINDS,
    )
    assert callable(append_to_field)
    assert issubclass(AppendValidationError, Exception)
    assert "user" in CANONICAL_KINDS
    assert "agent" in CANONICAL_KINDS


def test_routing_dispatch_importable_from_core():
    from termin_core.routing import build_route_specs, dispatch_http_request
    assert callable(build_route_specs)
    assert callable(dispatch_http_request)


# ── 7. Compute orchestration (item 3) ──

def test_compute_protocols_importable_from_core():
    from termin_core.providers.compute_contract import (
        DefaultCelComputeProvider, LlmComputeProvider,
        AiAgentComputeProvider,
        ToolSurface, AgentContext, AgentResult, AuditRecord,
        CompletionResult, ConversationContext,
    )
    # Protocols don't have callable() True for the class, but they're
    # importable, that's what we're checking.
    assert DefaultCelComputeProvider is not None
    assert LlmComputeProvider is not None
    assert AiAgentComputeProvider is not None


def test_compute_materialize_helpers_importable_from_core():
    from termin_core.compute import (
        materialize_to_anthropic, build_invokable_compute_tools,
        build_output_tool, build_agent_tools,
        ConversationMaterializationError,
        entry_role, build_content_blocks,
        truncate_purpose, purpose_property, add_purpose_to_tool,
        CANONICAL_KINDS_USER_ROLE, CANONICAL_KINDS_ASSISTANT_ROLE,
        PURPOSE_MAX_WORDS, PURPOSE_TOOL_DESCRIPTION,
    )
    assert callable(materialize_to_anthropic)
    assert "user" in CANONICAL_KINDS_USER_ROLE
    assert "agent" in CANONICAL_KINDS_ASSISTANT_ROLE
    # Functional smoke: empty entries → empty messages.
    assert materialize_to_anthropic([]) == []


def test_compute_materialize_round_trip_smoke():
    from termin_core.compute import materialize_to_anthropic
    msgs = materialize_to_anthropic([
        {"kind": "user", "body": "Hello"},
        {"kind": "agent", "body": "Hi there"},
    ])
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"  # 'agent' maps to 'assistant'


# ── 8. Provider Protocols (already in core pre-v0.9.3) ──

def test_provider_registries_importable_from_core():
    from termin_core.providers import (
        Category, ProviderRegistry, ContractRegistry,
        initial_deploy_diff,
    )
    assert hasattr(Category, "STORAGE")
    assert callable(ProviderRegistry)


def test_provider_contracts_importable_from_core():
    from termin_core.providers.storage_contract import (
        StorageProvider, QueryOptions, Page, Eq, And, Or,
    )
    from termin_core.providers.identity_contract import (
        IdentityProvider, Principal,
    )
    from termin_core.providers.channel_contract import (
        WebhookChannelProvider,
    )
    from termin_core.providers.presentation_contract import (
        PresentationProvider, Redacted, PrincipalContext,
        PresentationData, PRESENTATION_BASE_CONTRACTS,
    )
    assert StorageProvider is not None
    assert IdentityProvider is not None
    assert WebhookChannelProvider is not None
    assert PresentationProvider is not None
    assert "page" in PRESENTATION_BASE_CONTRACTS


# ── 9. Anti-shim guard ──

@pytest.mark.parametrize("module_name", [
    "termin_server.events",
    "termin_server.scheduler",
    "termin_server.transaction",
    "termin_server.reflection",
    "termin_server.boundaries",
    "termin_server.colorblind",
    "termin_server.markdown_sanitizer",
    "termin_server.channels",
    "termin_server.channel_config",
    "termin_server.channel_ws",
    "termin_server.migrations",
    "termin_server.errors",
    "termin_server.state",
    "termin_server.validation",
    "termin_server.expression",
    "termin_server.confidentiality",
    "termin_server.cel_predicate",
    "termin_server.providers.binding",
    "termin_server.providers.contracts",
    "termin_server.providers.deploy_config",
    "termin_server.providers.registry",
    "termin_server.providers.storage_contract",
    "termin_server.providers.identity_contract",
    "termin_server.providers.channel_contract",
    "termin_server.providers.compute_contract",
    "termin_server.providers.presentation_contract",
])
def test_no_termin_server_shim_for_moved_module(module_name: str):
    """Pre-v1.0 policy: no termin-server shim layer for code that
    moved to termin-core in v0.9.3 (or earlier). If someone adds a
    shim back "for compatibility," this test fires.
    """
    with pytest.raises(ImportError):
        importlib.import_module(module_name)
