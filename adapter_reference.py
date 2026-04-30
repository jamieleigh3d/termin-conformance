"""Reference Runtime Adapter — runs apps in-process using termin_runtime.

This adapter starts the reference Termin runtime (Python, FastAPI, SQLite)
in-process using Starlette's TestClient. No network, no deployment, instant.

Usage:
    TERMIN_ADAPTER=reference pytest tests/ -v

Requires: pip install termin-compiler (which includes termin_runtime)
"""

import json
import zipfile
from pathlib import Path

from adapter import RuntimeAdapter, AppInfo, TerminSession


class _TestClientSession(TerminSession):
    """Wraps FastAPI TestClient as a TerminSession.

    Manages identity cookies explicitly per-request to avoid session
    state bleeding between tests when the fixture is session-scoped.
    """

    def __init__(self, test_client):
        self._client = test_client
        self.base_url = "http://testserver"
        self._role = None
        self._user_name = "User"

    def _cookies(self):
        """Build cookie dict for the current identity."""
        cookies = {}
        if self._role:
            cookies["termin_role"] = self._role
        cookies["termin_user_name"] = self._user_name
        return cookies

    def get(self, path, **kwargs):
        kwargs.setdefault("cookies", self._cookies())
        return self._client.get(path, **kwargs)

    def post(self, path, **kwargs):
        kwargs.setdefault("cookies", self._cookies())
        return self._client.post(path, **kwargs)

    def put(self, path, **kwargs):
        kwargs.setdefault("cookies", self._cookies())
        return self._client.put(path, **kwargs)

    def delete(self, path, **kwargs):
        kwargs.setdefault("cookies", self._cookies())
        return self._client.delete(path, **kwargs)

    def set_role(self, role, user_name="User"):
        self._role = role
        self._user_name = user_name

    def websocket_connect(self, path):
        """Delegate to TestClient's websocket_connect."""
        return self._client.websocket_connect(path)


class ReferenceAdapter(RuntimeAdapter):
    """In-process adapter for the Termin reference runtime."""

    def __init__(self):
        self._sessions = {}

    def deploy(self, fixture_path: Path, app_name: str) -> AppInfo:
        # Slice 7.3 of Phase 7 (2026-04-30): the reference runtime moved
        # to the termin-server sibling repo. The legacy
        # ``from termin_runtime import create_termin_app`` shim still
        # works through v0.9; use the canonical path here so the adapter
        # is forward-clean.
        from termin_server import create_termin_app
        from fastapi.testclient import TestClient

        ir = self.load_ir_from_fixture(fixture_path)
        ir_json = json.dumps(ir)

        # Load seed data if present in .termin.pkg
        seed_data = None
        if fixture_path.suffix == ".pkg" or fixture_path.name.endswith(".termin.pkg"):
            with zipfile.ZipFile(fixture_path, 'r') as zf:
                manifest = json.loads(zf.read("manifest.json"))
                if manifest.get("seed"):
                    try:
                        seed_data = json.loads(zf.read(manifest["seed"]))
                    except (KeyError, json.JSONDecodeError):
                        pass

        # Load deploy config if present alongside the fixture
        deploy_config = None
        deploy_config_path = fixture_path.parent / f"{app_name}.deploy.json"
        if deploy_config_path.exists():
            deploy_config = json.loads(deploy_config_path.read_text(encoding="utf-8"))

        import tempfile
        db_file = tempfile.mktemp(suffix=f"_{app_name}.db")
        app = create_termin_app(ir_json, db_path=db_file, seed_data=seed_data,
                                deploy_config=deploy_config)
        client = TestClient(app)
        client.__enter__()

        session = _TestClientSession(client)
        info = AppInfo(
            base_url="http://testserver",
            ir=ir,
            cleanup=lambda: client.__exit__(None, None, None),
        )
        self._sessions[id(info)] = session
        return info

    def deploy_with_agent_mock(self, fixture_path, app_name, tool_calls):
        """Deploy with a mock AI provider that executes the given tool calls."""
        from termin_server import create_termin_app
        from termin_server.ai_provider import AIProvider
        from fastapi.testclient import TestClient
        import tempfile

        ir = self.load_ir_from_fixture(fixture_path)
        ir_json = json.dumps(ir)

        seed_data = None
        if fixture_path.suffix == ".pkg" or fixture_path.name.endswith(".termin.pkg"):
            with zipfile.ZipFile(fixture_path, 'r') as zf:
                manifest = json.loads(zf.read("manifest.json"))
                if manifest.get("seed"):
                    try:
                        seed_data = json.loads(zf.read(manifest["seed"]))
                    except (KeyError, json.JSONDecodeError):
                        pass

        # Mock deploy config — v0.9 shape so the strict deploy-config
        # validator and per-compute provider binding both accept it.
        # `api_key="mock"` is a literal (no `${` placeholder) so the
        # provider's is_configured() check passes, the patched
        # AIProvider.startup runs, and the patched agent_loop is
        # callable from compute_runner.
        def _mock_compute_bindings(ir_dict):
            mock = {}
            for c in ir_dict.get("computes", []):
                if (c.get("provider") or "") not in ("llm", "ai-agent"):
                    continue
                mock[c["name"]["snake"]] = {
                    "provider": "anthropic",
                    "config": {"model": "mock", "api_key": "mock"},
                }
            return mock

        deploy_config = {
            "version": "0.9.0",
            "bindings": {
                "identity": {"provider": "stub", "config": {}},
                "storage": {"provider": "sqlite", "config": {}},
                "presentation": {"provider": "default", "config": {}},
                "compute": _mock_compute_bindings(ir),
                "channels": {},
            },
            "runtime": {},
        }
        deploy_path = fixture_path.parent / f"{app_name}.deploy.json"
        if deploy_path.exists():
            deploy_config = json.loads(deploy_path.read_text(encoding="utf-8"))
            # Patch every LLM/agent compute binding's api_key so the
            # mock provider becomes is_configured.
            bindings = deploy_config.get("bindings", {})
            compute = bindings.get("compute", {}) if isinstance(bindings, dict) else {}
            for entry in compute.values():
                if isinstance(entry, dict):
                    cfg = entry.setdefault("config", {})
                    cfg["model"] = "mock"
                    cfg["api_key"] = "mock"

        # Shared result collector
        tool_results = []

        # Patch AIProvider
        original_startup = AIProvider.startup
        original_agent_loop = AIProvider.agent_loop
        original_agent_loop_streaming = getattr(
            AIProvider, "agent_loop_streaming", None)

        def mock_startup(self_ai):
            self_ai._client = True

        async def mock_agent_loop(self_ai, system_prompt, user_message, tools, execute_tool):
            for tool_name, tool_input in tool_calls:
                result = await execute_tool(tool_name, tool_input)
                tool_results.append({"tool": tool_name, "input": tool_input, "result": result})
            return {"thinking": "mock agent completed", "tool_results": tool_results}

        async def mock_agent_loop_streaming(self_ai, system_prompt, user_message,
                                             tools, execute_tool,
                                             on_event=None, max_turns=20):
            """Streaming-path mock — executes the same scripted tool
            calls as mock_agent_loop. Skips emitting field_delta events
            since the mock has no text to stream; fires a single done
            event so clients see a terminal signal."""
            result = await mock_agent_loop(
                self_ai, system_prompt, user_message, tools, execute_tool)
            if on_event:
                await on_event({"type": "done", "output": result})
            return result

        AIProvider.startup = mock_startup
        AIProvider.agent_loop = mock_agent_loop
        AIProvider.agent_loop_streaming = mock_agent_loop_streaming

        db_file = tempfile.mktemp(suffix=".db")
        app = create_termin_app(ir_json, db_path=db_file, seed_data=seed_data,
                                deploy_config=deploy_config, strict_channels=False)
        client = TestClient(app)
        client.__enter__()

        session = _TestClientSession(client)
        info = AppInfo(
            base_url="http://testserver",
            ir=ir,
            cleanup=lambda: (
                client.__exit__(None, None, None),
                setattr(AIProvider, 'startup', original_startup),
                setattr(AIProvider, 'agent_loop', original_agent_loop),
                (setattr(AIProvider, 'agent_loop_streaming',
                         original_agent_loop_streaming)
                 if original_agent_loop_streaming is not None
                 else delattr(AIProvider, 'agent_loop_streaming')),
            ),
        )
        self._sessions[id(info)] = session
        return info, tool_results

    def create_session(self, app_info: AppInfo) -> TerminSession:
        return self._sessions[id(app_info)]
