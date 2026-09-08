"""Settings > SESSION SETTINGS group: Transport Mode, Streaming Prioritization.

Streaming Prioritization turned out (via DOM inspection) not to be a simple on/off
toggle - it's a domain/URL management page (add streaming destinations to prioritize),
more like Firewall/Port Forwarding than a Bonding-Mode-style choice row. It's covered
here as a verify-only test for that reason; nothing is added, removed, or toggled.
"""

from playwright.sync_api import Page, expect

from helpers.speedify_cli import get_settings, set_transport_mode
from helpers.ui_helpers import click_settings_row, goto_dashboard, open_settings

TRANSPORT_UI_TO_CLI = {
    "Auto (Recommended)": "auto",
    "UDP": "udp",
    "TCP Multiple": "tcp-multi",
    "TCP": "tcp",
    "HTTPS": "https",
}


# Verify the Transport Mode row displays its current value and all available options
def test_transport_mode_displays_current_value_and_options(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    click_settings_row(page, "Transport Mode")
    expect(page).to_have_url("http://localhost:8080/#/settings/transportMode")

    for label in TRANSPORT_UI_TO_CLI:
        expect(page.locator("app-settings-choice-row").get_by_text(label, exact=True)).to_be_visible()


# Verify changing Transport Mode via the UI updates the CLI, for every available option
def test_changing_transport_mode_updates_and_restores(page: Page):
    original_mode = get_settings()["transportMode"]
    print(f"\n[settings] original transportMode: {original_mode!r}")
    try:
        for label, cli_value in TRANSPORT_UI_TO_CLI.items():
            print(f"[settings]   -> {label} ({cli_value})")
            goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
            open_settings(page)
            click_settings_row(page, "Transport Mode")
            page.locator("app-settings-choice-row").get_by_text(label, exact=True).click()
            page.wait_for_timeout(500)

            new_mode = get_settings()["transportMode"]
            print(f"[settings]      CLI transportMode is now {new_mode!r}")
            assert new_mode == cli_value, (
                f"Selecting {label!r} gave CLI mode {new_mode!r}, expected {cli_value!r}"
            )
    finally:
        set_transport_mode(original_mode)
        restored = get_settings()["transportMode"]
        print(f"[settings] restored transportMode: {restored!r}")
        assert restored == original_mode, f"Failed to restore transportMode: {restored!r} != {original_mode!r}"


# Verify the Streaming Prioritization row displays its (domain-list) page, unmodified -
# DOM inspection showed this isn't a toggle, so nothing is added or removed here
def test_streaming_prioritization_row_displays(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    click_settings_row(page, "Streaming Prioritization")
    expect(page).to_have_url("http://localhost:8080/#/settings/streamingPriorities")
    expect(page.get_by_text("Streaming Prioritization", exact=True).last).to_be_visible()
