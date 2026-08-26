import re

import pytest
from playwright.sync_api import Page, expect

from helpers.speedify_cli import (
    connect,
    disconnect,
    get_current_server,
    get_state,
    wait_for_state,
)

NOT_CONNECTED_STATE = "LOGGED_IN"

TOGGLE = "#navbar-onoff"
ONOFF = "#onOff"
STATUS_TEXT = "#status-box-ServerButtonTextStatus"
TIMER = ".status-box-ServerButtonTextServer"


def _settle(page: Page, timeout_ms: int = 20_000):
    """Polls until the status text reaches a terminal Connected/Disconnected state.

    The "pending" CSS class alone isn't a reliable settle signal — under load the
    status text can pass through other transitional values (e.g. "Disconnecting")
    without that class being present, so poll the text instead.
    """
    status = page.locator(STATUS_TEXT)
    onoff = page.locator(ONOFF).first
    waited = 0
    last_text = ""
    last_cls: list[str] = []

    # Give Angular a beat to re-render after a click before the first read — otherwise
    # a stale pre-click snapshot can be misread as the new terminal state.
    page.wait_for_timeout(150)
    waited += 150

    while waited < timeout_ms:
        # Read class and text back to back so a caller can't observe a moment where
        # they disagree (class and text don't appear to update in the same render tick).
        last_cls = (onoff.get_attribute("class") or "").split()
        last_text = status.inner_text().strip()
        if last_text in ("Connected", "Disconnected") and "pending" not in last_cls:
            return last_cls, last_text
        page.wait_for_timeout(300)
        waited += 300
    raise AssertionError(
        f"UI never reached a stable terminal state, last class={last_cls} text={last_text!r}"
    )


@pytest.fixture(autouse=True)
def restore_connection():
    was_connected = get_state() == "CONNECTED"
    yield
    if was_connected and get_state() != "CONNECTED":
        connect()
        wait_for_state("CONNECTED", timeout=20)
    elif not was_connected and get_state() == "CONNECTED":
        disconnect()
        wait_for_state(NOT_CONNECTED_STATE, timeout=10)


def test_disconnect_while_already_disconnected_does_not_crash(page: Page):
    disconnect()
    wait_for_state(NOT_CONNECTED_STATE, timeout=10)

    page.goto("/")
    page.wait_for_selector(STATUS_TEXT)
    expect(page.locator(STATUS_TEXT)).to_have_text("Disconnected")

    print("\n[edge] disconnecting again while already disconnected")
    disconnect()
    page.wait_for_timeout(1000)

    assert get_state() == NOT_CONNECTED_STATE
    expect(page.locator(STATUS_TEXT)).to_have_text("Disconnected")
    expect(page.locator("#dashboard")).to_be_attached()
    expect(page.locator("#networksSlider")).to_be_visible()


def test_connect_while_already_connected_remains_stable(page: Page):
    connect()
    wait_for_state("CONNECTED", timeout=20)

    page.goto("/")
    page.wait_for_selector(STATUS_TEXT)
    expect(page.locator(STATUS_TEXT)).to_have_text("Connected")

    print("\n[edge] connecting again while already connected")
    connect()
    page.wait_for_timeout(1000)

    assert get_state() == "CONNECTED"
    expect(page.locator(STATUS_TEXT)).to_have_text("Connected")
    expect(page.locator("#dashboard")).to_be_attached()
    expect(page.locator("#networksSlider")).to_be_visible()


def test_rapid_toggle_during_pending_state_settles_consistently(page: Page):
    disconnect()
    wait_for_state(NOT_CONNECTED_STATE, timeout=10)
    # Give the daemon a moment to fully settle before we start clicking — starting
    # right on the heels of the disconnect call occasionally produced clicks that
    # had no visible effect at all (verified this isn't a UI/render timing issue;
    # the daemon itself didn't register a new connect attempt at those moments).
    page.wait_for_timeout(1000)

    page.goto("/")
    page.wait_for_selector(TOGGLE)

    toggle = page.locator(TOGGLE)
    onoff = page.locator(ONOFF).first

    print("\n[edge] clicking toggle, immediately checking for pending, clicking again")

    def _click_and_read_class():
        toggle.click()
        # A tiny buffer for Angular to re-render after the click; at 0ms the class read
        # still reflects the pre-click state (verified empirically).
        page.wait_for_timeout(150)
        return (onoff.get_attribute("class") or "").split()

    # An off->off click (toggle already back on from something else) is immediate with
    # no pending phase, so retry a few times to reliably land on an actual transition.
    cls_immediately_after: list[str] = []
    for attempt in range(5):
        cls_immediately_after = _click_and_read_class()
        print(f"[edge] attempt {attempt + 1}: class right after click: {cls_immediately_after}")
        if "pending" in cls_immediately_after:
            break
        page.wait_for_timeout(500)

    assert "pending" in cls_immediately_after, (
        f"Expected a pending transition state after retrying, got {cls_immediately_after}"
    )

    toggle.click()

    final_cls, status_text = _settle(page)
    print(f"[edge] settled: class={final_cls} status={status_text!r}")

    if "off" in final_cls:
        assert status_text == "Disconnected"
    else:
        assert status_text == "Connected"


def test_disconnect_wait_then_reconnect_recovers_cleanly(page: Page):
    connect()
    wait_for_state("CONNECTED", timeout=20)

    page.goto("/")
    page.wait_for_selector(STATUS_TEXT)

    print("\n[edge] disconnecting, waiting 10s, reconnecting")
    disconnect()
    wait_for_state(NOT_CONNECTED_STATE, timeout=10)
    expect(page.locator(STATUS_TEXT)).to_have_text("Disconnected")

    page.wait_for_timeout(10_000)

    connect()
    wait_for_state("CONNECTED", timeout=20)

    server_name = get_current_server()["friendlyName"]
    expect(page.locator(STATUS_TEXT)).to_have_text("Connected", timeout=10_000)
    expect(page.locator("#statusBox").first).to_contain_text(server_name, timeout=10_000)
    print(f"[edge] recovered cleanly, connected to {server_name!r}")


def test_connect_disconnect_connect_resets_timer(page: Page):
    connect()
    wait_for_state("CONNECTED", timeout=20)

    page.goto("/")
    page.wait_for_selector(STATUS_TEXT)

    # Let the connection timer accumulate a bit before disconnecting.
    page.wait_for_timeout(4000)
    timer_before = page.locator(TIMER).nth(1).inner_text()
    print(f"\n[edge] timer before disconnect: {timer_before!r}")

    disconnect()
    wait_for_state(NOT_CONNECTED_STATE, timeout=10)

    connect()
    wait_for_state("CONNECTED", timeout=20)
    page.wait_for_timeout(1500)

    timer_after = page.locator(TIMER).nth(1).inner_text()
    print(f"[edge] timer after reconnect: {timer_after!r}")

    match = re.search(r"(\d+):(\d+)", timer_after)
    assert match, f"Could not parse timer text {timer_after!r}"
    minutes, seconds = int(match.group(1)), int(match.group(2))
    assert minutes == 0 and seconds < 10, (
        f"Timer shows {timer_after!r} right after reconnecting — it looks like it "
        "continued from the previous session instead of resetting"
    )
