"""Conformance — v0.8 security: PUT route state-machine gate.

The auto-CRUD `PUT /api/v1/<content>/<id>` route must not permit
state-machine-backed columns to bypass the declared transitions and
required_scope. In v0.8, this was a latent backdoor: a PUT body
including `{"status": "<target>"}` wrote the value directly, skipping
both the transition rules and the transition's required_scope.

Every conforming runtime must:

  1. Detect state-machine-backed fields in the PUT body.
  2. Route those changes through the state transition system, which
     validates the transition exists and the caller holds the
     transition's required_scope.
  3. Reject PUTs that attempt:
       - a transition not declared in the state machine (409)
       - a state value the state machine doesn't know (409)
       - a transition the caller's scopes don't permit (403)
  4. Preserve atomicity: if the transition is rejected, companion
     field updates in the same PUT body must NOT land.

v0.9 update: the state column is now named after the state-typed field
on the Content (e.g. `product_lifecycle` rather than the legacy
implicit `status`). A Content may declare multiple state-typed fields
— each generates its own column and its own transition table; the
PUT-route gate must inspect every state-typed column in the body and
route each through its respective state machine independently.

Uses warehouse, where:
  "warehouse clerk":   inventory.read + inventory.write
  "warehouse manager": read + write + admin
  "executive":         inventory.read (no write, no admin)

State machine `product_lifecycle` transitions:
  draft    -> active         requires inventory.write
  active   -> discontinued   requires inventory.admin
  discontinued -> active     requires inventory.admin
"""

import uuid
import pytest


# v0.9: state column = snake_case field name on the Content. Warehouse
# declares `Each product has a lifecycle which is state:`, so the column
# is `product_lifecycle` (lowering snake-cases the machine_name from the
# field declaration). Capturing this as a constant keeps the test
# resistant to a future warehouse rename.
SM_COL = "product_lifecycle"


def _sku(prefix="PUT"):
    return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"


@pytest.fixture
def draft_product(warehouse):
    """Create a fresh draft product as the manager."""
    warehouse.set_role("warehouse manager")
    r = warehouse.post("/api/v1/products", json={
        "sku": _sku(),
        "name": "Conformance PUT-gate product",
        "category": "raw material",
        "unit_cost": 1.0,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


class TestUndeclaredTransitionBlocked:
    def test_put_skipping_a_declared_transition_rejected(self, warehouse, draft_product):
        """draft -> discontinued is not declared. Must 409 regardless
        of caller scopes."""
        warehouse.set_role("warehouse manager")
        r = warehouse.put(f"/api/v1/products/{draft_product}",
                          json={SM_COL: "discontinued"})
        assert r.status_code == 409, r.text
        r2 = warehouse.get(f"/api/v1/products/{draft_product}")
        assert r2.json()[SM_COL] == "draft"

    def test_put_with_unknown_state_value_rejected(self, warehouse, draft_product):
        warehouse.set_role("warehouse manager")
        r = warehouse.put(f"/api/v1/products/{draft_product}",
                          json={SM_COL: "nonexistent_state"})
        assert r.status_code == 409
        r2 = warehouse.get(f"/api/v1/products/{draft_product}")
        assert r2.json()[SM_COL] == "draft"


class TestTransitionScopeEnforced:
    def test_clerk_cannot_discontinue_via_put(self, warehouse, draft_product):
        """active -> discontinued requires inventory.admin. A clerk
        with only inventory.write must get 403."""
        warehouse.set_role("warehouse manager")
        # Promote to active first.
        r_activate = warehouse.post(
            f"/_transition/products/{SM_COL}/{draft_product}/active")
        assert r_activate.status_code == 200

        warehouse.set_role("warehouse clerk")
        r = warehouse.put(f"/api/v1/products/{draft_product}",
                          json={SM_COL: "discontinued"})
        assert r.status_code == 403, r.text

        # State unchanged.
        warehouse.set_role("warehouse manager")
        r2 = warehouse.get(f"/api/v1/products/{draft_product}")
        assert r2.json()[SM_COL] == "active"


class TestValidTransitionStillSucceeds:
    def test_clerk_activate_via_put_succeeds(self, warehouse, draft_product):
        """draft -> active requires inventory.write. Clerk has it."""
        warehouse.set_role("warehouse clerk")
        r = warehouse.put(f"/api/v1/products/{draft_product}",
                          json={SM_COL: "active"})
        assert r.status_code == 200, r.text
        r2 = warehouse.get(f"/api/v1/products/{draft_product}")
        assert r2.json()[SM_COL] == "active"


class TestAtomicityOnRejection:
    def test_rejected_transition_reverts_companion_field_changes(
            self, warehouse, draft_product):
        """If a PUT includes both a forbidden transition and a
        description update, the description must NOT persist."""
        warehouse.set_role("warehouse manager")
        warehouse.post(f"/_transition/products/{SM_COL}/{draft_product}/active")

        warehouse.set_role("warehouse clerk")
        r = warehouse.put(f"/api/v1/products/{draft_product}", json={
            "description": "sneaked through",
            SM_COL: "discontinued",
        })
        assert r.status_code == 403

        warehouse.set_role("warehouse manager")
        r2 = warehouse.get(f"/api/v1/products/{draft_product}")
        assert r2.json().get("description", "") != "sneaked through"

    def test_valid_transition_plus_field_update_both_succeed(
            self, warehouse, draft_product):
        warehouse.set_role("warehouse clerk")
        r = warehouse.put(f"/api/v1/products/{draft_product}", json={
            "description": "updated at activation",
            SM_COL: "active",
        })
        assert r.status_code == 200, r.text
        warehouse.set_role("warehouse manager")
        r2 = warehouse.get(f"/api/v1/products/{draft_product}")
        body = r2.json()
        assert body[SM_COL] == "active"
        assert body["description"] == "updated at activation"


class TestBackwardCompatRegression:
    def test_put_without_state_field_still_works(self, warehouse, draft_product):
        """A PUT that doesn't touch state is unaffected by the gate."""
        warehouse.set_role("warehouse clerk")
        r = warehouse.put(f"/api/v1/products/{draft_product}",
                          json={"description": "regular update"})
        assert r.status_code == 200
        warehouse.set_role("warehouse manager")
        r2 = warehouse.get(f"/api/v1/products/{draft_product}")
        assert r2.json().get("description") == "regular update"
        assert r2.json().get(SM_COL) == "draft"

    def test_put_with_same_state_is_noop_on_state(self, warehouse, draft_product):
        """PUT with the current state must not 409 for 'X -> X not
        declared' — the state didn't change. The companion field update
        must still apply."""
        warehouse.set_role("warehouse clerk")
        r = warehouse.put(f"/api/v1/products/{draft_product}", json={
            SM_COL: "draft",
            "description": "same-state PUT",
        })
        assert r.status_code == 200, r.text
        warehouse.set_role("warehouse manager")
        r2 = warehouse.get(f"/api/v1/products/{draft_product}")
        assert r2.json().get(SM_COL) == "draft"
        assert r2.json().get("description") == "same-state PUT"
