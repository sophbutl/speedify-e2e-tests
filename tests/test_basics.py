import re

import pytest
from playwright.sync_api import Page, expect

from helpers.ui_helpers import NAV_TABS

# Verify the Speedify UI loads and the main heading is visible
@pytest.mark.smoke
def test_page_loads_and_shows_speedify_heading(page: Page):
    page.goto("/")
    expect(page.get_by_role("heading", name="Speedify")).to_be_visible()

# Verify the connection status text is visible and shows "Connected" or "Disconnected"
def test_connection_status_text_is_visible(page: Page):
    page.goto("/")
    status = page.locator("#status-box-ServerButtonTextStatus")
    expect(status).to_be_visible()
    expect(status).to_have_text(re.compile("Connected|Disconnected"))

# Verify all 5 navigation tabs (Networks, Traffic, Latency, Loss, Local) are visible
def test_all_nav_tabs_are_visible(page: Page):
    page.goto("/")
    nav = page.locator("#networksSlider")
    expect(nav).to_be_visible()

    for tab in NAV_TABS:
        expect(nav.get_by_text(tab, exact=True)).to_be_visible()

# Verify at least one network adapter card (like Wi-Fi) is showing
def test_wifi_adapter_card_is_visible(page: Page):
    page.goto("/")
    adapter_card = page.locator('[id^="network-dot-"]').first
    expect(adapter_card).to_be_visible()

# Verify the Statistics section displays a "Data Encrypted" label with a value
def test_statistics_section_shows_data_encrypted_with_value(page: Page):
    page.goto("/")
    stats = page.locator("#statistics-pane")
    expect(stats).to_be_visible()
    expect(stats.get_by_text("Data Encrypted")).to_be_visible()

    label = stats.get_by_text("Data Encrypted")
    value = label.locator("xpath=following-sibling::*[1]")
    expect(value).to_be_visible()
    expect(value).not_to_have_text("")
