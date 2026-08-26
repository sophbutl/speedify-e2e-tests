from playwright.sync_api import Page, expect

from helpers.speedify_cli import NOT_CONNECTED_STATE, get_current_server, get_settings, get_state, set_mode, wait_for_state
from helpers.ui_helpers import (
    STATUS_TEXT,
    TOGGLE,
    connect_and_wait,
    disconnect_and_wait,
    goto_dashboard,
    open_settings,
    wait_for_connection_settle,
)


# Verify the toggle's CSS class and the status text always agree, across repeated clicks
def test_toggle_class_and_status_text_always_agree(page: Page):
    goto_dashboard(page, wait_for=TOGGLE)

    print("\n[state] clicking toggle 5 times, checking agreement after each settle")
    for i in range(5):
        page.locator(TOGGLE).click()
        cls, text = wait_for_connection_settle(page)
        print(f"[state] click {i + 1}/5 -> class={cls} status={text!r}")

        if "off" in cls:
            assert text == "Disconnected", f"class={cls} but status text is {text!r}"
        else:
            assert text == "Connected", f"class={cls} but status text is {text!r}"


# Verify connecting via the CLI is reflected as "Connected" in the UI
def test_connect_via_cli_shows_connected_in_ui(page: Page):
    disconnect_and_wait()

    goto_dashboard(page, wait_for=STATUS_TEXT)
    expect(page.locator(STATUS_TEXT)).to_have_text("Disconnected")

    connect_and_wait(timeout=20)

    expect(page.locator(STATUS_TEXT)).to_have_text("Connected", timeout=10_000)


# Verify disconnecting via the CLI is reflected as "Disconnected" in the UI
def test_disconnect_via_cli_shows_disconnected_in_ui(page: Page):
    connect_and_wait(timeout=20)

    goto_dashboard(page, wait_for=STATUS_TEXT)
    expect(page.locator(STATUS_TEXT)).to_have_text("Connected")

    disconnect_and_wait()

    expect(page.locator(STATUS_TEXT)).to_have_text("Disconnected", timeout=10_000)


# Verify connecting via the UI toggle is reflected as CONNECTED in the CLI
def test_connect_via_ui_toggle_shows_connected_in_cli(page: Page):
    disconnect_and_wait()

    goto_dashboard(page, wait_for=TOGGLE)
    page.locator(TOGGLE).click()
    wait_for_connection_settle(page)

    # The default toggle connects to the "best" server, which the daemon resolves via
    # its own ongoing auto-selection (state stays AUTO_CONNECTING for a while). The UI
    # shows "Connected" as soon as a usable tunnel exists, well before that daemon-side
    # optimization finishes - so give the CLI a generous window to catch up rather than
    # treating this lag as a bug.
    wait_for_state("CONNECTED", timeout=60)


# Verify disconnecting via the UI toggle is reflected as not-connected in the CLI
def test_disconnect_via_ui_toggle_shows_not_connected_in_cli(page: Page):
    connect_and_wait(timeout=20)

    goto_dashboard(page, wait_for=TOGGLE)
    page.locator(TOGGLE).click()
    wait_for_connection_settle(page)

    assert get_state() == NOT_CONNECTED_STATE


# Verify the connected server's name is shown in the status box after connecting
def test_server_name_shown_after_connecting(page: Page):
    connect_and_wait(timeout=20)
    server_name = get_current_server()["friendlyName"]

    goto_dashboard(page, wait_for=STATUS_TEXT)

    status_box = page.locator("#statusBox").first
    expect(status_box).to_contain_text(server_name, timeout=10_000)


# Verify the server name is hidden and replaced by "Tap to Connect" after disconnecting
def test_server_name_hidden_after_disconnecting(page: Page):
    connect_and_wait(timeout=20)
    server_name = get_current_server()["friendlyName"]

    goto_dashboard(page, wait_for=STATUS_TEXT)
    status_box = page.locator("#statusBox").first
    expect(status_box).to_contain_text(server_name)

    disconnect_and_wait()

    expect(status_box).not_to_contain_text(server_name, timeout=10_000)
    expect(status_box).to_contain_text("Tap to Connect")


# Verify changing the bonding mode via the UI is reflected in the CLI settings
def test_change_bonding_mode_via_ui_updates_cli(page: Page):
    original_mode = get_settings()["bondingMode"]
    try:
        goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
        open_settings(page)
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


# Verify changing the bonding mode via the CLI is reflected in the UI after a reload
def test_change_bonding_mode_via_cli_reflects_in_ui_after_reload(page: Page):
    original_mode = get_settings()["bondingMode"]
    # "streaming" in the CLI maps to the UI's "Speed" choice plus its separate
    # "Enhance Streaming" toggle, which collapses to "Speed +" in the settings row.
    expected_row_text = {"speed": "Speed", "streaming": "Speed +", "redundant": "Redundant"}

    try:
        for mode in ["speed", "redundant", "streaming"]:
            set_mode(mode)
            goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
            open_settings(page)
            mode_row = page.get_by_text("Bonding Mode", exact=True)
            expect(mode_row).to_be_visible()

            row_value = mode_row.locator("xpath=following-sibling::*[1]")
            expect(row_value).to_have_text(expected_row_text[mode], timeout=10_000)
            print(f"[state] CLI mode={mode!r} -> UI shows {row_value.inner_text()!r}")
    finally:
        set_mode(original_mode)
