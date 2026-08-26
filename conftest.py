import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.sync_api import Browser, BrowserContext, Page

UI_DIR = "/Applications/Speedify.app/Contents/Resources/ui"
PORT = 8080


@pytest.fixture(scope="session", autouse=True)
def ui_server():
    handler = functools.partial(SimpleHTTPRequestHandler, directory=UI_DIR)
    server = ThreadingHTTPServer(("localhost", PORT), handler)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield

    server.shutdown()
    server.server_close()


@pytest.fixture(scope="session")
def base_url():
    return f"http://localhost:{PORT}"


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    return {
        **browser_type_launch_args,
        "headless": False,
    }


@pytest.fixture(scope="session")
def context(browser: Browser, browser_context_args):
    context = browser.new_context(**browser_context_args)
    yield context
    context.close()


@pytest.fixture(scope="session")
def page(context: BrowserContext):
    page = context.new_page()
    yield page
    page.close()
