import pytest
from playwright.sync_api import Page, expect

from helpers.speedify_cli import (
    connect,
    disconnect,
    get_current_server,
    get_settings,
    get_state,
    set_mode,
    wait_for_state,
)

# The daemon's "not connected" state is reported as LOGGED_IN, not a literal
# "DISCONNECTED" state string (verified against the real CLI output).
NOT_CONNECTED_STATE = "LOGGED_IN"

TOGGLE = "#navbar-onoff"
ONOFF = "#onOff"
STATUS_TEXT = "#status-box-ServerButtonTextStatus"


def _ui_settle(page: Page, timeout_ms: int = 20_000):
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
        # they disagree (this account can auto-reconnect quickly, and the two don't
        # appear to update in the same Angular render tick).
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


def test_toggle_class_and_status_text_always_agree(page: Page):
    page.goto("/")
    page.wait_for_selector(TOGGLE)

    status = page.locator(STATUS_TEXT)

    print("\n[state] clicking toggle 5 times, checking agreement after each settle")
    for i in range(5):
        page.locator(TOGGLE).click()
        cls, text = _ui_settle(page)
        print(f"[state] click {i + 1}/5 -> class={cls} status={text!r}")

        if "off" in cls:
            assert text == "Disconnected", f"class={cls} but status text is {text!r}"
        else:
            assert text == "Connected", f"class={cls} but status text is {text!r}"


def test_connect_via_cli_shows_connected_in_ui(page: Page):
    disconnect()
    wait_for_state(NOT_CONNECTED_STATE, timeout=10)

    page.goto("/")
    page.wait_for_selector(STATUS_TEXT)
    expect(page.locator(STATUS_TEXT)).to_have_text("Disconnected")

    connect()
    wait_for_state("CONNECTED", timeout=20)

    expect(page.locator(STATUS_TEXT)).to_have_text("Connected", timeout=10_000)


def test_disconnect_via_cli_shows_disconnected_in_ui(page: Page):
    connect()
    wait_for_state("CONNECTED", timeout=20)

    page.goto("/")
    page.wait_for_selector(STATUS_TEXT)
    expect(page.locator(STATUS_TEXT)).to_have_text("Connected")

    disconnect()
    wait_for_state(NOT_CONNECTED_STATE, timeout=10)

    expect(page.locator(STATUS_TEXT)).to_have_text("Disconnected", timeout=10_000)


def test_connect_via_ui_toggle_shows_connected_in_cli(page: Page):
    disconnect()
    wait_for_state(NOT_CONNECTED_STATE, timeout=10)

    page.goto("/")
    page.wait_for_selector(TOGGLE)
    page.locator(TOGGLE).click()
    _ui_settle(page)

    # The default toggle connects to the "best" server, which the daemon resolves via
    # its own ongoing auto-selection (state stays AUTO_CONNECTING for a while). The UI
    # shows "Connected" as soon as a usable tunnel exists, well before that daemon-side
    # optimization finishes — so give the CLI a generous window to catch up rather than
    # treating this lag as a bug.
    wait_for_state("CONNECTED", timeout=60)


def test_disconnect_via_ui_toggle_shows_not_connected_in_cli(page: Page):
    connect()
    wait_for_state("CONNECTED", timeout=20)

    page.goto("/")
    page.wait_for_selector(TOGGLE)
    page.locator(TOGGLE).click()
    _ui_settle(page)

    assert get_state() == NOT_CONNECTED_STATE


def test_server_name_shown_after_connecting(page: Page):
    connect()
    wait_for_state("CONNECTED", timeout=20)
    server_name = get_current_server()["friendlyName"]

    page.goto("/")
    page.wait_for_selector(STATUS_TEXT)

    status_box = page.locator("#statusBox").first
    expect(status_box).to_contain_text(server_name, timeout=10_000)


def test_server_name_hidden_after_disconnecting(page: Page):
    connect()
    wait_for_state("CONNECTED", timeout=20)
    server_name = get_current_server()["friendlyName"]

    page.goto("/")
    page.wait_for_selector(STATUS_TEXT)
    status_box = page.locator("#statusBox").first
    expect(status_box).to_contain_text(server_name)

    disconnect()
    wait_for_state(NOT_CONNECTED_STATE, timeout=10)

    expect(status_box).not_to_contain_text(server_name, timeout=10_000)
    expect(status_box).to_contain_text("Tap to Connect")


def test_change_bonding_mode_via_ui_updates_cli(page: Page):
    original_mode = get_settings()["bondingMode"]
    try:
        page.goto("/")
        page.wait_for_selector('button[aria-label="Settings Button"]')
        page.locator('button[aria-label="Settings Button"]').click()
        mode_row = page.get_by_text("Bonding Mode", exact=True)
        expect(mode_row).to_be_visible()
        mode_row.click()

        redundant_choice = page.locator("app-settings-choice-row").get_by_text(
            "Redundant", exact=True
        )
        expect(redundant_choice).to_be_visible()
        redundant_choice.click()
        page.wait_for_timeout(500)
        # Redundant mode shows a confirmation popup before it takes effect.
        page.locator(".pa-popup-card").get_by_text("Enable", exact=True).click()
        page.wait_for_timeout(1000)

        assert get_settings()["bondingMode"] == "redundant"
    finally:
        set_mode(original_mode)


def test_change_bonding_mode_via_cli_reflects_in_ui_after_reload(page: Page):
    original_mode = get_settings()["bondingMode"]
    # "streaming" in the CLI maps to the UI's "Speed" choice plus its separate
    # "Enhance Streaming" toggle, which collapses to "Speed +" in the settings row.
    expected_row_text = {"speed": "Speed", "streaming": "Speed +", "redundant": "Redundant"}

    try:
        for mode in ["speed", "redundant", "streaming"]:
            set_mode(mode)
            page.goto("/")
            page.wait_for_selector('button[aria-label="Settings Button"]')
            page.locator('button[aria-label="Settings Button"]').click()
            mode_row = page.get_by_text("Bonding Mode", exact=True)
            expect(mode_row).to_be_visible()

            row_value = mode_row.locator("xpath=following-sibling::*[1]")
            expect(row_value).to_have_text(expected_row_text[mode], timeout=10_000)
            print(f"[state] CLI mode={mode!r} -> UI shows {row_value.inner_text()!r}")
    finally:
        set_mode(original_mode)
