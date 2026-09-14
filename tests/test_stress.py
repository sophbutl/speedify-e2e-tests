import pytest
from playwright.sync_api import Page, expect

from helpers.ui_helpers import NAV_TABS, close_settings, goto_dashboard, is_nav_tab_active, open_settings

pytestmark = pytest.mark.slow

STATS_TABS = ["Today", "Week", "Month", "All Time"]

CLICK_TIMEOUT = 5000  # fail fast on a stuck UI instead of hanging on the default 30s


def _is_stats_tab_active(tab) -> bool:
    cls = tab.get_attribute("class") or ""
    return "darkText" in cls


# Verify rapid connect/disconnect clicks settle to a consistent toggle/status state
def test_rapid_connect_disconnect_settles_to_consistent_state(page: Page):
    goto_dashboard(page, wait_for="#navbar-onoff")

    toggle = page.locator("#navbar-onoff")
    onoff = page.locator("#onOff")
    status = page.locator("#status-box-ServerButtonTextStatus")

    print("\n[stress] rapid connect/disconnect: 20 clicks")
    for i in range(20):
        toggle.click(timeout=CLICK_TIMEOUT)
        print(f"[stress] click {i + 1}/20 -> class={onoff.get_attribute('class')!r}")
        page.wait_for_timeout(500)

    print("[stress] waiting for UI to settle...")
    for _ in range(30):
        if "pending" not in (onoff.get_attribute("class") or ""):
            break
        page.wait_for_timeout(500)
    else:
        raise AssertionError("Toggle is still stuck in a pending state after settling")

    final_class = (onoff.get_attribute("class") or "").split()
    status_text = status.inner_text().strip()
    print(f"[stress] settled: class={final_class} status={status_text!r}")

    if "off" in final_class:
        assert status_text == "Disconnected", (
            f"Toggle shows off but status text says {status_text!r}"
        )
    else:
        assert status_text == "Connected", (
            f"Toggle shows on but status text says {status_text!r}"
        )

    expect(toggle).to_be_visible()
    expect(page.locator("#dashboard")).to_be_attached()
    print("[stress] UI is consistent and responsive")


# Verify rapid tab switching always leaves the most recently clicked tab active
def test_rapid_tab_switching_keeps_correct_tab_active(page: Page):
    goto_dashboard(page)

    nav = page.locator("#networksSlider")
    tabs = {name: nav.get_by_text(name, exact=True) for name in NAV_TABS}

    print("\n[stress] rapid tab switching: 10 cycles through 5 tabs")
    for cycle in range(10):
        for name in NAV_TABS:
            tabs[name].click(timeout=CLICK_TIMEOUT)
            page.wait_for_timeout(200)
            assert is_nav_tab_active(tabs[name]), (
                f"{name} tab did not become active after click (cycle {cycle + 1})"
            )
        print(f"[stress] cycle {cycle + 1}/10 complete")

    page.wait_for_timeout(500)
    expect(page.locator("#omniChart")).to_be_visible()
    expect(nav).to_be_visible()
    print("[stress] graph canvas still present, nav still responsive")


# Verify spamming clicks on a single already-active tab still renders correctly
def test_spamming_same_tab_still_renders_correctly(page: Page):
    goto_dashboard(page)

    networks_tab = page.locator("#networksSlider").get_by_text("Networks", exact=True)

    print("\n[stress] spamming Networks tab 50 times")
    for i in range(50):
        networks_tab.click(timeout=CLICK_TIMEOUT)
        page.wait_for_timeout(200)
        if (i + 1) % 10 == 0:
            print(f"[stress] {i + 1}/50 clicks")

    page.wait_for_timeout(500)
    expect(networks_tab).to_be_visible()
    expect(page.locator("#omniChart")).to_be_visible()
    print("[stress] Networks tab and graph still render after spam")


# Verify rapid stats-tab switching always leaves the most recently clicked tab active
def test_rapid_stats_tab_switching_keeps_correct_tab_active(page: Page):
    goto_dashboard(page, wait_for="#statistics-pane")

    stats = page.locator("#statistics-pane")
    tabs = {name: stats.get_by_text(name, exact=True) for name in STATS_TABS}

    print("\n[stress] rapid stats tab switching: 15 cycles through 4 tabs")
    for cycle in range(15):
        for name in STATS_TABS:
            tabs[name].click(timeout=CLICK_TIMEOUT)
            page.wait_for_timeout(200)
            assert _is_stats_tab_active(tabs[name]), (
                f"{name} stats tab did not become active (cycle {cycle + 1})"
            )
        if (cycle + 1) % 5 == 0:
            print(f"[stress] cycle {cycle + 1}/15 complete")

    page.wait_for_timeout(500)
    expect(stats).to_be_visible()
    expect(stats.get_by_text("Data Encrypted")).to_be_visible()
    print("[stress] statistics section still displays data")


# Verify heavy up/down scrolling does not break or hide major dashboard sections
def test_heavy_scrolling_does_not_break_layout(page: Page):
    goto_dashboard(page)

    box = page.locator("#networksSlider").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

    print("\n[stress] scrolling up/down 20 times")
    for i in range(20):
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(150)
        page.mouse.wheel(0, -600)
        page.wait_for_timeout(150)
        if (i + 1) % 5 == 0:
            print(f"[stress] scroll pass {i + 1}/20")

    page.wait_for_timeout(500)
    # #statusBox is rendered twice in the DOM (component id + inner div id); .first avoids
    # a strict-mode violation.
    expect(page.locator("#statusBox").first).to_be_visible()
    expect(page.locator("#networksSlider")).to_be_visible()
    expect(page.locator("#statistics-pane")).to_be_visible()
    # #footer (account email/usage/upgrade bar) only renders for free-tier accounts;
    # this app is on an unlimited/team account, so it's legitimately absent.
    footer = page.locator("#footer")
    if footer.count() > 0:
        expect(footer).to_be_visible()
    print("[stress] all major sections still visible after scroll stress")


# Verify rapid Settings open/close cycles don't drop clicks or leave the dashboard broken
def test_rapid_settings_open_close_does_not_drop_clicks(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')

    settings_btn = page.locator('button[aria-label="Settings Button"]')
    back_btn = page.locator("app-back-done-button")

    print("\n[stress] rapid settings open/close: 15 cycles")
    for i in range(15):
        open_settings(page, timeout=CLICK_TIMEOUT)
        page.wait_for_timeout(300)
        assert back_btn.count() > 0, (
            f"Settings panel did not open on cycle {i + 1}/15 - the Settings button "
            "click appears to have been dropped after rapid open/close"
        )
        close_settings(page, timeout=CLICK_TIMEOUT)
        page.wait_for_timeout(300)
        print(f"[stress] cycle {i + 1}/15 complete")

    page.wait_for_timeout(500)
    # #dashboard is a zero-height layout wrapper (its children are visible, it never is),
    # so attachment plus a visible child landmark is the real check for "dashboard showing".
    expect(page.locator("#dashboard")).to_be_attached()
    expect(page.locator("#networksSlider")).to_be_visible()
    expect(settings_btn).to_be_visible()

    print("[stress] verifying settings button still opens settings")
    open_settings(page, timeout=CLICK_TIMEOUT)
    expect(back_btn).to_be_visible()
    close_settings(page, timeout=CLICK_TIMEOUT)
    expect(page.locator("#networksSlider")).to_be_visible()
    print("[stress] settings round-trip still works")
