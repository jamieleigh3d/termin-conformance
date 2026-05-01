"""Conformance — v0.9 Compute provider contract surface (compute-contract.md §2, §3).

Adapter-agnostic tests for the three Compute contracts (`default-CEL`,
`llm`, `ai-agent`) and their registry / deploy-config keying surface.
These tests go through the conformance adapter — never importing
runtime internals — so any conforming (runtime, provider-set) pair
passes the same suite.

The IR exposed via ``app_info.ir`` plus the runtime's behavior on the
manual-trigger endpoint give us everything we need to assert the
contract surface is in place. We do NOT poke at provider classes
directly; the contract is a behavioral one, observed through the
deployed app.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


# ──────────────────────────────────────────────────────────────────────
# § 2 — Three Compute contracts present in IR (source-level shape)
# ──────────────────────────────────────────────────────────────────────


class TestThreeContracts:
    """Per compute-contract.md §2 — three named compute contracts.

    The IR exposes `provider` on each ComputeSpec. Conforming runtimes
    must accept the three documented contract names and reject others
    upstream of deploy.
    """

    def test_default_cel_present_in_compute_demo(self, compute_demo, compute_demo_ir):
        """compute_demo carries five default-CEL computes (no
        Provider is line). Their IR provider field is null/empty.

        Note: every IR-only fixture in this file pairs with the
        session-scoped app fixture (e.g. ``compute_demo``) so the
        session-scoped TestClient is closed at session teardown via
        the app fixture's cleanup. ``*_ir`` fixtures alone never
        close the cached client and pytest will hang on exit.
        """
        cel_computes = [
            c for c in compute_demo_ir.get("computes", [])
            if not c.get("provider")
        ]
        assert len(cel_computes) >= 5, (
            f"compute_demo should declare >=5 default-CEL computes; "
            f"got {len(cel_computes)}"
        )

    def test_llm_contract_present_in_agent_simple(self, agent_simple, agent_simple_ir):
        """agent_simple has one llm compute (`complete`)."""
        llm = [
            c for c in agent_simple_ir.get("computes", [])
            if c.get("provider") == "llm"
        ]
        assert len(llm) == 1, (
            f"agent_simple should declare exactly one llm compute; "
            f"found {[c['name'] for c in llm]}"
        )

    def test_ai_agent_contract_present_in_agent_chatbot(self, agent_chatbot, agent_chatbot_ir):
        """agent_chatbot has one ai-agent compute (`reply`)."""
        agents = [
            c for c in agent_chatbot_ir.get("computes", [])
            if c.get("provider") == "ai-agent"
        ]
        assert len(agents) == 1, (
            f"agent_chatbot should declare exactly one ai-agent compute; "
            f"found {[c['name'] for c in agents]}"
        )

    def test_contract_names_exact_strings(
        self, agent_chatbot, agent_chatbot_ir,
        agent_simple, agent_simple_ir,
    ):
        """Per §3.1, contract names are case-sensitive exact strings.
        ai-agent uses a hyphen; llm is lowercase. The compiled IR
        carries these strings unchanged."""
        agent = next(
            c for c in agent_chatbot_ir["computes"]
            if c.get("provider") == "ai-agent"
        )
        # Rejects ai_agent / AI-Agent / aiAgent shapes.
        assert agent["provider"] == "ai-agent"
        llm = next(
            c for c in agent_simple_ir["computes"]
            if c.get("provider") == "llm"
        )
        assert llm["provider"] == "llm"


# ──────────────────────────────────────────────────────────────────────
# § 3.1 — Registry resolution observed through the manual trigger
# ──────────────────────────────────────────────────────────────────────


class TestComputeManualTrigger:
    """Per compute-contract.md §3.1 + §3.2 — the runtime resolves a
    compute to (Category.COMPUTE, contract, product) at deploy time and
    dispatches to the registered factory on invocation. The manual
    trigger endpoint exercises the full chain.
    """

    def test_default_cel_compute_invokes_via_trigger(self, compute_demo):
        """A default-CEL compute resolves to (COMPUTE, default-CEL,
        default-cel) and invokes successfully without any deploy
        binding."""
        compute_demo.set_role("order manager")
        # Seed an order so there's a record to operate on.
        r_create = compute_demo.post(
            "/api/v1/orders",
            json={"customer": "Acme", "total": 100, "priority": "medium"},
        )
        assert r_create.status_code == 201, r_create.text
        r = compute_demo.post(
            "/api/v1/compute/calculate_order_total/trigger",
            json={"record": r_create.json(), "content_name": "orders"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # The provider field on the response identifies which contract
        # was used. For default-CEL this is "default-CEL" or null/empty.
        # We accept any of those — the conformance bar is "didn't
        # crash and didn't try to bind a non-existent product."
        assert body.get("status") == "completed"

    def test_unknown_compute_returns_404(self, compute_demo):
        """Trigger to an unregistered compute name returns 404 — the
        runtime does not silently substitute or crash."""
        compute_demo.set_role("order manager")
        r = compute_demo.post(
            "/api/v1/compute/zz_nonexistent/trigger",
            json={"record": {}, "content_name": "orders"},
        )
        assert r.status_code == 404


# ──────────────────────────────────────────────────────────────────────
# § 3.2 — Deploy-config bindings (observable via fixtures)
# ──────────────────────────────────────────────────────────────────────


class TestDeployConfigKeying:
    """Per compute-contract.md §3.2 — bindings.compute is name-keyed by
    the source-level Compute snake name. Every llm/ai-agent compute
    in the IR must have a binding entry; default-CEL computes do not
    appear in bindings.compute.

    These tests inspect the on-disk deploy fixtures; runtimes that
    accept these fixtures and serve their app are conforming for
    deploy-config keying.
    """

    def _load_deploy(self, app_name: str) -> dict:
        path = FIXTURES_DIR / f"{app_name}.deploy.json"
        if not path.exists():
            pytest.skip(f"No deploy fixture for {app_name}")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_agent_chatbot_binding_keyed_by_compute_name(self):
        cfg = self._load_deploy("agent_chatbot")
        compute = cfg["bindings"]["compute"]
        # Source has one Compute called "reply" (snake = reply).
        assert "reply" in compute, (
            f"bindings.compute must be keyed by compute snake name 'reply'; "
            f"got keys {list(compute)}"
        )
        # Each entry is {provider, config}.
        entry = compute["reply"]
        assert "provider" in entry
        assert "config" in entry

    def test_agent_simple_binding_keyed_by_compute_name(self):
        cfg = self._load_deploy("agent_simple")
        compute = cfg["bindings"]["compute"]
        assert "complete" in compute, (
            f"bindings.compute must be keyed by 'complete'; got {list(compute)}"
        )

    def test_default_cel_computes_absent_from_bindings(self):
        """compute_demo declares only default-CEL computes; it should
        carry an empty bindings.compute (or no llm/agent entries)."""
        cfg = self._load_deploy("compute_demo")
        compute = cfg["bindings"]["compute"]
        # default-CEL computes don't get bindings; the dict may be
        # empty or contain only entries that are explicitly bound to
        # something (which compute_demo does not declare).
        for name, entry in compute.items():
            # If any entry exists, it must NOT claim to be default-CEL
            # bound through bindings.compute (which would be a
            # contract violation).
            assert entry.get("provider") not in (None, "default-CEL", "default-cel"), (
                f"compute_demo binding {name} should not bind default-CEL"
            )

    def test_security_agent_service_mode_bindings(self):
        """security_agent has two ai-agent computes both in service
        mode. Each should appear in bindings.compute keyed by snake."""
        cfg = self._load_deploy("security_agent")
        compute = cfg["bindings"]["compute"]
        assert "scanner" in compute
        assert "remediator" in compute
