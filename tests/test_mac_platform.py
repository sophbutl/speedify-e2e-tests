"""Mac-platform-specific tests: the real Speedify app runs inside WKWebView (WebKit),
while the rest of this suite runs against Chromium via the shared session `page`
fixture. These tests spin up dedicated WebKit browsers/contexts to catch rendering
or interaction bugs that Chromium wouldn't surface.
"""

import pytest
from playwright.sync_api import Browser, Page, Playwright, expect

from helpers.speedify_cli import connect, disconnect, get_adapters, get_state, wait_for_state

NOT_CONNECTED_STATE = "LOGGED_IN"
NAV_TABS = ["Networks", "Traffic", "Latency", "Loss", "Local"]

TOGGLE = "#navbar-onoff"
ONOFF = "#onOff"
STATUS_TEXT = "#status-box-ServerButtonTextStatus"

CLICK_TIMEOUT = 5000


def _is_nav_tab_active(tab) -> bool:
    cls = tab.get_attribute("class") or ""
    return "darkText" in cls and "darkText40" not in cls


def _settle(page: Page, timeout_ms: int = 20_000):
    """Polls until the status text reaches a terminal Connected/Disconnected state.

    Mirrors the helper in test_state_consistency.py / test_connect_disconnect_edge_cases.py:
    the "pending" class alone isn't a reliable settle signal, so poll the text instead.
    """
    status = page.locator(STATUS_TEXT)
    onoff = page.locator(ONOFF).first
    waited = 0
    last_text = ""
    last_cls: list[str] = []

    page.wait_for_timeout(150)
    waited += 150

    while waited < timeout_ms:
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
        wait_for_state("CONNECTED", timeout=30)
    elif not was_connected and get_state() == "CONNECTED":
        disconnect()
        wait_for_state(NOT_CONNECTED_STATE, timeout=10)


def _one_pane_background(page: Page) -> str:
    return page.evaluate(
        "getComputedStyle(document.getElementById('onePaneContent')).backgroundColor"
    )


# ---------------------------------------------------------------------------
# 1. WebKit rendering — the real app's engine
# ---------------------------------------------------------------------------


def test_core_ui_renders_correctly_in_webkit(playwright: Playwright):
    """Runs the same core checks as test_basics.py, but against a real WebKit
    browser instead of Chromium — this is the engine the shipped app actually uses.
    """
    if get_state() != "CONNECTED":
        connect()
        wait_for_state("CONNECTED", timeout=30)

    browser = playwright.webkit.launch()
    try:
        page = browser.new_page()
        page.goto("http://localhost:8080/")
        page.wait_for_selector("#networksSlider", timeout=15_000)

        print("\n[webkit] heading visible:", page.get_by_role("heading", name="Speedify").count() > 0)
        expect(page.get_by_role("heading", name="Speedify")).to_be_visible()

        status = page.locator(STATUS_TEXT)
        expect(status).to_be_visible()
        expect(status).to_have_text("Connected")
        print(f"[webkit] status text: {status.inner_text()!r}")

        nav = page.locator("#networksSlider")
        expect(nav).to_be_visible()
        for tab in NAV_TABS:
            expect(nav.get_by_text(tab, exact=True)).to_be_visible()
            nav.get_by_text(tab, exact=True).click(timeout=CLICK_TIMEOUT)
            page.wait_for_timeout(200)
        print("[webkit] all 5 nav tabs visible and clickable")

        nav.get_by_text("Networks", exact=True).click()
        page.wait_for_timeout(300)
        chart = page.locator("#omniChart")
        expect(chart).to_be_visible()
        box = chart.bounding_box()
        print(f"[webkit] graph canvas box: {box}")
        assert box["width"] > 0 and box["height"] > 0, f"Graph canvas has zero size in WebKit: {box}"

        adapter_card = page.locator('[id^="network-dot-"]').first
        expect(adapter_card).to_be_visible()
        print("[webkit] adapter card visible")

        stats = page.locator("#statistics-pane")
        expect(stats).to_be_visible()
        expect(stats.get_by_text("Data Encrypted")).to_be_visible()
        print("[webkit] statistics section shows data")

        toggle = page.locator(TOGGLE)
        onoff = page.locator(ONOFF).first
        class_before = onoff.get_attribute("class")
        toggle.click(timeout=CLICK_TIMEOUT)
        _, text_after = _settle(page)
        class_after = onoff.get_attribute("class")
        print(f"[webkit] toggle: before={class_before!r} after={class_after!r} status={text_after!r}")
        assert class_after != class_before, "Toggle did not change state in WebKit"

        # Restore for the next test / teardown.
        toggle.click(timeout=CLICK_TIMEOUT)
        _settle(page)
    finally:
        browser.close()


# ---------------------------------------------------------------------------
# 2. Reduced motion
# ---------------------------------------------------------------------------


def test_settings_drop_bug_with_reduced_motion(browser: Browser):
    """Bug 1 (from test_stress.py::test_rapid_settings_toggle): rapid settings
    open/close can drop a click so the panel silently fails to open. Check whether
    macOS "Reduce motion" (which shortens/removes the settings-panel animation)
    changes that.
    """
    ctx = browser.new_context()
    try:
        page = ctx.new_page()
        page.emulate_media(reduced_motion="reduce")
        page.goto("http://localhost:8080/")
        page.wait_for_selector('button[aria-label="Settings Button"]')

        settings_btn = page.locator('button[aria-label="Settings Button"]')
        back_btn = page.locator("app-back-done-button")

        settings_btn.click(timeout=CLICK_TIMEOUT)
        page.wait_for_timeout(100)
        back_btn.click(timeout=CLICK_TIMEOUT)
        page.wait_for_timeout(100)

        print("\n[reduced-motion] reopening Settings immediately after close")
        settings_btn.click(timeout=CLICK_TIMEOUT)
        dropped = back_btn.count() == 0
        print(f"[reduced-motion] Settings panel dropped on immediate reopen: {dropped}")

        if dropped:
            print("[reduced-motion] Bug 1 STILL reproduces with reduced motion on")
        else:
            print("[reduced-motion] Bug 1 did not reproduce this time with reduced motion on")
            back_btn.click(timeout=CLICK_TIMEOUT)

        expect(page.locator("#networksSlider")).to_be_visible()
    finally:
        ctx.close()


def test_toggle_unresponsive_bug_with_reduced_motion(browser: Browser):
    """Bug 2 (from test_stress.py::test_rapid_connect_disconnect / the "pending"
    stuck-state behavior in test_connect_disconnect_edge_cases.py): rapid toggling
    can leave the connect/disconnect switch stuck unresponsive. Check whether
    reduced motion changes that.
    """
    ctx = browser.new_context()
    try:
        page = ctx.new_page()
        page.emulate_media(reduced_motion="reduce")
        page.goto("http://localhost:8080/")
        page.wait_for_selector(TOGGLE)

        toggle = page.locator(TOGGLE)
        onoff = page.locator(ONOFF).first

        print("\n[reduced-motion] rapid connect/disconnect: 10 clicks")
        for i in range(10):
            toggle.click(timeout=CLICK_TIMEOUT)
            print(f"[reduced-motion] click {i + 1}/10 -> class={onoff.get_attribute('class')!r}")
            page.wait_for_timeout(500)

        print("[reduced-motion] waiting for UI to settle...")
        stuck = True
        for _ in range(30):
            if "pending" not in (onoff.get_attribute("class") or ""):
                stuck = False
                break
            page.wait_for_timeout(500)

        print(f"[reduced-motion] toggle still stuck pending after settling window: {stuck}")
        if stuck:
            print("[reduced-motion] Bug 2 STILL reproduces with reduced motion on")
        else:
            print("[reduced-motion] Bug 2 did not reproduce this time with reduced motion on")

        assert not stuck, "Toggle is still stuck in a pending state after settling (reduced motion)"
        expect(toggle).to_be_visible()
    finally:
        ctx.close()
        if get_state() != "CONNECTED":
            connect()
            wait_for_state("CONNECTED", timeout=30)


def test_rapid_tab_switching_with_reduced_motion(browser: Browser):
    ctx = browser.new_context()
    try:
        page = ctx.new_page()
        page.emulate_media(reduced_motion="reduce")
        page.goto("http://localhost:8080/")
        page.wait_for_selector("#networksSlider")

        nav = page.locator("#networksSlider")
        tabs = {name: nav.get_by_text(name, exact=True) for name in NAV_TABS}

        print("\n[reduced-motion] rapid tab switching: 5 cycles through 5 tabs")
        swallowed = []
        for cycle in range(5):
            for name in NAV_TABS:
                tabs[name].click(timeout=CLICK_TIMEOUT)
                page.wait_for_timeout(150)
                if not _is_nav_tab_active(tabs[name]):
                    swallowed.append((cycle + 1, name))
            print(f"[reduced-motion] cycle {cycle + 1}/5 complete")

        print(f"[reduced-motion] clicks that appeared swallowed: {swallowed}")
        assert not swallowed, f"Tab clicks were swallowed under reduced motion: {swallowed}"
        expect(page.locator("#omniChart")).to_be_visible()
        expect(nav).to_be_visible()
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# 3. Network adapter changes
# ---------------------------------------------------------------------------


def test_ui_adapter_cards_match_cli_adapters(page: Page):
    adapters = get_adapters()
    assert len(adapters) >= 1, "No adapters reported by the CLI to check against"

    page.goto("/")
    page.wait_for_selector('[id^="network-dot-"]')

    ui_card_count = page.locator('[id^="network-dot-"]').count()
    print(f"\n[adapters] CLI reports {len(adapters)} adapter(s), UI shows {ui_card_count} card(s)")
    assert ui_card_count == len(adapters), (
        f"UI shows {ui_card_count} adapter card(s) but CLI reports {len(adapters)}"
    )

    for adapter in adapters:
        card = page.locator(f'#network-dot-{adapter["adapterID"]}')
        expect(card).to_be_visible()
        expect(card).to_contain_text(adapter["name"])
        print(f"[adapters] verified card for {adapter['adapterID']} ({adapter['name']})")


def test_adapter_card_updates_on_disconnect_and_reconnect(page: Page):
    connect()
    wait_for_state("CONNECTED", timeout=30)

    page.goto("/")
    adapters = get_adapters()
    adapter_id = adapters[0]["adapterID"]
    card = page.locator(f"#network-dot-{adapter_id}")
    page.wait_for_selector(f"#network-dot-{adapter_id}")

    class_connected = card.get_attribute("class")
    print(f"\n[adapters] card class while connected: {class_connected!r}")

    disconnect()
    wait_for_state(NOT_CONNECTED_STATE, timeout=10)
    page.wait_for_timeout(1000)

    class_disconnected = card.get_attribute("class")
    print(f"[adapters] card class while disconnected: {class_disconnected!r}")

    connect()
    wait_for_state("CONNECTED", timeout=30)
    page.wait_for_timeout(1000)

    class_reconnected = card.get_attribute("class")
    print(f"[adapters] card class after reconnect: {class_reconnected!r}")

    expect(card).to_be_visible()
    assert class_reconnected == class_connected, (
        "Adapter card did not return to its original connected-state class after reconnecting: "
        f"before={class_connected!r} after={class_reconnected!r}"
    )


# ---------------------------------------------------------------------------
# 4. Page recovery after disruption
# ---------------------------------------------------------------------------


def test_reload_while_disconnected_shows_correct_state(page: Page):
    disconnect()
    wait_for_state(NOT_CONNECTED_STATE, timeout=10)

    page.goto("/")
    page.wait_for_selector(STATUS_TEXT)
    expect(page.locator(STATUS_TEXT)).to_have_text("Disconnected")

    page.reload()
    page.wait_for_selector(STATUS_TEXT)
    expect(page.locator(STATUS_TEXT)).to_have_text("Disconnected", timeout=10_000)
    expect(page.locator("#networksSlider")).to_be_visible()
    print("\n[recovery] reload while disconnected -> UI correctly shows disconnected")


def test_settings_reload_returns_to_dashboard_not_stuck_in_settings(page: Page):
    page.goto("/")
    page.wait_for_selector('button[aria-label="Settings Button"]')

    page.locator('button[aria-label="Settings Button"]').click()
    expect(page.locator("app-back-done-button")).to_be_visible()

    page.reload()
    page.wait_for_selector("#networksSlider", timeout=15_000)

    stuck_in_settings = page.locator("app-back-done-button").count() > 0
    print(f"\n[recovery] still in Settings after reload: {stuck_in_settings}")

    if stuck_in_settings:
        # Documented finding: the app uses hash-based routing (#/settings), and that
        # hash survives a reload, so the UI comes back showing Settings instead of the
        # dashboard. Recover here so later tests aren't left stuck on this panel.
        print("[recovery] FINDING: reload while in Settings does not return to the dashboard")
        page.locator("app-back-done-button").click()
        page.wait_for_timeout(300)

    assert not stuck_in_settings, (
        "Reloading from Settings left the UI stuck in the Settings panel "
        "(the #/settings URL hash survives the reload)"
    )
    expect(page.locator("#networksSlider")).to_be_visible()
    expect(page.locator('button[aria-label="Settings Button"]')).to_be_visible()


def test_ui_stays_live_after_60_seconds_of_no_interaction(page: Page):
    connect()
    wait_for_state("CONNECTED", timeout=30)

    page.goto("/")
    page.wait_for_selector(STATUS_TEXT)

    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    print("\n[recovery] waiting 60s with no interaction")
    page.wait_for_timeout(60_000)

    expect(page.locator(STATUS_TEXT)).to_have_text("Connected")
    expect(page.locator("#networksSlider")).to_be_visible()
    expect(page.locator("#omniChart")).to_be_visible()

    # A live/updating UI should still respond to a click, not be frozen.
    nav = page.locator("#networksSlider")
    nav.get_by_text("Traffic", exact=True).click(timeout=CLICK_TIMEOUT)
    page.wait_for_timeout(300)
    assert _is_nav_tab_active(nav.get_by_text("Traffic", exact=True)), (
        "UI appears frozen/stale after 60s idle - tab click had no effect"
    )
    nav.get_by_text("Networks", exact=True).click(timeout=CLICK_TIMEOUT)

    assert errors == [], f"Page threw errors during the idle period: {errors}"
    print("[recovery] UI still live and responsive after 60s idle")


# ---------------------------------------------------------------------------
# 5. WebKit-specific stress
# ---------------------------------------------------------------------------


def test_settings_stress_in_webkit(playwright: Playwright):
    browser = playwright.webkit.launch()
    try:
        page = browser.new_page()
        page.goto("http://localhost:8080/")
        page.wait_for_selector('button[aria-label="Settings Button"]')

        settings_btn = page.locator('button[aria-label="Settings Button"]')
        back_btn = page.locator("app-back-done-button")

        dropped_cycles = []
        print("\n[webkit-stress] settings open/close: 15 cycles at 300ms")
        for i in range(15):
            settings_btn.click(timeout=CLICK_TIMEOUT)
            page.wait_for_timeout(300)
            if back_btn.count() == 0:
                dropped_cycles.append(i + 1)
                print(f"[webkit-stress] cycle {i + 1}/15: Settings panel did not open")
                settings_btn.click(timeout=CLICK_TIMEOUT)
                page.wait_for_timeout(300)
            back_btn.click(timeout=CLICK_TIMEOUT)
            page.wait_for_timeout(300)

        if dropped_cycles:
            print(f"[webkit-stress] Bug 1 (settings-drop) reproduced in WEBKIT on cycles: {dropped_cycles}")
        else:
            print("[webkit-stress] Bug 1 (settings-drop) did NOT reproduce in WebKit over 15 cycles")

        expect(page.locator("#networksSlider")).to_be_visible()
    finally:
        browser.close()


def test_connect_disconnect_stress_in_webkit(playwright: Playwright):
    if get_state() != "CONNECTED":
        connect()
        wait_for_state("CONNECTED", timeout=30)

    browser = playwright.webkit.launch()
    try:
        page = browser.new_page()
        page.goto("http://localhost:8080/")
        page.wait_for_selector(TOGGLE)

        toggle = page.locator(TOGGLE)
        onoff = page.locator(ONOFF).first

        print("\n[webkit-stress] rapid connect/disconnect: 10 clicks")
        for i in range(10):
            toggle.click(timeout=CLICK_TIMEOUT)
            print(f"[webkit-stress] click {i + 1}/10 -> class={onoff.get_attribute('class')!r}")
            page.wait_for_timeout(500)

        stuck = True
        for _ in range(30):
            if "pending" not in (onoff.get_attribute("class") or ""):
                stuck = False
                break
            page.wait_for_timeout(500)

        if stuck:
            print("[webkit-stress] Bug 2 (toggle-unresponsive) REPRODUCED in WebKit")
        else:
            print("[webkit-stress] Bug 2 (toggle-unresponsive) did NOT reproduce in WebKit")

        assert not stuck, "Toggle is stuck in a pending state after settling in WebKit"
        expect(toggle).to_be_visible()
    finally:
        browser.close()
        if get_state() != "CONNECTED":
            connect()
            wait_for_state("CONNECTED", timeout=30)


# ---------------------------------------------------------------------------
# 6. Forced color schemes in WebKit
# ---------------------------------------------------------------------------


def test_webkit_dark_color_scheme_renders_dark_background(playwright: Playwright):
    browser = playwright.webkit.launch()
    try:
        ctx = browser.new_context(color_scheme="dark")
        page = ctx.new_page()
        page.goto("http://localhost:8080/")
        page.wait_for_selector("#networksSlider")
        page.wait_for_timeout(400)

        bg = _one_pane_background(page)
        print(f"\n[webkit] colorScheme=dark -> background={bg!r}")
        assert bg not in ("rgb(255, 255, 255)", "rgba(0, 0, 0, 0)"), (
            f"Expected a dark background in WebKit under colorScheme=dark, got {bg!r}"
        )
    finally:
        browser.close()


def test_webkit_light_color_scheme_renders_light_background(playwright: Playwright):
    browser = playwright.webkit.launch()
    try:
        ctx = browser.new_context(color_scheme="light")
        page = ctx.new_page()
        page.goto("http://localhost:8080/")
        page.wait_for_selector("#networksSlider")
        page.wait_for_timeout(400)

        bg = _one_pane_background(page)
        print(f"\n[webkit] colorScheme=light -> background={bg!r}")
        assert bg == "rgb(255, 255, 255)", f"Expected a light background in WebKit, got {bg!r}"
    finally:
        browser.close()


# ---------------------------------------------------------------------------
# 7. High contrast / accessibility
# ---------------------------------------------------------------------------


def _text_and_background_color(page: Page, selector: str):
    """Returns (text color, nearest ancestor's non-transparent background color)."""
    return page.evaluate(
        """(sel) => {
            let el = document.querySelector(sel);
            if (!el) return [null, null];
            const color = getComputedStyle(el).color;
            let bgEl = el;
            let bg = 'rgba(0, 0, 0, 0)';
            while (bgEl) {
                const candidate = getComputedStyle(bgEl).backgroundColor;
                if (candidate && candidate !== 'rgba(0, 0, 0, 0)') { bg = candidate; break; }
                bgEl = bgEl.parentElement;
            }
            return [color, bg];
        }""",
        selector,
    )


def _relative_luminance(rgb_str: str) -> float:
    nums = [int(n) for n in rgb_str.replace("rgba(", "").replace("rgb(", "").replace(")", "").split(",")[:3]]

    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in nums)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(rgb_a: str, rgb_b: str) -> float:
    l1, l2 = _relative_luminance(rgb_a), _relative_luminance(rgb_b)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def test_forced_colors_mode_does_not_break_layout(browser: Browser):
    ctx = browser.new_context(forced_colors="active")
    try:
        page = ctx.new_page()
        page.goto("http://localhost:8080/")
        page.wait_for_selector("#networksSlider", timeout=15_000)

        active = page.evaluate("matchMedia('(forced-colors: active)').matches")
        print(f"\n[a11y] forced-colors active: {active}")

        expect(page.locator(STATUS_TEXT)).to_be_visible()
        expect(page.locator("#networksSlider")).to_be_visible()
        expect(page.locator(TOGGLE)).to_be_visible()
    finally:
        ctx.close()


@pytest.mark.parametrize("scheme", ["dark", "light"])
def test_status_text_and_toggle_have_sufficient_contrast(browser: Browser, scheme):
    ctx = browser.new_context(color_scheme=scheme)
    try:
        page = ctx.new_page()
        page.goto("http://localhost:8080/")
        page.wait_for_selector(STATUS_TEXT)
        page.wait_for_timeout(400)

        status_color, status_bg = _text_and_background_color(page, STATUS_TEXT)
        ratio = _contrast_ratio(status_color, status_bg)
        print(f"\n[a11y] {scheme}: status text color={status_color!r} bg={status_bg!r} contrast={ratio:.2f}:1")

        expect(page.locator(STATUS_TEXT)).to_be_visible()
        expect(page.locator(STATUS_TEXT)).to_have_text("Connected")
        # WCAG AA for normal text is 4.5:1; this is a directional accessibility check.
        assert ratio >= 4.5, (
            f"Status text contrast is only {ratio:.2f}:1 against its background in {scheme} mode "
            "(WCAG AA wants >= 4.5:1)"
        )
    finally:
        ctx.close()


def test_toggle_visually_distinguishable_in_both_states(page: Page):
    # The toggle is a sliding switch (like iOS): #onOff sets the track's background
    # color, and its child .onoffswitch-switch knob translates left/right. Position is
    # the primary, color-independent affordance, so that's the main thing checked here
    # - background-color contrast is measured too, but only as a secondary diagnostic,
    # since a colorblind user still perceives the knob position either way.
    page.goto("/")
    page.wait_for_selector(TOGGLE)
    # Wait for the toggle to reach a stable Connected/Disconnected state before
    # reading its color - right after goto(), Angular can briefly show a default
    # class before applying the real connection state.
    _settle(page)

    onoff = page.locator(ONOFF).first
    knob = page.locator(f"{ONOFF} .onoffswitch-switch").first
    page.wait_for_timeout(500)  # let the background-color/transform CSS transition finish
    on_bg = onoff.evaluate("el => getComputedStyle(el).backgroundColor")
    on_transform = knob.evaluate("el => getComputedStyle(el).transform")
    was_connected = "on" in (onoff.get_attribute("class") or "")

    page.locator(TOGGLE).click(timeout=CLICK_TIMEOUT)
    _settle(page)
    page.wait_for_timeout(500)  # let the background-color/transform CSS transition finish
    off_bg = onoff.evaluate("el => getComputedStyle(el).backgroundColor")
    off_transform = knob.evaluate("el => getComputedStyle(el).transform")

    print(f"\n[a11y] toggle background: on-state={on_bg!r} off-state={off_bg!r}")
    print(f"[a11y] toggle knob transform: on-state={on_transform!r} off-state={off_transform!r}")

    ratio = _contrast_ratio(on_bg, off_bg)
    print(f"[a11y] contrast between on/off toggle backgrounds: {ratio:.2f}:1 (diagnostic only)")
    if ratio < 3.0:
        print(
            "[a11y] FINDING: on/off background colors have low luminance contrast "
            f"({ratio:.2f}:1) - a colorblind or grayscale-display user relies on the knob "
            "position, not color, to read toggle state"
        )

    assert on_transform != off_transform, (
        "Toggle knob does not move between on/off states - with a low-contrast "
        "background color, position is the only reliable way to tell the states apart"
    )

    # Restore original state.
    if was_connected:
        connect()
        wait_for_state("CONNECTED", timeout=30)
    else:
        disconnect()
        wait_for_state(NOT_CONNECTED_STATE, timeout=10)
