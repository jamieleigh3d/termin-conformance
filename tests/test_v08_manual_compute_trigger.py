"""Conformance — v0.8 manual compute trigger endpoint.

Every conforming runtime must expose:

  POST /api/v1/compute/<name>/trigger

With body:

  {"record": <content record>, "content_name": "<content_snake>"}

Behavior:
  - 404 if the compute name is unknown.
  - 400 if the body is not valid JSON.
  - 400 if content_name is provided and is not declared in the app.
  - If the compute declares exactly one input_content, content_name
    may be omitted; the runtime infers it.
  - 403 if the caller lacks the compute's required_scope.
  - 200 with an envelope {invocation_id, compute, provider, trigger,
    status} on success. `trigger` is the literal string "manual".

This endpoint exists so agent and LLM computes can be invoked
on-demand for testing and dev-loop iteration without waiting for
their normal trigger (event, schedule, or api).

Uses the compute_demo fixture which has 5 CEL compute definitions.
Compute names are snake_case in URL paths.
"""

import pytest


CEL_COMPUTE = "calculate_order_total"


@pytest.fixture(autouse=True)
def _authenticated(compute_demo):
    compute_demo.set_role("order manager")
    yield


class TestManualTriggerEndpointExistence:
    def test_unknown_compute_returns_404(self, compute_demo):
        r = compute_demo.post(
            "/api/v1/compute/zz_nonexistent/trigger",
            json={"record": {}, "content_name": "orders"},
        )
        assert r.status_code == 404

    def test_non_json_body_returns_400(self, compute_demo):
        r = compute_demo.post(
            f"/api/v1/compute/{CEL_COMPUTE}/trigger",
            data=b"not json",
            headers={"Content-Type": "text/plain"},
        )
        assert r.status_code == 400

    def test_unknown_content_name_returns_400(self, compute_demo):
        r = compute_demo.post(
            f"/api/v1/compute/{CEL_COMPUTE}/trigger",
            json={"record": {}, "content_name": "zz_nonexistent_content"},
        )
        assert r.status_code == 400


class TestManualTriggerEnvelope:
    def test_trigger_returns_invocation_envelope(self, compute_demo):
        # Seed an order so there's a record to operate on.
        r_create = compute_demo.post(
            "/api/v1/orders",
            json={"customer": "Acme", "total": 100, "priority": "medium"},
        )
        assert r_create.status_code == 201, r_create.text

        r = compute_demo.post(
            f"/api/v1/compute/{CEL_COMPUTE}/trigger",
            json={"record": r_create.json(), "content_name": "orders"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "invocation_id" in body
        assert "compute" in body
        assert "provider" in body
        assert body.get("trigger") == "manual"
        assert body.get("status") == "completed"

    def test_content_name_inferred_when_single_input(self, compute_demo):
        """If the compute declares exactly one input_content, content_name
        can be omitted. calculate_order_total has one input (orders)."""
        r_create = compute_demo.post(
            "/api/v1/orders",
            json={"customer": "Beta", "total": 50, "priority": "low"},
        )
        assert r_create.status_code == 201

        r = compute_demo.post(
            f"/api/v1/compute/{CEL_COMPUTE}/trigger",
            json={"record": r_create.json()},
        )
        assert r.status_code == 200, r.text
