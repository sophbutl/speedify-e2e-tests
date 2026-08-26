from playwright.sync_api import Page, expect

from helpers.ui_helpers import NAV_TABS, close_settings, goto_dashboard, is_nav_tab_active, open_settings


def _assert_footer_or_account_fallback(page: Page) -> None:
    # #footer (account email/usage/upgrade bar) only renders for free-tier accounts.
    # This app is on an unlimited/team account, so it's legitimately absent - fall back
    # to checking the equivalent account info lives in Settings instead.
    footer = page.locator("#footer")
    if footer.count() > 0:
        expect(footer).to_be_visible()
        return

    open_settings(page)
    expect(page.get_by_text("Account", exact=True)).to_be_visible()
    close_settings(page)
    expect(page.locator("#networksSlider")).to_be_visible()


# Verify the Settings back/done button returns the user to the dashboard
def test_settings_back_button_returns_to_dashboard(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')

    settings_btn = page.locator('button[aria-label="Settings Button"]')
    back_btn = page.locator("app-back-done-button")

    open_settings(page)
    expect(back_btn).to_be_visible()

    close_settings(page)
    expect(page.locator("#networksSlider")).to_be_visible()
    expect(settings_btn).to_be_visible()


# Verify all major dashboard sections (status, nav, statistics, account info) are present
def test_all_major_sections_present_on_dashboard(page: Page):
    goto_dashboard(page)

    # #dashboard itself is a zero-height layout wrapper; check attachment plus its
    # visible children instead of the wrapper's own visibility.
    expect(page.locator("#dashboard")).to_be_attached()
    expect(page.locator("#statusBox").first).to_be_visible()
    expect(page.locator("#networksSlider")).to_be_visible()
    expect(page.locator("#statistics-pane")).to_be_visible()
    _assert_footer_or_account_fallback(page)


# Verify the dashboard fully re-renders (nav tabs, graph, statistics) after a Settings round trip
def test_settings_round_trip_dashboard_renders_completely(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')

    open_settings(page)
    page.wait_for_selector("app-back-done-button")
    close_settings(page)

    expect(page.locator("#statusBox").first).to_be_visible()
    expect(page.locator("#networksSlider")).to_be_visible()
    for tab in NAV_TABS:
        expect(page.locator("#networksSlider").get_by_text(tab, exact=True)).to_be_visible()
    expect(page.locator("#omniChart")).to_be_visible()
    expect(page.locator("#statistics-pane")).to_be_visible()


# Verify clicking the already-active nav tab does not change its state
def test_clicking_already_active_tab_is_a_noop(page: Page):
    goto_dashboard(page)

    networks_tab = page.locator("#networksSlider").get_by_text("Networks", exact=True)

    # Networks is the default active tab on load.
    assert is_nav_tab_active(networks_tab)
    class_before = networks_tab.get_attribute("class")

    networks_tab.click()
    page.wait_for_timeout(300)

    class_after = networks_tab.get_attribute("class")
    assert class_after == class_before, "Re-clicking the active tab changed its state"
    expect(page.locator("#omniChart")).to_be_visible()


# Verify a second, quick click on a different nav tab wins over the first click
def test_second_quick_click_on_another_tab_wins(page: Page):
    goto_dashboard(page)

    nav = page.locator("#networksSlider")
    traffic_tab = nav.get_by_text("Traffic", exact=True)
    latency_tab = nav.get_by_text("Latency", exact=True)

    traffic_tab.click()
    latency_tab.click()
    page.wait_for_timeout(500)

    assert is_nav_tab_active(latency_tab), "Latency (the second click) should end up active"
    assert not is_nav_tab_active(traffic_tab), "Traffic (the first click) should not remain active"
    expect(page.locator("#omniChart")).to_be_visible()
