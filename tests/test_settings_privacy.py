"""Settings > PRIVACY group: Encryption, Hassle Free IP, DNS Service, Bypass,
Advanced ISP Stats, App Analytics.

Hassle Free IP and DNS Service are read-only here per the exploratory session's safety
guidance - Hassle Free IP's own description warns "Changing this setting will trigger
a reconnect", and DNS Service is a real networking risk. Both settings' current values
and available choices are still verified.
"""

from playwright.sync_api import Page, expect

from helpers.speedify_cli import get_privacy, get_settings, set_advanced_isp_stats, set_encryption
from helpers.ui_helpers import click_settings_row, goto_dashboard, open_settings

DNS_CHOICES = ["Auto (Recommended)", "Quad9", "CloudFlare", "OpenDNS", "AdGuard", "Custom"]


# Verify the Encryption row displays its current value
def test_encryption_displays_current_value(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    row_value = (
        page.get_by_text("Encryption", exact=True)
        .last.locator("xpath=following-sibling::*[1]")
        .inner_text()
        .strip()
    )
    print(f"\n[settings] Encryption current value: {row_value!r}")
    assert row_value in ("On", "Off")


# Verify toggling Encryption via the UI updates the CLI's "encrypted" field, and restores -
# the affirmative choice is labeled "On (Recommended)", not "On" (verified via DOM inspection)
def test_toggling_encryption_updates_cli_and_restores(page: Page):
    original_encrypted = get_settings()["encrypted"]
    print(f"\n[settings] original encrypted: {original_encrypted}")
    try:
        goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
        open_settings(page)
        click_settings_row(page, "Encryption")
        expect(page).to_have_url("http://localhost:8080/#/settings/encryption")

        target_label = "Off" if original_encrypted else "On (Recommended)"
        print(f"[settings] selecting {target_label!r}")
        page.locator("app-settings-choice-row").get_by_text(target_label, exact=True).click()
        page.wait_for_timeout(500)

        new_encrypted = get_settings()["encrypted"]
        print(f"[settings] CLI encrypted after change: {new_encrypted}")
        assert new_encrypted == (not original_encrypted), (
            f"Selecting {target_label!r} gave CLI encrypted={new_encrypted}, "
            f"expected {not original_encrypted}"
        )
    finally:
        set_encryption("on" if original_encrypted else "off")
        restored = get_settings()["encrypted"]
        print(f"[settings] restored encrypted: {restored}")
        assert restored == original_encrypted, f"Failed to restore encryption: {restored} != {original_encrypted}"


# Verify the Hassle Free IP row displays its current value - never toggled here since its
# own description warns changing it triggers a reconnect (not instantly/safely reversible)
def test_hassle_free_ip_displays_current_value(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    row_value = (
        page.get_by_text("Hassle Free IP", exact=True)
        .last.locator("xpath=following-sibling::*[1]")
        .inner_text()
        .strip()
    )
    print(f"\n[settings] Hassle Free IP current value: {row_value!r}")
    assert row_value in ("On", "Off")

    click_settings_row(page, "Hassle Free IP")
    expect(page).to_have_url("http://localhost:8080/#/settings/residentialProxy")
    expect(page.get_by_text("reconnect", exact=False)).to_be_visible()


# Verify the DNS Service row displays its current value and all available options -
# never changed here (a real networking risk, per the exploratory session's guidance)
def test_dns_service_displays_current_value_and_options(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    row_value = (
        page.get_by_text("DNS Service", exact=True)
        .last.locator("xpath=following-sibling::*[1]")
        .inner_text()
        .strip()
    )
    print(f"\n[settings] DNS Service current value: {row_value!r}")
    assert row_value != ""

    click_settings_row(page, "DNS Service")
    expect(page).to_have_url("http://localhost:8080/#/settings/dnsService")
    for label in DNS_CHOICES:
        expect(page.locator("app-settings-choice-row").get_by_text(label, exact=True)).to_be_visible()


# Verify the Bypass row shows the service count, and that MANAGE navigates to the
# management view without errors
def test_bypass_row_displays_service_count_and_manage_opens(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    row_value = (
        page.get_by_text("Bypass", exact=True)
        .last.locator("xpath=following-sibling::*[1]")
        .inner_text()
        .strip()
    )
    print(f"\n[settings] Bypass service count: {row_value!r}")
    assert row_value.isdigit(), f"Expected a numeric service count, got {row_value!r}"

    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    click_settings_row(page, "Bypass")
    expect(page).to_have_url("http://localhost:8080/#/settings/streamingBypass")
    # "selected services will bypass" also partially overlaps a second, similar
    # sentence elsewhere on this pane (a strict-mode violation with the apostrophed
    # version originally tried here) - a shorter, punctuation-free substring plus
    # .first avoids both problems.
    expect(page.get_by_text("selected services will bypass", exact=False).first).to_be_visible()
    assert errors == [], f"Opening Bypass management threw page errors: {errors}"

    # Documented finding from DOM inspection: the individual service checklist (e.g.
    # Netflix, HBO, Hulu - confirmed present via `speedify_cli show streamingbypass`)
    # doesn't render any matchable text in this browser-only test harness, even after
    # waiting and scrolling. The page navigates and loads without errors; verifying an
    # individual service's on/off state isn't reliably possible from here, so that part
    # of the exploratory session's ask is intentionally not asserted.
    print("[settings] individual Bypass services not verifiable in this harness - see comment above")


# Verify the Advanced ISP Stats row displays its current value, and that toggling it via
# the UI updates the CLI's "advancedIspStats" field and restores cleanly
def test_advanced_isp_stats_displays_and_toggle_restores(page: Page):
    original = get_privacy()["advancedIspStats"]
    print(f"\n[settings] original advancedIspStats: {original}")
    try:
        goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
        open_settings(page)
        click_settings_row(page, "Advanced ISP Stats")
        expect(page).to_have_url("http://localhost:8080/#/settings/advancedIspStats")

        target_label = "Off" if original else "On (Recommended)"
        print(f"[settings] selecting {target_label!r}")
        page.locator("app-settings-choice-row").get_by_text(target_label, exact=True).click()
        page.wait_for_timeout(500)

        new_value = get_privacy()["advancedIspStats"]
        print(f"[settings] CLI advancedIspStats after change: {new_value}")
        assert new_value == (not original), (
            f"Selecting {target_label!r} gave advancedIspStats={new_value}, expected {not original}"
        )
    finally:
        set_advanced_isp_stats("on" if original else "off")
        restored = get_privacy()["advancedIspStats"]
        print(f"[settings] restored advancedIspStats: {restored}")
        assert restored == original, f"Failed to restore advancedIspStats: {restored} != {original}"


# Verify the App Analytics row displays its current value, and that toggling it via the
# UI updates the CLI's "appAnalytics" field and restores cleanly (no CLI setter exists
# for this one, so both the change and the restore go through the UI)
def test_app_analytics_displays_and_toggle_restores(page: Page):
    original = get_privacy()["appAnalytics"]
    print(f"\n[settings] original appAnalytics: {original}")
    target_label = "Off" if original else "On"
    restore_label = "On" if original else "Off"
    try:
        goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
        open_settings(page)
        click_settings_row(page, "App Analytics")
        expect(page).to_have_url("http://localhost:8080/#/settings/appAnalytics")

        print(f"[settings] selecting {target_label!r}")
        page.locator("app-settings-choice-row").get_by_text(target_label, exact=True).click()
        page.wait_for_timeout(500)

        new_value = get_privacy()["appAnalytics"]
        print(f"[settings] CLI appAnalytics after change: {new_value}")
        assert new_value == (not original), (
            f"Selecting {target_label!r} gave appAnalytics={new_value}, expected {not original}"
        )
    finally:
        print(f"[settings] restoring via UI: selecting {restore_label!r}")
        goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
        open_settings(page)
        click_settings_row(page, "App Analytics")
        page.locator("app-settings-choice-row").get_by_text(restore_label, exact=True).click()
        page.wait_for_timeout(500)
        restored = get_privacy()["appAnalytics"]
        print(f"[settings] restored appAnalytics: {restored}")
        assert restored == original, f"Failed to restore appAnalytics: {restored} != {original}"
