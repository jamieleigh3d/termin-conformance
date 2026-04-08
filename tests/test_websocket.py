"""Termin Runtime Conformance Test Suite.

A comprehensive test suite that validates any conforming Termin runtime
against the behavioral contracts defined in the IR specification and
Runtime Implementer's Guide.

These tests are designed to be portable: they test observable behavior
through the HTTP API and rendered HTML, not internal implementation
details. Any runtime that passes this suite is behaviorally conformant.

Test categories:
  1. Identity & Access Control (40+ tests)
  2. State Machine Enforcement (30+ tests)
  3. Field Validation & Constraints (30+ tests)
  4. CRUD Operations & API Routes (25+ tests)
  5. Presentation & Component Rendering (25+ tests)
  6. Default Expressions & CEL Evaluation (20+ tests)
  7. Data Isolation & Cross-Content Safety (20+ tests)
  8. Event Processing (10+ tests)
  9. Navigation & Role Visibility (10+ tests)
  10. Error Handling & Edge Cases (15+ tests)

Authors: Jamie-Leigh Blake & Claude Anthropic
"""

import json
import uuid
import pytest
from pathlib import Path


def _uid():
    return uuid.uuid4().hex[:8]


# ═══════════════════════════════════════════════════════════════════════
# 1. IDENTITY & ACCESS CONTROL
# ═══════════════════════════════════════════════════════════════════════


class TestWebSocketProtocol:
    """WebSocket runtime protocol conformance.

    These tests require the adapter's session to support websocket_connect().
    Adapters that don't support WebSocket will see these tests skip.
    """

    def test_ws_connect_sends_frames(self, warehouse):
        """WebSocket connection sends initial frames (identity or push)."""
        if not hasattr(warehouse, 'websocket_connect'):
            pytest.skip("Adapter does not support WebSocket")
        with warehouse.websocket_connect("/runtime/ws") as ws:
            frame = ws.receive_json()
            # The first frame should be either an identity frame or a push
            assert "op" in frame or "type" in frame

    def test_ws_subscribe_returns_current_data(self, warehouse):
        if not hasattr(warehouse, 'websocket_connect'):
            pytest.skip("Adapter does not support WebSocket")
        with warehouse.websocket_connect("/runtime/ws") as ws:
            ws.receive_json()  # identity
            ws.send_json({
                "v": 1, "ch": "content.products", "op": "subscribe",
                "ref": "sub-1", "payload": {},
            })
            frame = ws.receive_json()
            assert frame["op"] == "response"
            assert "current" in frame["payload"]

    def test_ws_unsubscribe(self, warehouse):
        if not hasattr(warehouse, 'websocket_connect'):
            pytest.skip("Adapter does not support WebSocket")
        with warehouse.websocket_connect("/runtime/ws") as ws:
            ws.receive_json()  # identity
            ws.send_json({
                "v": 1, "ch": "content.products", "op": "unsubscribe",
                "ref": "unsub-1", "payload": {},
            })
            frame = ws.receive_json()
            assert frame["payload"]["unsubscribed"] is True


# ═══════════════════════════════════════════════════════════════════════
# 11. RUNTIME BOOTSTRAP
# ═══════════════════════════════════════════════════════════════════════
