import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.sync_api import Browser, BrowserContext

from helpers.speedify_cli import get_state
from helpers.ui_helpers import connect_and_wait, disconnect_and_wait

# The real Speedify app ships its UI as a static bundle inside the .app; we serve that
# same bundle over plain HTTP so Playwright can drive it like any other web page.
UI_DIR = "/Applications/Speedify.app/Contents/Resources/ui"
PORT = 8080


@pytest.fixture(scope="session", autouse=True)
def ui_server():
    """Serves the Speedify UI bundle on localhost for the whole test session."""
    handler = functools.partial(SimpleHTTPRequestHandler, directory=UI_DIR)
    server = ThreadingHTTPServer(("localhost", PORT), handler)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield

    server.shutdown()
    server.server_close()


@pytest.fixture(scope="session")
def base_url():
    """Base URL pytest-playwright uses for relative page.goto("/") calls."""
    return f"http://localhost:{PORT}"


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """Runs headed (not headless) since tests interact with the real local VPN daemon."""
    return {
        **browser_type_launch_args,
        "headless": False,
    }


@pytest.fixture(scope="session")
def context(browser: Browser, browser_context_args):
    """A single browser context shared across the whole test session."""
    context = browser.new_context(**browser_context_args)
    yield context
    context.close()


@pytest.fixture(scope="session")
def page(context: BrowserContext):
    """A single page shared across the whole test session (reuses `context` above)."""
    page = context.new_page()
    yield page
    page.close()


@pytest.fixture(autouse=True)
def restore_connection_state():
    """Restores the daemon's connect/disconnect state after every test.

    Runs for every test in the suite so that a test which connects or disconnects
    as part of its setup or assertions never leaks that change into the next test.
    """
    was_connected = get_state() == "CONNECTED"
    yield
    if was_connected and get_state() != "CONNECTED":
        connect_and_wait()
    elif not was_connected and get_state() == "CONNECTED":
        disconnect_and_wait()
