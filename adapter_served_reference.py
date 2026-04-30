"""Served Reference Runtime Adapter — runs apps on a real HTTP port.

Like adapter_reference.ReferenceAdapter, but each deployed app is served
by a real uvicorn instance listening on a randomized localhost port.
Sessions communicate via requests (not TestClient), and AppInfo.base_url
is a `http://127.0.0.1:<port>` URL suitable for Playwright navigation.

Use this adapter when you need:
  - Playwright/Chromium tests that navigate to real URLs
  - Visual regression tests
  - Any browser-driven conformance check

Usage:
    TERMIN_ADAPTER=served-reference pytest tests/ -v

Requires:
  pip install termin-compiler      # for the runtime
  pip install uvicorn              # for serving
  pip install requests             # for HTTP clients

The cost is startup time (~0.5s per app). Once running, the same app
instance is reused across the session, same as the in-process adapter.
"""

import json
import os
import socket
import threading
import time
import zipfile
from pathlib import Path

import requests

from adapter import RuntimeAdapter, AppInfo, TerminSession


class _ServedSession(TerminSession):
    """TerminSession backed by a real HTTP client talking to a local
    uvicorn instance. Manages identity cookies client-side per-request
    to mirror ReferenceAdapter's isolation."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._role = None
        self._user_name = "User"

    def _cookies(self):
        cookies = {}
        if self._role:
            cookies["termin_role"] = self._role
        cookies["termin_user_name"] = self._user_name
        return cookies

    def get(self, path, **kwargs):
        kwargs.setdefault("cookies", self._cookies())
        return self._session.get(f"{self.base_url}{path}", **kwargs)

    def post(self, path, **kwargs):
        kwargs.setdefault("cookies", self._cookies())
        return self._session.post(f"{self.base_url}{path}", **kwargs)

    def put(self, path, **kwargs):
        kwargs.setdefault("cookies", self._cookies())
        return self._session.put(f"{self.base_url}{path}", **kwargs)

    def delete(self, path, **kwargs):
        kwargs.setdefault("cookies", self._cookies())
        return self._session.delete(f"{self.base_url}{path}", **kwargs)

    def set_role(self, role, user_name="User"):
        self._role = role
        self._user_name = user_name

    # Intentionally no websocket_connect here — adapters that do need
    # WebSocket use the reference adapter. Can be added later if a
    # browser test requires a native ws client alongside Playwright.


class _ServedApp:
    """Holds the uvicorn server + thread for one app. start()/stop()
    are idempotent."""

    def __init__(self, app):
        self.app = app
        self.port = self._free_port()
        self.server = None
        self.thread = None

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self):
        import uvicorn
        # log_level="error" keeps stdout clean during tests. Use
        # lifespan="on" so the app's startup tasks (event-bus
        # forwarder, scheduler, seed-loader, etc.) actually run.
        config = uvicorn.Config(
            self.app, host="127.0.0.1", port=self.port,
            log_level="error", lifespan="on",
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        # Poll until the server answers. Use a GET to /api/reflect if
        # available — a declared-API endpoint present in every app —
        # otherwise fall back to the root path.
        for _ in range(100):
            try:
                r = requests.get(f"{self.base_url}/api/reflect", timeout=1.0)
                # Any response (including 404) means the server is alive.
                _ = r.status_code
                return
            except (requests.ConnectionError, requests.Timeout, OSError):
                time.sleep(0.1)
        # Try root as a last resort
        for _ in range(50):
            try:
                r = requests.get(f"{self.base_url}/", timeout=1.0)
                _ = r.status_code
                return
            except (requests.ConnectionError, requests.Timeout, OSError):
                time.sleep(0.1)
        raise RuntimeError(
            f"Served runtime did not start on {self.base_url} within 15 seconds")

    def stop(self):
        if self.server:
            self.server.should_exit = True
            if self.thread:
                self.thread.join(timeout=5)


class ServedReferenceAdapter(RuntimeAdapter):
    """Real-HTTP-port variant of ReferenceAdapter. Use when a browser
    (Playwright, real user-agent) needs to navigate to the runtime."""

    def __init__(self):
        self._sessions = {}
        self._servers = {}

    def deploy(self, fixture_path: Path, app_name: str) -> AppInfo:
        # Slice 7.3 of Phase 7 (2026-04-30): canonical path after the
        # runtime extraction.
        from termin_server import create_termin_app

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

        deploy_config = None
        deploy_config_path = fixture_path.parent / f"{app_name}.deploy.json"
        if deploy_config_path.exists():
            deploy_config = json.loads(deploy_config_path.read_text(encoding="utf-8"))

        import tempfile
        db_file = tempfile.mktemp(suffix=f"_{app_name}.db")
        app = create_termin_app(ir_json, db_path=db_file, seed_data=seed_data,
                                deploy_config=deploy_config,
                                strict_channels=False)

        served = _ServedApp(app)
        served.start()

        session = _ServedSession(served.base_url)
        info = AppInfo(
            base_url=served.base_url,
            ir=ir,
            cleanup=served.stop,
        )
        self._sessions[id(info)] = session
        self._servers[id(info)] = served
        return info

    def create_session(self, app_info: AppInfo) -> TerminSession:
        return self._sessions[id(app_info)]
