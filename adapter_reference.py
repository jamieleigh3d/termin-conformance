"""Reference Runtime Adapter — runs apps in-process using termin_runtime.

This adapter starts the reference Termin runtime (Python, FastAPI, SQLite)
in-process using Starlette's TestClient. No network, no deployment, instant.

Usage:
    pytest tests/ --adapter=reference
    # or set in conftest.py: ADAPTER = ReferenceAdapter()

Requires: pip install termin-compiler (which includes termin_runtime)
"""

import json
import zipfile
from pathlib import Path

from adapter import RuntimeAdapter, AppInfo, TerminSession


class _TestClientSession(TerminSession):
    """Wraps FastAPI TestClient as a TerminSession."""

    def __init__(self, test_client):
        self._client = test_client
        self.base_url = "http://testserver"

    def get(self, path, **kwargs):
        return self._client.get(path, **kwargs)

    def post(self, path, **kwargs):
        return self._client.post(path, **kwargs)

    def put(self, path, **kwargs):
        return self._client.put(path, **kwargs)

    def delete(self, path, **kwargs):
        return self._client.delete(path, **kwargs)

    def set_role(self, role, user_name="User"):
        self._client.cookies.set("termin_role", role)
        self._client.cookies.set("termin_user_name", user_name)


class ReferenceAdapter(RuntimeAdapter):
    """In-process adapter for the Termin reference runtime."""

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

        app = create_termin_app(ir_json, seed_data=seed_data)
        client = TestClient(app)
        client.__enter__()

        return AppInfo(
            base_url="http://testserver",
            ir=ir,
            cleanup=lambda: client.__exit__(None, None, None),
        )

    def create_session(self, app_info: AppInfo) -> TerminSession:
        # For the reference runtime, the TestClient is reused across
        # all tests for the same app (session-scoped fixture)
        # We return a new session wrapper but it shares the same client
        return app_info._session
