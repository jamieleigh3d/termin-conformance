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
        from termin_runtime import create_termin_app
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

        app = create_termin_app(ir_json, seed_data=seed_data,
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

    def create_session(self, app_info: AppInfo) -> TerminSession:
        return self._sessions[id(app_info)]
