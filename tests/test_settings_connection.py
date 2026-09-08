"""Settings > CONNECTION SETTINGS group: Pair & Share, Performance Tests, Starlink
Control, plus Secondary Threshold.

Secondary Threshold actually lives in the MODE group in the live DOM (right below
Bonding Mode), not CONNECTION SETTINGS - grouped here anyway to match the file
organization the exploratory session asked for.
"""

from playwright.sync_api import Page, expect

from helpers.speedify_cli import get_settings, set_secondary_threshold
from helpers.ui_helpers import click_settings_row, goto_dashboard, open_settings


# Verify the Secondary Threshold row displays its current value
def test_secondary_threshold_displays_current_value(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    row_value = (
        page.get_by_text("Secondary Threshold", exact=True)
        .last.locator("xpath=following-sibling::*[1]")
        .inner_text()
        .strip()
    )
    print(f"\n[settings] Secondary Threshold current value: {row_value!r}")
    assert row_value != "" and ("Mbps" in row_value or "Gbps" in row_value)


# Verify changing the Secondary Threshold via the UI's dropdown updates the CLI's
# priorityOverflowThreshold, and restores cleanly
def test_changing_secondary_threshold_updates_and_restores(page: Page):
    original_mbps = get_settings()["priorityOverflowThreshold"]
    print(f"\n[settings] original priorityOverflowThreshold: {original_mbps}")
    try:
        goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
        open_settings(page)
        click_settings_row(page, "Secondary Threshold")
        expect(page).to_have_url("http://localhost:8080/#/settings/secondaryThreshold")

        # This is a native <select>, not an app-settings-choice-row like most other
        # settings pickers (verified via DOM inspection).
        select = page.locator("select").last
        options = select.locator("option").evaluate_all(
            "opts => opts.map(o => ({value: o.value, text: o.textContent.trim()}))"
        )
        current_value = select.input_value()
        target = next(o for o in options if o["value"] != current_value)
        print(f"[settings] changing from {current_value!r} to {target['value']!r} ({target['text']!r})")

        select.select_option(value=target["value"])
        page.wait_for_timeout(500)

        new_value = get_settings()["priorityOverflowThreshold"]
        print(f"[settings] CLI priorityOverflowThreshold after change: {new_value}")
        assert new_value == float(target["value"]), (
            f"CLI priorityOverflowThreshold ({new_value}) doesn't match the selected option "
            f"({target['value']!r})"
        )
    finally:
        set_secondary_threshold(int(original_mbps))
        restored = get_settings()["priorityOverflowThreshold"]
        print(f"[settings] restored priorityOverflowThreshold: {restored}")
        assert restored == original_mbps, f"Failed to restore threshold: {restored} != {original_mbps}"


# Verify the Pair & Share row displays its page - deeper interaction needs a real peer
# device, so this only confirms the page itself renders
def test_pair_and_share_row_displays(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    click_settings_row(page, "Pair & Share")
    expect(page).to_have_url("http://localhost:8080/#/settings/pairAndShare")
    expect(page.get_by_text("Pair & Share", exact=True).last).to_be_visible()
    expect(page.get_by_text("Display Name", exact=True)).to_be_visible()


# Verify the Performance Tests row displays without running an actual speed/livestream test
def test_performance_tests_row_displays(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    click_settings_row(page, "Performance Tests")
    expect(page).to_have_url("http://localhost:8080/#/settings/testSpeed")
    expect(page.get_by_text("Start Single Speed Test", exact=True)).to_be_visible()
    # Never click "Start ... Test" - these use real bandwidth/data against real servers.


# Verify the Starlink Control row displays - skips deep interaction, which needs real hardware
def test_starlink_control_row_displays(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    click_settings_row(page, "Starlink Control")
    expect(page).to_have_url("http://localhost:8080/#/settings/starlinkControl")
    # "Bonding Alignment" appears twice (a row label and a <b> in the description
    # text below it) - .first avoids a strict-mode violation.
    expect(page.get_by_text("Bonding Alignment", exact=True).first).to_be_visible()
