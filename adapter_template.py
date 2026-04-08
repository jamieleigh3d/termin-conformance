"""Template Adapter — customize this for your Termin runtime.

Copy this file and implement deploy() for your runtime's deployment
mechanism. The conformance suite calls deploy() once per test app
(6 apps total), gets back a base URL, and runs all tests via HTTP.

See adapter_reference.py for a working example.
"""

import json
import time
from pathlib import Path

import requests

from adapter import RuntimeAdapter, AppInfo, TerminSession


class MyRuntimeAdapter(RuntimeAdapter):
    """Adapter for [Your Runtime Name].

    Replace this with your actual deployment logic.
    """

    def __init__(self, org: str = "myorg", env: str = "staging"):
        self.org = org
        self.env = env

    def deploy(self, fixture_path: Path, app_name: str) -> AppInfo:
        ir = self.load_ir_from_fixture(fixture_path)

        # ── Replace this with your deployment logic ──
        #
        # Example for a cloud runtime:
        #   1. Upload the .termin.pkg to your deployment API
        #   2. Wait for the app to become healthy
        #   3. Return the base URL
        #
        # base_url = f"https://{app_name}.{self.org}.{self.env}.yourdomain.dev"
        # deploy_api.upload(fixture_path, app_name, self.org)
        # _wait_for_healthy(base_url)

        raise NotImplementedError(
            "Implement deploy() with your runtime's deployment logic. "
            "See adapter_reference.py for an example."
        )

        return AppInfo(
            base_url=base_url,
            ir=ir,
            cleanup=lambda: self._teardown(app_name),
        )

    def _teardown(self, app_name: str):
        """Clean up after tests. Override if your runtime needs teardown."""
        pass

    def create_session(self, app_info: AppInfo) -> TerminSession:
        """Create an authenticated session.

        Override if your runtime uses JWT, OAuth, API keys, etc.
        The default uses cookie-based stub auth.
        """
        return TerminSession(app_info.base_url)


def _wait_for_healthy(url: str, timeout: int = 120):
    """Poll until the app responds to /api/reflect."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{url}/api/reflect", timeout=5)
            if r.status_code == 200:
                return
        except requests.ConnectionError:
            pass
        time.sleep(2)
    raise TimeoutError(f"App at {url} did not become healthy within {timeout}s")
