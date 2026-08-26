from playwright.sync_api import Page, expect

from helpers.speedify_cli import connect, get_adapters, get_state, wait_for_state


def test_adapter_card_shows_name_and_speed_when_connected(page: Page):
    if get_state() != "CONNECTED":
        connect()
        wait_for_state("CONNECTED", timeout=20)

    adapters = get_adapters()
    assert len(adapters) >= 1, "No adapters reported by the CLI to check against"
    adapter = adapters[0]

    page.goto("/")
    page.wait_for_selector(f'#network-dot-{adapter["adapterID"]}')

    card = page.locator(f'#network-dot-{adapter["adapterID"]}')
    expect(card).to_be_visible()
    expect(card).to_contain_text(adapter["name"])


def test_download_and_upload_speed_values_are_not_blank(page: Page):
    if get_state() != "CONNECTED":
        connect()
        wait_for_state("CONNECTED", timeout=20)

    page.goto("/")
    page.wait_for_selector('img[aria-label="Download Speed"]')

    download_value = page.locator('img[aria-label="Download Speed"]').first.locator(
        "xpath=following-sibling::*[1]"
    )
    upload_value = page.locator('img[aria-label="Upload Speed"]').first.locator(
        "xpath=following-sibling::*[1]"
    )

    expect(download_value).to_be_visible()
    expect(upload_value).to_be_visible()
    assert download_value.inner_text().strip() != ""
    assert upload_value.inner_text().strip() != ""


def test_statistics_show_numeric_values(page: Page):
    page.goto("/")
    page.wait_for_selector("#statistics-pane")

    stats = page.locator("#statistics-pane")
    for label in ["Data Encrypted", "Top Download Speed", "Top Upload Speed"]:
        value = stats.get_by_text(label, exact=True).locator("xpath=following-sibling::*[1]")
        text = value.inner_text().strip()
        print(f"[data] {label}: {text!r}")
        assert text != "", f"{label} value is blank"
        assert any(ch.isdigit() for ch in text), f"{label} value {text!r} has no digits"


def test_footer_or_account_info_is_not_blank(page: Page):
    page.goto("/")
    page.wait_for_selector("#networksSlider")

    # #accountInfo-email / #accountInfo-usageText only render inside #footer, which
    # is only shown for free-tier accounts. This app is on an unlimited/team account
    # (verified via console logs: "isTeam=true"), so the equivalent account info lives
    # in Settings > Account instead.
    footer = page.locator("#footer")
    if footer.count() > 0:
        email = page.locator("#accountInfo-email")
        usage = page.locator("#accountInfo-usageText")
        expect(email).to_be_visible()
        expect(usage).to_be_visible()
        assert email.inner_text().strip() != ""
        assert usage.inner_text().strip() != ""
        return

    page.locator('button[aria-label="Settings Button"]').click()
    account_header = page.locator(".account-header").first
    expect(account_header).to_be_visible()
    text = account_header.inner_text().strip()
    print(f"[data] account type (no #footer for this account tier): {text!r}")
    assert text != ""
    page.locator("app-back-done-button").click()


def test_upgrade_button_is_clickable_or_absent_for_this_account_tier(page: Page):
    page.goto("/")
    page.wait_for_selector("#networksSlider")

    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    upgrade_btn = page.locator("#uber-box-upgrade")
    if upgrade_btn.count() == 0:
        # Unlimited/team accounts don't get an upgrade nag — nothing to click.
        print("[data] #uber-box-upgrade not present for this account tier, skipping click")
        return

    expect(upgrade_btn).to_be_visible()

    # Upgrade CTAs commonly open an external purchase page in a new tab rather than
    # navigating the app itself — capture a popup if one appears so it doesn't leak
    # into later tests, and don't assume either way.
    try:
        with page.context.expect_page(timeout=3000) as popup_info:
            upgrade_btn.click()
        popup_info.value.close()
        print("[data] UPGRADE NOW opened a new tab; closed it")
    except Exception:
        page.wait_for_timeout(1000)
        print("[data] UPGRADE NOW did not open a new tab")

    assert errors == [], f"Clicking UPGRADE NOW threw page errors: {errors}"
    expect(page.locator("#dashboard")).to_be_attached()
