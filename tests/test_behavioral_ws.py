"""Behavioral WebSocket conformance tests.

Uses REAL uvicorn servers and REAL WebSocket clients (not TestClient).
This catches sync bugs invisible to TestClient:
- Event loop isolation (background threads publishing to main loop)
- Push delivery timing
- Event bus cross-thread communication

These tests exercise the actual production execution model.

Authors: Jamie-Leigh Blake & Claude Anthropic
"""

import asyncio
import json
import socket
import threading
import time
import uuid
import zipfile
from pathlib import Path

import httpx
import pytest
import uvicorn
import websockets.client

from termin_runtime import create_termin_app

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


# ── Server helpers ──────────────────────────────────────────────────────


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _load_fixture(app_name: str):
    """Load IR JSON and optional seed/deploy data from a .termin.pkg."""
    pkg_path = FIXTURES_DIR / f"{app_name}.termin.pkg"
    ir_path = FIXTURES_DIR / "ir" / f"{app_name}_ir.json"

    if pkg_path.exists():
        with zipfile.ZipFile(pkg_path, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))
            ir_json = zf.read(manifest["ir"]["entry"]).decode("utf-8")
            seed_data = None
            if manifest.get("seed"):
                try:
                    seed_data = json.loads(zf.read(manifest["seed"]))
                except (KeyError, json.JSONDecodeError):
                    pass
        return ir_json, seed_data
    elif ir_path.exists():
        return ir_path.read_text(encoding="utf-8"), None
    else:
        raise FileNotFoundError(f"No fixture for '{app_name}' in {FIXTURES_DIR}")


def _load_deploy_config(app_name: str):
    """Load deploy config JSON if it exists alongside the fixture."""
    path = FIXTURES_DIR / f"{app_name}.deploy.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


class UvicornTestServer:
    """Runs uvicorn in a background thread on a random port."""

    def __init__(self, app, port=0):
        self.app = app
        self.port = port or _find_free_port()
        self.server = None
        self.thread = None

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}"

    @property
    def ws_url(self):
        return f"ws://127.0.0.1:{self.port}/runtime/ws"

    def start(self):
        config = uvicorn.Config(
            self.app, host="127.0.0.1", port=self.port, log_level="error"
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        # Wait for server readiness
        for _ in range(100):
            try:
                with httpx.Client() as client:
                    client.get(f"{self.base_url}/api/reflect", timeout=1.0)
                return
            except (httpx.ConnectError, httpx.ReadTimeout, OSError):
                time.sleep(0.1)
        raise RuntimeError("Server didn't start within 10 seconds")

    def stop(self):
        if self.server:
            self.server.should_exit = True
            self.thread.join(timeout=5)


def _make_server(app_name: str) -> UvicornTestServer:
    """Build and start a UvicornTestServer for the given fixture app."""
    ir_json, seed_data = _load_fixture(app_name)
    deploy_config = _load_deploy_config(app_name)
    app = create_termin_app(
        ir_json, seed_data=seed_data,
        strict_channels=False, deploy_config=deploy_config,
    )
    server = UvicornTestServer(app)
    server.start()
    return server


# ── Session-scoped fixtures ─────────────────────────────────────────────


@pytest.fixture(scope="session")
def agent_simple_ws_server():
    server = _make_server("agent_simple")
    yield server
    server.stop()


@pytest.fixture(scope="session")
def channel_simple_ws_server():
    server = _make_server("channel_simple")
    yield server
    server.stop()


@pytest.fixture(scope="session")
def warehouse_ws_server():
    server = _make_server("warehouse")
    yield server
    server.stop()


# ── Helpers ──────────────────────────────────────────────────────────────


async def _recv_until(ws, op, timeout=5, max_msgs=10):
    """Receive messages until we get one with the specified op."""
    for _ in range(max_msgs):
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        if msg.get("op") == op:
            return msg
    pytest.fail(f"Never received op='{op}' after {max_msgs} messages")


# ── Behavioral spec tests ───────────────────────────────────────────────


class TestBehavioralWebSocket:
    """Real-server WebSocket behavioral conformance tests.

    All element/field selection uses data-termin-* attribute names
    (field snake_case names from IR), never hardcoded English text.
    """

    # ── test_create_produces_push_within_2s ──

    @pytest.mark.asyncio
    async def test_create_produces_push_within_2s(self, agent_simple_ws_server):
        """Create record via API, WS subscriber receives push within 2 seconds."""
        server = agent_simple_ws_server

        async with websockets.client.connect(server.ws_url) as ws:
            # Subscribe to completions content channel
            await ws.send(json.dumps({
                "v": 1, "ch": "content.completions", "op": "subscribe",
                "ref": "sub1", "payload": {},
            }))
            await _recv_until(ws, "response")

            # Create a record via the REST API
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{server.base_url}/api/v1/completions",
                    json={"prompt": "behavioral-push-test"},
                    cookies={"termin_role": "anonymous"},
                )
                assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"

            # Push must arrive within 2 seconds
            push = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            assert push["op"] == "push"
            assert "completions" in push["ch"]
            assert push["payload"]["prompt"] == "behavioral-push-test"

    # ── test_update_produces_push ──

    @pytest.mark.asyncio
    async def test_update_produces_push(self, warehouse_ws_server):
        """Update record via API, WS subscriber receives push with updated fields."""
        server = warehouse_ws_server

        # First create a product so we have something to update
        unique_sku = f"WS-UPD-{uuid.uuid4().hex[:6]}"
        async with httpx.AsyncClient() as client:
            create_resp = await client.post(
                f"{server.base_url}/api/v1/products",
                json={
                    "sku": unique_sku,
                    "name": "Update Test Widget",
                    "description": "original",
                    "unit_cost": 10.00,
                    "category": "raw material",
                },
                cookies={
                    "termin_role": "warehouse clerk",
                    "termin_user_name": "User",
                },
            )
            assert create_resp.status_code == 201

        # Now subscribe and update (warehouse uses {sku} as lookup)
        async with websockets.client.connect(server.ws_url) as ws:
            await ws.send(json.dumps({
                "v": 1, "ch": "content.products", "op": "subscribe",
                "ref": "sub1", "payload": {},
            }))
            await _recv_until(ws, "response")

            async with httpx.AsyncClient() as client:
                update_resp = await client.put(
                    f"{server.base_url}/api/v1/products/{unique_sku}",
                    json={"description": "updated-via-ws-test"},
                    cookies={
                        "termin_role": "warehouse clerk",
                        "termin_user_name": "User",
                    },
                )
                assert update_resp.status_code == 200

            push = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            assert push["op"] == "push"
            assert "products" in push["ch"]
            # The pushed record should reflect the update
            assert push["payload"]["description"] == "updated-via-ws-test"

    # ── test_push_payload_has_record_id_and_fields ──

    @pytest.mark.asyncio
    async def test_push_payload_has_record_id_and_fields(self, agent_simple_ws_server):
        """Push payload is the record dict with 'id' and field names from IR."""
        server = agent_simple_ws_server

        async with websockets.client.connect(server.ws_url) as ws:
            await ws.send(json.dumps({
                "v": 1, "ch": "content.completions", "op": "subscribe",
                "ref": "sub1", "payload": {},
            }))
            await _recv_until(ws, "response")

            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{server.base_url}/api/v1/completions",
                    json={"prompt": "payload-shape-test"},
                    cookies={"termin_role": "anonymous"},
                )

            push = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            payload = push["payload"]

            # Must have record 'id' (data-termin-id)
            assert "id" in payload, f"Payload missing 'id': {list(payload.keys())}"
            # Must have the field names from IR (data-termin-field-*)
            assert "prompt" in payload, f"Payload missing 'prompt': {list(payload.keys())}"
            # Must NOT be wrapped in an event envelope
            assert "channel_id" not in payload, "Payload is an event wrapper, not a record"
            assert "record" not in payload, "Payload has nested 'record' key"

    # ── test_subscribe_returns_current_records ──

    @pytest.mark.asyncio
    async def test_subscribe_returns_current_records(self, agent_simple_ws_server):
        """Subscribe response includes existing records."""
        server = agent_simple_ws_server

        # Ensure at least one record exists
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{server.base_url}/api/v1/completions",
                json={"prompt": "pre-existing-record"},
                cookies={"termin_role": "anonymous"},
            )

        # Subscribe — response should include current data
        async with websockets.client.connect(server.ws_url) as ws:
            await ws.send(json.dumps({
                "v": 1, "ch": "content.completions", "op": "subscribe",
                "ref": "sub1", "payload": {},
            }))
            resp = await _recv_until(ws, "response")

            assert "current" in resp["payload"], (
                f"Subscribe response missing 'current': {list(resp['payload'].keys())}"
            )
            records = resp["payload"]["current"]
            assert isinstance(records, list)
            assert len(records) > 0, "Expected at least one existing record"
            # Each record should have 'id' and field names
            assert all("id" in r for r in records)

    # ── test_no_push_for_unsubscribed_content ──

    @pytest.mark.asyncio
    async def test_no_push_for_unsubscribed_content(self, channel_simple_ws_server):
        """Creating content type A does not push to content type B subscribers."""
        server = channel_simple_ws_server

        async with websockets.client.connect(server.ws_url) as ws:
            # Subscribe to echoes ONLY
            await ws.send(json.dumps({
                "v": 1, "ch": "content.echoes", "op": "subscribe",
                "ref": "sub1", "payload": {},
            }))
            await _recv_until(ws, "response")

            # Create a note (NOT an echo)
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{server.base_url}/api/v1/notes",
                    json={"title": "wrong-channel-test", "body": "should not push"},
                    cookies={
                        "termin_role": "anonymous",
                        "termin_user_name": "User",
                    },
                )
                assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"

            # Should NOT receive a push for notes when subscribed to echoes
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1)
                msg = json.loads(raw)
                if msg["op"] == "push" and "notes" in msg.get("ch", ""):
                    pytest.fail(
                        f"Received push for unsubscribed content type: {msg['ch']}"
                    )
            except asyncio.TimeoutError:
                pass  # Expected — no push for unsubscribed content
