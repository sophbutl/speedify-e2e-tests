"""Settings > PREFERENCES group: Language, Window Location, Graph Rotation, and the
Dashboard customization page.

The "Dashboard" row opens a card-customization sub-page - it's a row within
PREFERENCES (confirmed via DOM inspection: unlike "ACCOUNT", "PRIVACY", etc. it
doesn't carry the group-header class or uppercase styling), not a separate top-level
Settings group, despite how it might first read from a flat text dump of the page.

Theme is already covered in tests/test_mac_specific.py and is not repeated here.
"""

from playwright.sync_api import Page, expect

from helpers.ui_helpers import NAV_TABS, click_settings_row, goto_dashboard, is_nav_tab_active, open_settings

DASHBOARD_CARDS = [
    "Registration Reminder",
    "Paired Devices",
    "Streams",
    "Bypass",
    "Bonding Mode",
    "Graph - Networks",
    "Graph - Traffic",
    "Graph - Latency",
    "Graph - Loss",
    "Graph - Local",
    "Statistics",
    "News & Events",
    "Advanced ISP Stats",
    "Starlink Summary",
    "Starlink Dish Orientation",
    "Starlink Connectivity",
]


def _row_value(page: Page, label: str) -> str:
    return (
        page.get_by_text(label, exact=True)
        .last.locator("xpath=following-sibling::*[1]")
        .inner_text()
        .strip()
    )


# Verify the Language row shows its current value and the picker lists all available languages
def test_language_picker_shows_current_value_and_options(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    row_value = _row_value(page, "Language")
    print(f"\n[settings] Language current value: {row_value!r}")
    assert row_value != ""

    click_settings_row(page, "Language")
    expect(page).to_have_url("http://localhost:8080/#/settings/language")
    expect(page.locator("app-settings-choice-row").get_by_text("Auto", exact=True)).to_be_visible()
    expect(
        page.locator("app-settings-choice-row").get_by_text("English / (United States)", exact=True)
    ).to_be_visible()


# Verify switching Language to English and back to Auto leaves the UI fully recovered
def test_changing_language_to_english_and_back_recovers_ui(page: Page):
    try:
        goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
        open_settings(page)
        click_settings_row(page, "Language")

        print("\n[settings] selecting English / (United States)")
        page.locator("app-settings-choice-row").get_by_text("English / (United States)", exact=True).click()
        page.wait_for_timeout(500)

        # The OS is already English (confirmed throughout this whole suite), so
        # switching from "Auto" to an explicit "English" shouldn't visibly change
        # anything - this just confirms the UI stays fully readable/functional.
        goto_dashboard(page, wait_for="#networksSlider")
        expect(page.get_by_role("heading", name="Speedify")).to_be_visible()
        for tab in NAV_TABS:
            expect(page.locator("#networksSlider").get_by_text(tab, exact=True)).to_be_visible()
        print("[settings] UI still fully readable/functional after switching to English")
    finally:
        print("[settings] restoring Language to Auto")
        goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
        open_settings(page)
        click_settings_row(page, "Language")
        page.locator("app-settings-choice-row").get_by_text("Auto", exact=True).click()
        page.wait_for_timeout(500)
        goto_dashboard(page, wait_for="#networksSlider")
        expect(page.get_by_role("heading", name="Speedify")).to_be_visible()


# Verify the Window Location row shows its current value and both available options
def test_window_location_displays_current_value_and_options(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    row_value = _row_value(page, "Window Location")
    print(f"\n[settings] Window Location current value: {row_value!r}")
    assert row_value != ""

    click_settings_row(page, "Window Location")
    expect(page).to_have_url("http://localhost:8080/#/settings/windowLocation")
    for label in ["Docked in Menu Bar", "Floating Window"]:
        expect(page.locator("app-settings-choice-row").get_by_text(label, exact=True)).to_be_visible()


# Note: the exploratory task only asked to "verify current value/behavior displays"
# for Window Location (unlike Transport Mode, Encryption, Graph Rotation, etc., which
# explicitly ask for a toggle-and-restore test) - so no change/restore test is added
# here. DOM inspection also found a real quirk worth flagging for a future session:
# selecting a different option updates the row's value immediately (no reload), but
# the page's own Back button doesn't navigate away afterward (click registers with no
# error, but the URL and DOM never change), and the choice itself doesn't survive a
# full page reload either - unlike every other setting covered in this suite.


# Verify the Graph Rotation row displays its current value
def test_graph_rotation_displays_current_value(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    row_value = _row_value(page, "Graph Rotation")
    print(f"\n[settings] Graph Rotation current value: {row_value!r}")
    assert row_value in ("On", "Off")


# Verify turning Graph Rotation on actually rotates the active dashboard tab over time,
# then restores the original setting
def test_toggling_graph_rotation_and_observing_dashboard_behavior(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    original = _row_value(page, "Graph Rotation")
    print(f"\n[settings] original Graph Rotation: {original!r}")
    try:
        if original != "On":
            click_settings_row(page, "Graph Rotation")
            page.locator("app-settings-choice-row").get_by_text("On", exact=True).click()
            page.wait_for_timeout(500)
            print("[settings] turned Graph Rotation On")

        goto_dashboard(page, wait_for="#networksSlider")
        nav = page.locator("#networksSlider")
        active_before = next(t for t in NAV_TABS if is_nav_tab_active(nav.get_by_text(t, exact=True)))
        print(f"[settings] active tab before waiting: {active_before!r}")

        # The app's own description says graphs rotate "every 20 seconds" - poll for
        # up to 30s rather than sleeping a fixed amount, in case it's not exact.
        rotated = False
        for i in range(30):
            page.wait_for_timeout(1000)
            active_now = next(
                (t for t in NAV_TABS if is_nav_tab_active(nav.get_by_text(t, exact=True))), None
            )
            if (i + 1) % 5 == 0:
                print(f"[settings]   after {i + 1}s: active tab = {active_now!r}")
            if active_now and active_now != active_before:
                rotated = True
                print(f"[settings] tab auto-rotated to {active_now!r} after {i + 1}s")
                break
        assert rotated, f"Active tab never changed from {active_before!r} within 30s with Graph Rotation On"
    finally:
        goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
        open_settings(page)
        click_settings_row(page, "Graph Rotation")
        page.locator("app-settings-choice-row").get_by_text(original, exact=True).click()
        page.wait_for_timeout(500)
        # Re-open Settings fresh rather than using close_settings()/Back to return to
        # the list: while still on the Graph Rotation sub-page, "Graph Rotation"
        # resolves to the page title instead of a row (no following-sibling value,
        # read back ""), and this page's Back button was found not to reliably
        # navigate away in this harness (click registers, URL doesn't change) - a
        # fresh reload sidesteps both. Graph Rotation's value does survive a reload
        # (confirmed above, unlike Window Location), so this is safe here.
        goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
        open_settings(page)
        restored = _row_value(page, "Graph Rotation")
        print(f"[settings] restored Graph Rotation: {restored!r}")
        assert restored == original, f"Failed to restore Graph Rotation: {restored!r} != {original!r}"


# Verify the Dashboard customization page lists all expected cards
def test_dashboard_customization_page_lists_expected_cards(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    click_settings_row(page, "Dashboard")
    expect(page).to_have_url("http://localhost:8080/#/settings/dashboardSettings")

    for card in DASHBOARD_CARDS:
        expect(page.get_by_text(card, exact=True).last).to_be_visible()
    print(f"\n[settings] all {len(DASHBOARD_CARDS)} dashboard cards are listed")


# Verify toggling a dashboard card's visibility switch updates it, and restores cleanly
def test_toggling_a_dashboard_card_updates_and_restores(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    click_settings_row(page, "Dashboard")

    toggle = page.locator('[role="switch"][aria-label="News & Events"]')
    expect(toggle).to_be_visible()
    original = toggle.get_attribute("aria-checked")
    print(f"\n[settings] News & Events card aria-checked before: {original!r}")
    try:
        toggle.click()
        page.wait_for_timeout(400)
        after = toggle.get_attribute("aria-checked")
        print(f"[settings] aria-checked after toggle: {after!r}")
        assert after != original, "Toggling the News & Events card didn't change its state"
    finally:
        # Some dashboard cards (News & Events included) only actually render on the
        # dashboard when they have content to show - confirmed via this card's own
        # description ("Some cards will only show when they have data to present") -
        # so the toggle's own aria-checked state is verified directly here rather than
        # a downstream dashboard appearance, which isn't reliably observable for it.
        toggle2 = page.locator('[role="switch"][aria-label="News & Events"]')
        current = toggle2.get_attribute("aria-checked")
        if current != original:
            toggle2.click()
            page.wait_for_timeout(400)
        restored = toggle2.get_attribute("aria-checked")
        print(f"[settings] restored aria-checked: {restored!r}")
        assert restored == original, f"Failed to restore card toggle: {restored!r} != {original!r}"
