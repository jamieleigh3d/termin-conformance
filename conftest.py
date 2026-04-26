"""Conformance suite pytest configuration.

Provides session-scoped fixtures for each test app. Each app is deployed
once and reused across all tests in the session.

To use a different adapter, set the TERMIN_ADAPTER environment variable
or modify the _get_adapter() function below.
"""

import os
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
# v0.9: cascade-grammar test fixtures live in their own directory so
# they don't show up next to production-shaped example fixtures.
CASCADE_FIXTURES_DIR = Path(__file__).parent / "fixtures-cascade"


def _get_adapter():
    """Return the runtime adapter to use for testing.

    Override this to use a different adapter:
      export TERMIN_ADAPTER=reference   # default
      export TERMIN_ADAPTER=template    # your custom adapter
    """
    adapter_name = os.environ.get("TERMIN_ADAPTER", "reference")

    if adapter_name == "reference":
        from adapter_reference import ReferenceAdapter
        return ReferenceAdapter()
    elif adapter_name == "served-reference":
        # Like "reference" but serves each app on a real localhost port
        # so Playwright / visual-regression tests can navigate to it.
        from adapter_served_reference import ServedReferenceAdapter
        return ServedReferenceAdapter()
    elif adapter_name == "template":
        from adapter_template import MyRuntimeAdapter
        return MyRuntimeAdapter()
    else:
        raise ValueError(
            f"Unknown adapter: {adapter_name}. "
            "Set TERMIN_ADAPTER=reference | served-reference | template.")


_adapter = _get_adapter()
_deployed_apps = {}


def _get_app_session(app_name: str, cascade: bool = False):
    """Deploy an app (or reuse cached deployment) and return a session.

    If `cascade` is True, the fixture is looked up in fixtures-cascade/
    instead of fixtures/. v0.9 cascade-grammar test fixtures live there
    so they don't pollute the production example fixture list.
    """
    if app_name not in _deployed_apps:
        base = CASCADE_FIXTURES_DIR if cascade else FIXTURES_DIR
        fixture_path = base / f"{app_name}.termin.pkg"
        if not fixture_path.exists():
            raise FileNotFoundError(f"No .termin.pkg fixture for '{app_name}' in {base}")

        app_info = _adapter.deploy(fixture_path, app_name)
        session = _adapter.create_session(app_info)
        _deployed_apps[app_name] = (app_info, session)

    return _deployed_apps[app_name]


# ── Session-scoped fixtures: each app deployed once ──

@pytest.fixture(scope="session")
def warehouse():
    app_info, session = _get_app_session("warehouse")
    yield session
    if app_info.cleanup:
        app_info.cleanup()

@pytest.fixture(scope="session")
def helpdesk():
    app_info, session = _get_app_session("helpdesk")
    yield session
    if app_info.cleanup:
        app_info.cleanup()

@pytest.fixture(scope="session")
def projectboard():
    app_info, session = _get_app_session("projectboard")
    yield session
    if app_info.cleanup:
        app_info.cleanup()

@pytest.fixture(scope="session")
def hello():
    app_info, session = _get_app_session("hello")
    yield session
    if app_info.cleanup:
        app_info.cleanup()

@pytest.fixture(scope="session")
def hello_user():
    app_info, session = _get_app_session("hello_user")
    yield session
    if app_info.cleanup:
        app_info.cleanup()

@pytest.fixture(scope="session")
def compute_demo():
    app_info, session = _get_app_session("compute_demo")
    yield session
    if app_info.cleanup:
        app_info.cleanup()

@pytest.fixture(scope="session")
def hrportal():
    app_info, session = _get_app_session("hrportal")
    yield session
    if app_info.cleanup:
        app_info.cleanup()

@pytest.fixture(scope="session")
def agent_simple():
    app_info, session = _get_app_session("agent_simple")
    yield session
    if app_info.cleanup:
        app_info.cleanup()

@pytest.fixture(scope="session")
def agent_chatbot():
    app_info, session = _get_app_session("agent_chatbot")
    yield session
    if app_info.cleanup:
        app_info.cleanup()

@pytest.fixture(scope="session")
def channel_simple():
    app_info, session = _get_app_session("channel_simple")
    yield session
    if app_info.cleanup:
        app_info.cleanup()

@pytest.fixture(scope="session")
def channel_demo():
    app_info, session = _get_app_session("channel_demo")
    yield session
    if app_info.cleanup:
        app_info.cleanup()

@pytest.fixture(scope="session")
def security_agent():
    app_info, session = _get_app_session("security_agent")
    yield session
    if app_info.cleanup:
        app_info.cleanup()

@pytest.fixture(scope="session")
def approval_workflow():
    """v0.9 fixture — exercises multi-state-machine per content.
    Two state machines on `documents`: lifecycle + approval_status.
    """
    app_info, session = _get_app_session("approval_workflow")
    yield session
    if app_info.cleanup:
        app_info.cleanup()


# ── v0.9 cascade-grammar test fixtures ──

@pytest.fixture(scope="session")
def cascade_demo():
    """v0.9 fixture — three contents demonstrating both cascade modes:
    parents, cascade children (cascade on delete), restrict children
    (restrict on delete).
    """
    app_info, session = _get_app_session("cascade_demo", cascade=True)
    yield session
    if app_info.cleanup:
        app_info.cleanup()

@pytest.fixture(scope="session")
def cascade_self_ref():
    """v0.9 fixture — tree nodes with self-cascade-on-delete reference."""
    app_info, session = _get_app_session("cascade_self_ref", cascade=True)
    yield session
    if app_info.cleanup:
        app_info.cleanup()

@pytest.fixture(scope="session")
def cascade_optional():
    """v0.9 fixture — non-required cascade reference for NULL-FK behavior."""
    app_info, session = _get_app_session("cascade_optional", cascade=True)
    yield session
    if app_info.cleanup:
        app_info.cleanup()

@pytest.fixture(scope="session")
def cascade_multihop_ok():
    """v0.9 fixture — A → B → C all cascade. Multi-hop propagation."""
    app_info, session = _get_app_session("cascade_multihop_ok", cascade=True)
    yield session
    if app_info.cleanup:
        app_info.cleanup()


# ── IR fixtures for introspection ──

@pytest.fixture(scope="session")
def warehouse_ir():
    app_info, _ = _get_app_session("warehouse")
    return app_info.ir

@pytest.fixture(scope="session")
def helpdesk_ir():
    app_info, _ = _get_app_session("helpdesk")
    return app_info.ir

@pytest.fixture(scope="session")
def projectboard_ir():
    app_info, _ = _get_app_session("projectboard")
    return app_info.ir

@pytest.fixture(scope="session")
def hrportal_ir():
    app_info, _ = _get_app_session("hrportal")
    return app_info.ir

@pytest.fixture(scope="session")
def agent_simple_ir():
    app_info, _ = _get_app_session("agent_simple")
    return app_info.ir

@pytest.fixture(scope="session")
def agent_chatbot_ir():
    app_info, _ = _get_app_session("agent_chatbot")
    return app_info.ir

@pytest.fixture(scope="session")
def channel_simple_ir():
    app_info, _ = _get_app_session("channel_simple")
    return app_info.ir

@pytest.fixture(scope="session")
def channel_demo_ir():
    app_info, _ = _get_app_session("channel_demo")
    return app_info.ir

@pytest.fixture(scope="session")
def security_agent_ir():
    app_info, _ = _get_app_session("security_agent")
    return app_info.ir

@pytest.fixture(scope="session")
def hello_ir():
    app_info, _ = _get_app_session("hello")
    return app_info.ir

@pytest.fixture(scope="session")
def hello_user_ir():
    app_info, _ = _get_app_session("hello_user")
    return app_info.ir

@pytest.fixture(scope="session")
def compute_demo_ir():
    app_info, _ = _get_app_session("compute_demo")
    return app_info.ir

@pytest.fixture(scope="session")
def approval_workflow_ir():
    app_info, _ = _get_app_session("approval_workflow")
    return app_info.ir


# ── Playwright browser fixtures (opt-in) ────────────────────────────
#
# Browser-driven conformance tests use these fixtures. They skip
# gracefully when:
#   - The Playwright package is not installed, OR
#   - The adapter's session does not expose a real HTTP URL (the
#     in-process reference adapter returns base_url="http://testserver"
#     which is not reachable by a browser).
#
# To run browser tests:
#   pip install playwright
#   python -m playwright install chromium
#   TERMIN_ADAPTER=served-reference python -m pytest tests/test_*browser*.py -v

def _playwright_available():
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.fixture(scope="session")
def _chromium():
    """Launch a headless Chromium browser once per session."""
    if not _playwright_available():
        pytest.skip("playwright not installed")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def browser_context(_chromium):
    """A fresh Chromium context per test — no state bleed between tests."""
    context = _chromium.new_context()
    yield context
    context.close()


@pytest.fixture
def browser_page(browser_context):
    """A fresh page in a fresh context per test."""
    page = browser_context.new_page()
    yield page
    page.close()


def _require_served_url(session):
    """Skip the test if this adapter's base_url isn't a real HTTP URL.
    A browser needs to navigate to it. Used by browser-test fixtures."""
    base = getattr(session, "base_url", "")
    if not base or base.startswith("http://testserver"):
        pytest.skip(
            "browser tests require TERMIN_ADAPTER=served-reference "
            "(or another adapter that serves on a real port)")
