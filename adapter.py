"""Termin Conformance Suite — Runtime Adapter Interface.

Each runtime implementation provides a concrete adapter by subclassing
RuntimeAdapter. The adapter tells the conformance suite how to:

1. Deploy a test app from a .termin.pkg or raw IR JSON
2. Authenticate as a specific role
3. Tear down after tests

See adapter_reference.py for the reference runtime adapter.
See adapter_template.py for a blank template to customize.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import json
import zipfile

import requests


@dataclass
class AppInfo:
    """Returned by deploy(). Contains everything needed to test the app."""
    base_url: str                      # e.g. "http://localhost:8000" or "https://warehouse.org.runtime.dev"
    ir: dict                           # parsed IR JSON (for test introspection)
    cleanup: Optional[callable] = None # called after tests to tear down


class TerminSession:
    """HTTP session wrapper for conformance tests.

    Provides get/post/put/delete against a base URL, with identity
    management via set_role(). The adapter controls how identity
    is established (cookies, tokens, headers, etc.).
    """

    def __init__(self, base_url: str, session: requests.Session = None):
        self.base_url = base_url.rstrip("/")
        self._session = session or requests.Session()

    def get(self, path, **kwargs):
        return self._session.get(f"{self.base_url}{path}", **kwargs)

    def post(self, path, **kwargs):
        return self._session.post(f"{self.base_url}{path}", **kwargs)

    def put(self, path, **kwargs):
        return self._session.put(f"{self.base_url}{path}", **kwargs)

    def delete(self, path, **kwargs):
        return self._session.delete(f"{self.base_url}{path}", **kwargs)

    def set_role(self, role: str, user_name: str = "User"):
        """Set the identity for subsequent requests.

        The default implementation uses cookies (matching the stub auth
        provider). Override in your adapter if your runtime uses a
        different auth mechanism.
        """
        self._session.cookies.set("termin_role", role)
        self._session.cookies.set("termin_user_name", user_name)


class RuntimeAdapter(ABC):
    """Abstract base class for runtime adapters.

    Implement deploy() and optionally override create_session().
    """

    @abstractmethod
    def deploy(self, fixture_path: Path, app_name: str) -> AppInfo:
        """Deploy a test app and return its base URL.

        Args:
            fixture_path: Path to a .termin.pkg file or IR JSON file.
            app_name: Short name for the app (e.g., "warehouse").

        Returns:
            AppInfo with base_url, parsed IR, and optional cleanup callable.
        """
        ...

    def create_session(self, app_info: AppInfo) -> TerminSession:
        """Create an HTTP session for testing the deployed app.

        Override this if your runtime needs custom session setup
        (e.g., OAuth token acquisition, custom headers).
        """
        return TerminSession(app_info.base_url)

    def deploy_with_agent_mock(self, fixture_path: Path, app_name: str,
                               tool_calls: list[tuple[str, dict]]) -> tuple[AppInfo, list]:
        """Deploy an app with a mock AI provider that executes predetermined tool calls.

        This tests the "back door" — the agent tool API that AI Computes use
        to interact with the runtime. The mock replaces the actual LLM with a
        function that calls execute_tool with the given sequence, capturing results.

        Args:
            fixture_path: Path to a .termin.pkg or IR JSON file.
            app_name: Short name for the app.
            tool_calls: List of (tool_name, tool_input) tuples the mock will execute.

        Returns:
            (AppInfo, tool_results) — the deployed app and a mutable list that will be
            populated with tool call results once the agent Compute fires.
        """
        raise NotImplementedError(
            "Agent tool testing not implemented in this adapter. "
            "Override deploy_with_agent_mock() to support agent conformance tests."
        )

    def load_ir_from_fixture(self, fixture_path: Path) -> dict:
        """Extract IR JSON from a .termin.pkg or raw .json file."""
        if fixture_path.suffix == ".json":
            return json.loads(fixture_path.read_text(encoding="utf-8"))
        # .termin.pkg
        with zipfile.ZipFile(fixture_path, 'r') as zf:
            manifest = json.loads(zf.read("manifest.json"))
            return json.loads(zf.read(manifest["ir"]["entry"]))
