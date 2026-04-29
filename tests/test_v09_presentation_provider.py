# Copyright 2026 Jamie-Leigh Blake and Termin project contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0

"""Conformance — v0.9 Phase 5 presentation provider system.

Companion to `specs/presentation-contract.md`. The presentation
contract has three concerns:

  * The provider Protocol shape (§2) — declared_contracts,
    render_modes, render_ssr, csr_bundle_url.
  * Binding resolution (§3) — namespace expansion, per-contract
    override, instance caching, default-Tailwind synthesis,
    unknown-product/namespace fail-soft.
  * Contract package loading (§4) — YAML format, verb collision,
    deploy-config wiring, fail-closed semantics.

Per the conformance suite philosophy (`CLAUDE.md`): "the conformance
suite is the spec." If a behavior isn't tested here, it isn't
specified. Provider authors and alternative-runtime authors MUST
satisfy these tests.

Imports from termin_runtime / termin directly mirror the migration
conformance pack — provider authors are the primary audience and
they reuse the reference runtime + plug in a provider, so direct
import is the natural surface. Alternative-runtime authors will
need to adapt these tests when v0.10+ provides an adapter-agnostic
shape; see `specs/presentation-contract.md` §6 for the v0.9 framing.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any, Mapping, Optional
from unittest.mock import MagicMock

import pytest


# ── Fixtures ──

class _Ctx:
    """Minimal context shape used by the binding-resolution tests."""

    def __init__(self, contract_package_registry=None) -> None:
        self.presentation_providers: list = []
        self.contract_package_registry = contract_package_registry


def _fake_provider_registry(
    product_name: str = "fake",
    contract_names: tuple[str, ...] = (),
    render_modes: tuple[str, ...] = ("ssr",),
):
    """Build a ProviderRegistry with one factory registered against
    the given contracts under `product_name`. The factory returns a
    new MagicMock each call so caching tests can count instances.
    """
    from termin_runtime.providers import (
        Category, ContractRegistry, ProviderRegistry,
    )
    contracts = ContractRegistry.default()
    registry = ProviderRegistry()
    instances: list = []

    def factory(config):
        prov = MagicMock(name=f"{product_name}-instance")
        prov.declared_contracts = contract_names
        prov.render_modes = render_modes
        prov._config_seen = config
        instances.append(prov)
        return prov

    for c in contract_names:
        registry.register(Category.PRESENTATION, c, product_name, factory)
    return registry, contracts, instances


def _presentation_base_contracts() -> tuple[str, ...]:
    from termin_runtime.providers.presentation_contract import (
        PRESENTATION_BASE_CONTRACTS,
    )
    return tuple(f"presentation-base.{n}" for n in PRESENTATION_BASE_CONTRACTS)


# ── §2: Provider Protocol shape ──

def test_presentation_provider_protocol_runtime_checkable():
    """A simple object with declared_contracts + render_modes +
    render_ssr + csr_bundle_url MUST satisfy isinstance against
    PresentationProvider Protocol."""
    from termin_runtime.providers.presentation_contract import (
        PresentationProvider,
    )

    class _Impl:
        declared_contracts = ("presentation-base.text",)
        render_modes = ("ssr",)

        def render_ssr(self, contract, ir_fragment, data, principal_context):
            return ""

        def csr_bundle_url(self):
            return None

    assert isinstance(_Impl(), PresentationProvider)


def test_presentation_base_namespace_has_ten_contracts():
    """BRD #2 §5.1 closes the presentation-base namespace at ten
    contracts — page, text, markdown, data-table, form, chat, metric,
    nav-bar, toast, banner. Conforming runtimes MUST recognize all
    ten."""
    from termin_runtime.providers.presentation_contract import (
        PRESENTATION_BASE_CONTRACTS,
    )
    expected = {
        "page", "text", "markdown", "data-table", "form",
        "chat", "metric", "nav-bar", "toast", "banner",
    }
    assert set(PRESENTATION_BASE_CONTRACTS) == expected


def test_redacted_sentinel_distinct_from_none_and_empty():
    """Field-level redaction marker (BRD §7.6) MUST be a distinct
    sentinel — providers must be able to discriminate redaction from
    natural absence (None / "" / 0 / False)."""
    from termin_runtime.providers.presentation_contract import (
        Redacted, is_redacted,
    )
    r = Redacted(field_name="ssn", expected_type="text")
    assert is_redacted(r)
    assert not is_redacted(None)
    assert not is_redacted("")
    assert not is_redacted(0)
    assert not is_redacted(False)


def test_redacted_json_default_produces_wire_shape():
    """Per BRD §7.6, the JSON encoding of a Redacted MUST carry a
    `__redacted: true` discriminator so CSR providers can detect it
    over the wire without inspecting Python type tags."""
    import json
    from termin_runtime.providers.presentation_contract import (
        Redacted, redacted_json_default,
    )
    r = Redacted(field_name="salary", expected_type="currency", reason="hr.salary")
    encoded = json.loads(json.dumps(r, default=redacted_json_default))
    assert encoded["__redacted"] is True
    assert encoded["field"] == "salary"
    assert encoded["expected_type"] == "currency"
    assert encoded["reason"] == "hr.salary"


# ── §3: Binding resolution ──

def test_namespace_binding_fans_out_to_all_contracts():
    """A `presentation-base` namespace binding MUST emit one triple
    per contract in the namespace."""
    from termin_runtime.app import _populate_presentation_providers
    base = _presentation_base_contracts()
    registry, contracts, _ = _fake_provider_registry("test", base)
    ctx = _Ctx()
    _populate_presentation_providers(
        ctx,
        {"bindings": {"presentation": {
            "presentation-base": {"provider": "test", "config": {}},
        }}},
        registry, contracts,
    )
    bound = {c for c, _, _ in ctx.presentation_providers}
    assert bound == set(base)


def test_per_contract_binding_does_not_fan_out():
    """A binding keyed on a fully-qualified contract name MUST target
    exactly that contract — no namespace expansion."""
    from termin_runtime.app import _populate_presentation_providers
    base = _presentation_base_contracts()
    registry, contracts, _ = _fake_provider_registry("test", base)
    ctx = _Ctx()
    _populate_presentation_providers(
        ctx,
        {"bindings": {"presentation": {
            "presentation-base.text": {"provider": "test", "config": {}},
        }}},
        registry, contracts,
    )
    bound = [c for c, _, _ in ctx.presentation_providers]
    assert bound == ["presentation-base.text"]


def test_per_contract_binding_wins_over_namespace_binding():
    """When both a namespace binding and a per-contract binding apply,
    the per-contract one MUST win."""
    from termin_runtime.app import _populate_presentation_providers
    base = _presentation_base_contracts()
    registry, contracts, _ = _fake_provider_registry("default", base)
    # Add a second product registered for just one contract.
    second_registry, _, _ = _fake_provider_registry(
        "override", ("presentation-base.text",)
    )
    # Merge: copy the override factory into the original registry.
    for record in second_registry.all_records():
        registry.register(
            record.category, record.contract_name,
            record.product_name, record.factory,
        )
    ctx = _Ctx()
    _populate_presentation_providers(
        ctx,
        {"bindings": {"presentation": {
            "presentation-base": {"provider": "default", "config": {}},
            "presentation-base.text": {"provider": "override", "config": {}},
        }}},
        registry, contracts,
    )
    by_contract = {c: p for c, p, _ in ctx.presentation_providers}
    assert by_contract["presentation-base.text"] == "override"
    assert by_contract["presentation-base.page"] == "default"


def test_factory_called_once_per_product_across_namespace():
    """A factory invoked for product P MUST be called exactly once
    across the fan-out. The single instance binds to every contract
    in the namespace."""
    from termin_runtime.app import _populate_presentation_providers
    base = _presentation_base_contracts()
    registry, contracts, instances = _fake_provider_registry("test", base)
    ctx = _Ctx()
    _populate_presentation_providers(
        ctx,
        {"bindings": {"presentation": {
            "presentation-base": {"provider": "test", "config": {}},
        }}},
        registry, contracts,
    )
    assert len(instances) == 1
    instance_ids = {id(p) for _, _, p in ctx.presentation_providers}
    assert instance_ids == {id(instances[0])}


def test_factory_receives_config_dict():
    """The factory invocation MUST receive the deploy config's
    `config` sub-dict so providers can read their per-deploy
    configuration (theme overrides, bundle URL overrides, etc.)."""
    from termin_runtime.app import _populate_presentation_providers
    base = _presentation_base_contracts()
    registry, contracts, instances = _fake_provider_registry("test", base)
    ctx = _Ctx()
    _populate_presentation_providers(
        ctx,
        {"bindings": {"presentation": {
            "presentation-base": {"provider": "test", "config": {
                "theme_default": "dark", "bundle_url_override": "/cdn/bundle.js",
            }}
        }}},
        registry, contracts,
    )
    assert instances[0]._config_seen == {
        "theme_default": "dark",
        "bundle_url_override": "/cdn/bundle.js",
    }


def test_alternate_top_level_shape_accepted():
    """Both `bindings.presentation.<key>` and
    `presentation.bindings.<key>` MUST be accepted."""
    from termin_runtime.app import _populate_presentation_providers
    base = _presentation_base_contracts()
    registry, contracts, _ = _fake_provider_registry("test", base)
    ctx = _Ctx()
    _populate_presentation_providers(
        ctx,
        {"presentation": {"bindings": {
            "presentation-base": {"provider": "test", "config": {}},
        }}},
        registry, contracts,
    )
    assert len(ctx.presentation_providers) == len(base)


def test_default_tailwind_synthesis_when_no_binding():
    """No presentation binding MUST synthesize a default
    `tailwind-default` binding for presentation-base."""
    from termin_runtime.app import _populate_presentation_providers
    from termin_runtime.providers import (
        Category, ContractRegistry, ProviderRegistry,
    )
    from termin_runtime.providers.builtins.presentation_tailwind_default import (
        register_tailwind_default,
    )
    contracts = ContractRegistry.default()
    registry = ProviderRegistry()
    register_tailwind_default(registry, contracts)

    ctx = _Ctx()
    _populate_presentation_providers(ctx, {}, registry, contracts)
    products = {p for _, _, p in [(c, p, i) for c, p, i in ctx.presentation_providers]}
    # Triples are (contract, product, instance) — extract products.
    products = {p for _, p, _ in ctx.presentation_providers}
    assert products == {"tailwind-default"}
    bound = {c for c, _, _ in ctx.presentation_providers}
    assert bound == set(_presentation_base_contracts())


def test_explicit_binding_overrides_default_synthesis():
    """An explicit binding to `presentation-base` MUST suppress the
    default-Tailwind synthesis."""
    from termin_runtime.app import _populate_presentation_providers
    base = _presentation_base_contracts()
    registry, contracts, _ = _fake_provider_registry("explicit", base)
    ctx = _Ctx()
    _populate_presentation_providers(
        ctx,
        {"bindings": {"presentation": {
            "presentation-base": {"provider": "explicit", "config": {}},
        }}},
        registry, contracts,
    )
    products = {p for _, p, _ in ctx.presentation_providers}
    assert products == {"explicit"}


def test_unknown_product_emits_no_triple():
    """A binding to a product nobody registered MUST NOT crash; the
    fan-out emits no triple. Deploy-time required_contracts
    validation is the fail-closed surface."""
    from termin_runtime.app import _populate_presentation_providers
    base = _presentation_base_contracts()
    registry, contracts, _ = _fake_provider_registry("real", base)
    ctx = _Ctx()
    _populate_presentation_providers(
        ctx,
        {"bindings": {"presentation": {
            "presentation-base": {"provider": "ghost", "config": {}},
        }}},
        registry, contracts,
    )
    assert ctx.presentation_providers == []


def test_unknown_namespace_emits_no_triple():
    """A namespace binding for a namespace no contract package
    declares MUST NOT crash; same fail-soft policy as unknown
    product."""
    from termin_runtime.app import _populate_presentation_providers
    base = _presentation_base_contracts()
    registry, contracts, _ = _fake_provider_registry("real", base)
    ctx = _Ctx(contract_package_registry=None)
    _populate_presentation_providers(
        ctx,
        {"bindings": {"presentation": {
            "ghost-namespace": {"provider": "real", "config": {}},
        }}},
        registry, contracts,
    )
    # No triple for the ghost namespace; the synthesis covers
    # presentation-base separately if no package binding existed.
    products = {p for _, p, _ in ctx.presentation_providers}
    assert "ghost-namespace" not in {c.split(".", 1)[0] for c, _, _ in ctx.presentation_providers}


def test_package_namespace_binding_fans_out_via_registry(tmp_path):
    """A namespace binding for a contract-package namespace MUST fan
    out to every contract the package declares — same shape as
    presentation-base, just sourced from the package registry."""
    from termin_runtime.app import _populate_presentation_providers
    from termin.contract_packages import (
        load_contract_packages_into_registry,
    )
    from termin_runtime.providers.contracts import (
        Category, ContractDefinition, Tier,
    )
    from termin_runtime.providers import (
        ContractRegistry, ProviderRegistry,
    )

    pkg_path = tmp_path / "demo.yaml"
    pkg_path.write_text(textwrap.dedent("""
        namespace: demo-pkg
        version: 0.1.0
        contracts:
          - name: alpha
            source-verb: "Show alpha for <ref>"
          - name: beta
            source-verb: "Show beta for <ref>"
    """).strip(), encoding="utf-8")
    pkg_registry = load_contract_packages_into_registry([pkg_path])

    contracts = ContractRegistry.default()
    for short in ("alpha", "beta"):
        contracts.register_contract(ContractDefinition(
            name=f"demo-pkg.{short}",
            category=Category.PRESENTATION,
            tier=Tier.TIER_2,
            naming="named",
            description="conformance test",
        ))
    provider_registry = ProviderRegistry()
    instances: list = []

    def factory(config):
        prov = MagicMock()
        instances.append(prov)
        return prov
    for short in ("alpha", "beta"):
        provider_registry.register(
            Category.PRESENTATION, f"demo-pkg.{short}",
            "demo-product", factory,
        )

    ctx = _Ctx(contract_package_registry=pkg_registry)
    _populate_presentation_providers(
        ctx,
        {"bindings": {"presentation": {
            "demo-pkg": {"provider": "demo-product", "config": {}},
        }}},
        provider_registry, contracts,
    )
    bound = {c for c, p, _ in ctx.presentation_providers if p == "demo-product"}
    assert bound == {"demo-pkg.alpha", "demo-pkg.beta"}
    assert len(instances) == 1


# ── §4: Contract package loading ──

def test_well_formed_package_loads_clean(tmp_path):
    from termin.contract_packages import load_contract_package
    pkg = tmp_path / "demo.yaml"
    pkg.write_text(textwrap.dedent("""
        namespace: demo-ns
        version: 0.1.0
        description: A demo package.
        contracts:
          - name: thing
            source-verb: "Show a thing of <ref>"
    """).strip(), encoding="utf-8")
    p = load_contract_package(pkg)
    assert p.namespace == "demo-ns"
    assert len(p.contracts) == 1
    assert p.contracts[0].source_verb == "Show a thing of <ref>"


def test_missing_namespace_raises(tmp_path):
    from termin.contract_packages import load_contract_package, ContractPackageError
    pkg = tmp_path / "demo.yaml"
    pkg.write_text(textwrap.dedent("""
        version: 0.1.0
        contracts: []
    """).strip(), encoding="utf-8")
    with pytest.raises(ContractPackageError, match="namespace"):
        load_contract_package(pkg)


def test_missing_version_raises(tmp_path):
    from termin.contract_packages import load_contract_package, ContractPackageError
    pkg = tmp_path / "demo.yaml"
    pkg.write_text(textwrap.dedent("""
        namespace: demo
        contracts: []
    """).strip(), encoding="utf-8")
    with pytest.raises(ContractPackageError, match="version"):
        load_contract_package(pkg)


def test_missing_source_verb_for_non_extends_raises(tmp_path):
    """Per BRD #2 §10.2, a non-extends contract MUST have a non-empty
    source-verb. Override-mode contracts (with `extends`) MAY omit it."""
    from termin.contract_packages import load_contract_package, ContractPackageError
    pkg = tmp_path / "demo.yaml"
    pkg.write_text(textwrap.dedent("""
        namespace: demo
        version: 0.1.0
        contracts:
          - name: orphan
    """).strip(), encoding="utf-8")
    with pytest.raises(ContractPackageError, match="source-verb"):
        load_contract_package(pkg)


def test_intra_package_verb_collision_raises(tmp_path):
    from termin.contract_packages import load_contract_package, ContractPackageError
    pkg = tmp_path / "demo.yaml"
    pkg.write_text(textwrap.dedent("""
        namespace: demo
        version: 0.1.0
        contracts:
          - name: a
            source-verb: "Show a thing of <ref>"
          - name: b
            source-verb: "Show a thing of <ref>"
    """).strip(), encoding="utf-8")
    with pytest.raises(ContractPackageError, match="duplicate"):
        load_contract_package(pkg)


def test_cross_package_verb_collision_names_both(tmp_path):
    """A collision across two loaded packages MUST name BOTH packages
    in the error message — operators need to identify which two are
    in conflict."""
    from termin.contract_packages import (
        load_contract_packages_into_registry, ContractPackageError,
    )
    a = tmp_path / "a.yaml"
    a.write_text(textwrap.dedent("""
        namespace: pkg-a
        version: 0.1.0
        contracts:
          - name: thing
            source-verb: "Show a colored item of <ref>"
    """).strip(), encoding="utf-8")
    b = tmp_path / "b.yaml"
    b.write_text(textwrap.dedent("""
        namespace: pkg-b
        version: 0.1.0
        contracts:
          - name: rival
            source-verb: "Show a colored item of <ref>"
    """).strip(), encoding="utf-8")
    with pytest.raises(ContractPackageError, match="Verb collision") as exc_info:
        load_contract_packages_into_registry([a, b])
    msg = str(exc_info.value)
    assert "pkg-a" in msg and "pkg-b" in msg


def test_extends_field_carried_through(tmp_path):
    """Override-mode contracts (`extends: <ns>.<contract>`) load
    cleanly; the extends pointer survives in the registry."""
    from termin.contract_packages import load_contract_package
    pkg = tmp_path / "demo.yaml"
    pkg.write_text(textwrap.dedent("""
        namespace: pretty-base
        version: 0.1.0
        contracts:
          - name: data-table
            extends: presentation-base.data-table
            modifiers:
              - "Sticky header"
    """).strip(), encoding="utf-8")
    p = load_contract_package(pkg)
    assert p.contracts[0].extends == "presentation-base.data-table"
    # Override-mode allows empty source-verb (drop-in).
    assert p.contracts[0].source_verb == ""


def test_registry_lookup_by_qualified_name(tmp_path):
    from termin.contract_packages import load_contract_packages_into_registry
    pkg = tmp_path / "demo.yaml"
    pkg.write_text(textwrap.dedent("""
        namespace: demo-ns
        version: 0.1.0
        contracts:
          - name: orb
            source-verb: "Show an orb of <ref>"
    """).strip(), encoding="utf-8")
    reg = load_contract_packages_into_registry([pkg])
    c = reg.get_contract("demo-ns.orb")
    assert c is not None
    assert c.name == "orb"
    assert reg.get_contract("demo-ns.absent") is None
    assert reg.get_contract("ghost-ns.thing") is None


def test_registry_collects_verbs_for_grammar_extension(tmp_path):
    """The registry MUST expose `source_verbs()` so the parser can
    extend its dispatch table at parse time per BRD §4.5."""
    from termin.contract_packages import load_contract_packages_into_registry
    a = tmp_path / "a.yaml"
    a.write_text(textwrap.dedent("""
        namespace: pkg-a
        version: 0.1.0
        contracts:
          - name: alpha
            source-verb: "Show alpha of <ref>"
    """).strip(), encoding="utf-8")
    b = tmp_path / "b.yaml"
    b.write_text(textwrap.dedent("""
        namespace: pkg-b
        version: 0.1.0
        contracts:
          - name: beta
            source-verb: "Show beta of <ref>"
    """).strip(), encoding="utf-8")
    reg = load_contract_packages_into_registry([a, b])
    assert set(reg.source_verbs()) == {
        "Show alpha of <ref>",
        "Show beta of <ref>",
    }


# ── §4 (deploy-config wiring): _load_contract_packages ──

def test_load_contract_packages_attaches_registry_to_ctx(tmp_path):
    """A deploy config declaring contract_packages MUST populate
    `ctx.contract_package_registry` at app startup."""
    from termin_runtime.app import _load_contract_packages
    pkg = tmp_path / "demo.yaml"
    pkg.write_text(textwrap.dedent("""
        namespace: demo-ns
        version: 0.1.0
        contracts:
          - name: x
            source-verb: "Show x of <ref>"
    """).strip(), encoding="utf-8")

    class _Ctx2:
        contract_package_registry = None

    ctx = _Ctx2()
    _load_contract_packages(ctx, {"contract_packages": [str(pkg)]})
    assert ctx.contract_package_registry is not None
    assert "demo-ns" in ctx.contract_package_registry.namespaces()


def test_load_contract_packages_no_field_is_noop():
    """An app declaring no contract_packages MUST be deployable with
    `ctx.contract_package_registry` left at None."""
    from termin_runtime.app import _load_contract_packages

    class _Ctx2:
        contract_package_registry = None

    ctx = _Ctx2()
    _load_contract_packages(ctx, {})
    assert ctx.contract_package_registry is None


def test_load_contract_packages_resolves_relative_to_deploy_path(tmp_path):
    """Paths in deploy config MUST resolve relative to the deploy
    file's parent directory — the natural authoring layout."""
    from termin_runtime.app import _load_contract_packages
    sub = tmp_path / "deploys"
    sub.mkdir()
    pkg_dir = sub / "contract_packages"
    pkg_dir.mkdir()
    (pkg_dir / "demo.yaml").write_text(textwrap.dedent("""
        namespace: rel-demo
        version: 0.1.0
        contracts:
          - name: x
            source-verb: "Show x of <ref>"
    """).strip(), encoding="utf-8")
    deploy = sub / "app.deploy.json"
    deploy.write_text("{}", encoding="utf-8")

    class _Ctx2:
        contract_package_registry = None

    ctx = _Ctx2()
    _load_contract_packages(ctx, {
        "_deploy_config_path": str(deploy),
        "contract_packages": ["contract_packages/demo.yaml"],
    })
    assert "rel-demo" in ctx.contract_package_registry.namespaces()


def test_load_contract_packages_fail_closed_on_missing_file(tmp_path):
    """Missing package file MUST fail at startup — `Using
    "<ns>.<contract>"` references in source would be unresolvable."""
    from termin_runtime.app import _load_contract_packages

    class _Ctx2:
        contract_package_registry = None

    with pytest.raises(RuntimeError, match="contract package"):
        _load_contract_packages(
            _Ctx2(), {"contract_packages": [str(tmp_path / "missing.yaml")]}
        )


def test_load_contract_packages_fail_closed_on_verb_collision(tmp_path):
    """Cross-package verb collision MUST fail at startup."""
    from termin_runtime.app import _load_contract_packages
    a = tmp_path / "a.yaml"
    a.write_text(textwrap.dedent("""
        namespace: a-ns
        version: 0.1.0
        contracts:
          - name: x
            source-verb: "Show common verb of <ref>"
    """).strip(), encoding="utf-8")
    b = tmp_path / "b.yaml"
    b.write_text(textwrap.dedent("""
        namespace: b-ns
        version: 0.1.0
        contracts:
          - name: y
            source-verb: "Show common verb of <ref>"
    """).strip(), encoding="utf-8")

    class _Ctx2:
        contract_package_registry = None

    with pytest.raises(RuntimeError, match="Verb collision"):
        _load_contract_packages(
            _Ctx2(), {"contract_packages": [str(a), str(b)]}
        )


def test_load_contract_packages_rejects_non_list_value():
    """Type validation: `contract_packages` MUST be a list, not a
    string. Defensive against deploy-config typos."""
    from termin_runtime.app import _load_contract_packages

    class _Ctx2:
        contract_package_registry = None

    with pytest.raises(RuntimeError, match="must be a list"):
        _load_contract_packages(_Ctx2(), {"contract_packages": "single.yaml"})


# ── §4: airlock-components fixture (BRD #2 §10.5 worked example) ──

_AIRLOCK_PKG_PATHS = [
    Path(__file__).parent.parent.parent / "termin-compiler" / "examples-dev" /
    "contract_packages" / "airlock-components.yaml",
    # Fallback: the conformance repo may copy the fixture in a future
    # release. Try local fixtures dir too.
    Path(__file__).parent.parent / "fixtures" / "contract_packages" /
    "airlock-components.yaml",
]


def _airlock_pkg_path():
    for p in _AIRLOCK_PKG_PATHS:
        if p.exists():
            return p
    return None


def test_airlock_components_fixture_available_in_dev_layout():
    """The Airlock package fixture is the BRD §10.5 worked example.
    A conforming runtime in a sibling-checkout layout (compiler +
    conformance side by side) MUST be able to load it. Conformance
    runs in CI may need to copy or vendor it; this test skips
    gracefully if the fixture isn't reachable from this repo."""
    if _airlock_pkg_path() is None:
        pytest.skip("Airlock fixture not present in either expected location")


def test_airlock_components_loads_three_contracts():
    from termin.contract_packages import load_contract_package
    pkg_path = _airlock_pkg_path()
    if pkg_path is None:
        pytest.skip("Airlock fixture not present")
    pkg = load_contract_package(pkg_path)
    contract_names = {c.name for c in pkg.contracts}
    assert contract_names == {
        "cosmic-orb", "airlock-terminal", "scenario-narrative",
    }


def test_airlock_components_verbs_match_brd_appendix_c():
    """The three source-verbs in airlock-components MUST match the
    forms documented in BRD #2 Appendix C / §10.5 — those are the
    canonical examples the conformance suite trains against."""
    from termin.contract_packages import load_contract_package
    pkg_path = _airlock_pkg_path()
    if pkg_path is None:
        pytest.skip("Airlock fixture not present")
    pkg = load_contract_package(pkg_path)
    verbs = {c.source_verb for c in pkg.contracts}
    assert verbs == {
        "Show a cosmic orb of <state-ref>",
        "Show an airlock terminal for <command-set>",
        "Show scenario narrative from <content-ref>",
    }
