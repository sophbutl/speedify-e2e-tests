import re

import pytest
from playwright.sync_api import Page, expect

from helpers.speedify_cli import NOT_CONNECTED_STATE, get_current_server, get_state
from helpers.ui_helpers import (
    ONOFF,
    STATUS_TEXT,
    TOGGLE,
    connect_and_wait,
    disconnect_and_wait,
    goto_dashboard,
    wait_for_connection_settle,
)

TIMER = ".status-box-ServerButtonTextServer"


# Verify disconnecting while already disconnected is a harmless no-op
def test_disconnect_while_already_disconnected_does_not_crash(page: Page):
    disconnect_and_wait()

    goto_dashboard(page, wait_for=STATUS_TEXT)
    expect(page.locator(STATUS_TEXT)).to_have_text("Disconnected")

    print("\n[edge] disconnecting again while already disconnected")
    disconnect_and_wait()

    assert get_state() == NOT_CONNECTED_STATE
    expect(page.locator(STATUS_TEXT)).to_have_text("Disconnected")
    expect(page.locator("#dashboard")).to_be_attached()
    expect(page.locator("#networksSlider")).to_be_visible()


# Verify connecting while already connected leaves the UI in a stable connected state
def test_connect_while_already_connected_remains_stable(page: Page):
    connect_and_wait(timeout=20)

    goto_dashboard(page, wait_for=STATUS_TEXT)
    expect(page.locator(STATUS_TEXT)).to_have_text("Connected")

    print("\n[edge] connecting again while already connected")
    connect_and_wait(timeout=20)

    assert get_state() == "CONNECTED"
    expect(page.locator(STATUS_TEXT)).to_have_text("Connected")
    expect(page.locator("#dashboard")).to_be_attached()
    expect(page.locator("#networksSlider")).to_be_visible()


# Verify toggling rapidly during a pending transition still settles to a consistent state
@pytest.mark.slow
def test_rapid_toggle_during_pending_state_settles_consistently(page: Page):
    disconnect_and_wait()
    # Give the daemon a moment to fully settle before we start clicking - starting
    # right on the heels of the disconnect call occasionally produced clicks that
    # had no visible effect at all (verified this isn't a UI/render timing issue;
    # the daemon itself didn't register a new connect attempt at those moments).
    page.wait_for_timeout(1000)

    goto_dashboard(page, wait_for=TOGGLE)

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

    final_cls, status_text = wait_for_connection_settle(page)
    print(f"[edge] settled: class={final_cls} status={status_text!r}")

    if "off" in final_cls:
        assert status_text == "Disconnected"
    else:
        assert status_text == "Connected"


# Verify disconnecting, waiting, then reconnecting recovers cleanly with the correct server
def test_disconnect_wait_then_reconnect_recovers_cleanly(page: Page):
    connect_and_wait(timeout=20)

    goto_dashboard(page, wait_for=STATUS_TEXT)

    print("\n[edge] disconnecting, waiting 10s, reconnecting")
    disconnect_and_wait()
    expect(page.locator(STATUS_TEXT)).to_have_text("Disconnected")

    page.wait_for_timeout(10_000)

    connect_and_wait(timeout=20)

    server_name = get_current_server()["friendlyName"]
    expect(page.locator(STATUS_TEXT)).to_have_text("Connected", timeout=10_000)
    expect(page.locator("#statusBox").first).to_contain_text(server_name, timeout=10_000)
    print(f"[edge] recovered cleanly, connected to {server_name!r}")


# Verify the connection timer resets to zero after a disconnect/reconnect cycle
def test_connect_disconnect_connect_resets_timer(page: Page):
    connect_and_wait(timeout=20)

    goto_dashboard(page, wait_for=STATUS_TEXT)

    # Let the connection timer accumulate a bit before disconnecting.
    page.wait_for_timeout(4000)
    timer_before = page.locator(TIMER).nth(1).inner_text()
    print(f"\n[edge] timer before disconnect: {timer_before!r}")

    disconnect_and_wait()

    connect_and_wait(timeout=20)
    page.wait_for_timeout(1500)

    timer_after = page.locator(TIMER).nth(1).inner_text()
    print(f"[edge] timer after reconnect: {timer_after!r}")

    match = re.search(r"(\d+):(\d+)", timer_after)
    assert match, f"Could not parse timer text {timer_after!r}"
    minutes, seconds = int(match.group(1)), int(match.group(2))
    assert minutes == 0 and seconds < 10, (
        f"Timer shows {timer_after!r} right after reconnecting - it looks like it "
        "continued from the previous session instead of resetting"
    )
