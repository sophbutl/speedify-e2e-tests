import pytest
from playwright.sync_api import Browser, Page, expect

from helpers.speedify_cli import NOT_CONNECTED_STATE, get_state, wait_for_state
from helpers.ui_helpers import (
    ONOFF,
    STATUS_TEXT,
    TOGGLE,
    connect_and_wait,
    ensure_connected,
    goto_dashboard,
    open_settings,
)

DEFAULT_VIEWPORT = {"width": 1280, "height": 720}

# Common macOS display resolutions (logical pixels, i.e. what the web layer sees).
MAC_DISPLAY_SIZES = {
    "MacBook Air 13\"": (1280, 800),
    "MacBook Air 15\"": (1440, 900),
    "MacBook Pro 14\"": (1512, 982),
    "MacBook Pro 16\"": (1728, 1117),
}

# The native app's real enforced minimum window size lives in Cocoa/AppKit (NSWindow
# minSize) and isn't queryable from the web content layer, so this is a reasonable,
# clearly-assumed floor for a desktop utility window rather than a verified constraint.
ASSUMED_MIN_WINDOW_SIZE = {"width": 800, "height": 600}


@pytest.fixture(autouse=True)
def restore_viewport_and_media(page: Page):
    yield
    page.set_viewport_size(DEFAULT_VIEWPORT)
    page.emulate_media(color_scheme=None)
    page.wait_for_timeout(200)


def _one_pane_background(page: Page) -> str:
    # #onePaneContent is a duplicate id (like #dashboard, the first match is a
    # zero-height layout wrapper); getElementById grabs that first one, whose
    # background still correctly tracks the theme - verified: dark=rgb(28, 28, 29),
    # light=rgb(255, 255, 255), consistent whether set via colorScheme emulation or
    # the in-app Theme picker. Reading it via evaluate() doesn't require the element
    # to be visible, only present, so the earlier wait_for_selector timeout (which
    # defaults to waiting for visibility) doesn't apply here - that's fixed by
    # waiting on #networksSlider instead before calling this.
    return page.evaluate(
        "getComputedStyle(document.getElementById('onePaneContent')).backgroundColor"
    )


# ---------------------------------------------------------------------------
# Dark mode / light mode
# ---------------------------------------------------------------------------


# Verify the Theme setting exists with Default, Light, and Dark options
def test_theme_setting_exists_with_default_light_dark_options(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)

    theme_row = page.get_by_text("Theme", exact=True)
    expect(theme_row).to_be_visible()
    theme_row.click()

    for label in ["Default", "Light", "Dark"]:
        expect(page.locator("app-settings-choice-row").get_by_text(label, exact=True)).to_be_visible()


# Verify selecting the Dark theme changes the app's background color
def test_selecting_dark_theme_changes_background_color(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')

    try:
        open_settings(page)
        page.get_by_text("Theme", exact=True).click()

        page.locator("app-settings-choice-row").get_by_text("Dark", exact=True).click()
        page.wait_for_timeout(500)
        cls = page.evaluate("document.getElementById('onePane').className")
        bg = _one_pane_background(page)
        print(f"\n[mac] dark theme -> onePane class={cls!r} bg={bg!r}")

        assert "darkTheme" in cls
        assert bg != "rgb(255, 255, 255)"
    finally:
        # Restore the Default theme setting regardless of outcome.
        theme_row = page.get_by_text("Theme", exact=True)
        if theme_row.count() == 0:
            open_settings(page)
            page.get_by_text("Theme", exact=True).click()
        page.locator("app-settings-choice-row").get_by_text("Default", exact=True).click()
        page.wait_for_timeout(300)


# Verify selecting the Light theme changes the app's background color
def test_selecting_light_theme_changes_background_color(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')

    try:
        open_settings(page)
        page.get_by_text("Theme", exact=True).click()

        page.locator("app-settings-choice-row").get_by_text("Light", exact=True).click()
        page.wait_for_timeout(500)
        cls = page.evaluate("document.getElementById('onePane').className")
        bg = _one_pane_background(page)
        print(f"\n[mac] light theme -> onePane class={cls!r} bg={bg!r}")

        assert "lightTheme" in cls
        assert bg == "rgb(255, 255, 255)"
    finally:
        theme_row = page.get_by_text("Theme", exact=True)
        if theme_row.count() == 0:
            open_settings(page)
            page.get_by_text("Theme", exact=True).click()
        page.locator("app-settings-choice-row").get_by_text("Default", exact=True).click()
        page.wait_for_timeout(300)


# Verify a context forced to a dark OS color scheme renders a dark background
def test_dark_color_scheme_context_renders_dark_background(browser: Browser):
    ctx = browser.new_context(color_scheme="dark")
    try:
        page = ctx.new_page()
        goto_dashboard(page, url="http://localhost:8080/")
        bg = _one_pane_background(page)
        print(f"\n[mac] colorScheme=dark -> background={bg!r}")
        assert bg not in ("rgb(255, 255, 255)", "rgba(0, 0, 0, 0)"), (
            f"Expected a dark background under colorScheme=dark, got {bg!r}"
        )
    finally:
        ctx.close()


# Verify a context forced to a light OS color scheme renders a light background
def test_light_color_scheme_context_renders_light_background(browser: Browser):
    ctx = browser.new_context(color_scheme="light")
    try:
        page = ctx.new_page()
        goto_dashboard(page, url="http://localhost:8080/")
        bg = _one_pane_background(page)
        print(f"\n[mac] colorScheme=light -> background={bg!r}")
        assert bg == "rgb(255, 255, 255)", f"Expected a light background, got {bg!r}"
    finally:
        ctx.close()


# Verify switching the OS color scheme mid-session updates the UI without breaking it
def test_switching_color_scheme_mid_session_updates_without_breaking(page: Page):
    goto_dashboard(page)

    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    print("\n[mac] switching color scheme mid-session: dark -> light -> dark")
    page.emulate_media(color_scheme="dark")
    page.wait_for_timeout(400)
    dark_bg = _one_pane_background(page)
    print(f"[mac] dark: {dark_bg!r}")

    page.emulate_media(color_scheme="light")
    page.wait_for_timeout(400)
    light_bg = _one_pane_background(page)
    print(f"[mac] light: {light_bg!r}")

    page.emulate_media(color_scheme="dark")
    page.wait_for_timeout(400)
    dark_bg_again = _one_pane_background(page)
    print(f"[mac] dark again: {dark_bg_again!r}")

    assert dark_bg != light_bg, "Background didn't change between color schemes"
    assert dark_bg == dark_bg_again, "Re-applying the same color scheme gave a different result"
    assert errors == [], f"Switching color scheme threw page errors: {errors}"
    expect(page.locator("#networksSlider")).to_be_visible()


# ---------------------------------------------------------------------------
# Keyboard shortcuts
# ---------------------------------------------------------------------------


# Verify Cmd+A (select all) does not break the page layout
def test_cmd_a_does_not_break_layout(page: Page):
    goto_dashboard(page)

    page.keyboard.press("Meta+a")
    page.wait_for_timeout(300)

    selection_length = page.evaluate("window.getSelection().toString().length")
    print(f"\n[mac] Cmd+A selected {selection_length} characters")

    expect(page.locator("#networksSlider")).to_be_visible()
    expect(page.locator("#statusBox").first).to_be_visible()

    # Clear the selection so it doesn't linger for later tests.
    page.evaluate("window.getSelection().removeAllRanges()")


# Verify Cmd+R is inert in-page, but a real reload correctly recovers connected state
def test_cmd_r_keypress_is_inert_but_reload_recovers_state(page: Page):
    connect_and_wait()

    goto_dashboard(page, wait_for=STATUS_TEXT)
    url_before = page.url

    # Cmd+R is a browser-chrome-level accelerator, not a page-level DOM event, so
    # automated keyboard.press("Meta+r") is expected to be a no-op here - verified
    # empirically (URL and DOM are untouched). The real "does a reload recover
    # correctly" behavior is exercised via page.reload() below instead.
    page.keyboard.press("Meta+r")
    page.wait_for_timeout(500)
    assert page.url == url_before
    expect(page.locator("#networksSlider")).to_be_visible()

    page.reload()
    page.wait_for_selector(STATUS_TEXT)
    expect(page.locator(STATUS_TEXT)).to_have_text("Connected", timeout=10_000)
    expect(page.locator("#networksSlider")).to_be_visible()


# Verify pressing Escape while in Settings leaves the UI in a recoverable state
def test_escape_key_press_in_settings_leaves_ui_recoverable(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')

    open_settings(page)
    back_btn = page.locator("app-back-done-button")
    expect(back_btn).to_be_visible()

    page.keyboard.press("Escape")
    page.wait_for_timeout(500)

    # Documented finding: Escape does NOT close the Settings panel in this app
    # (verified directly against the DOM) - unlike the typical macOS convention.
    # Whichever way it behaves, the UI must stay usable and Settings must still
    # be closable via the Done button.
    still_in_settings = back_btn.count() > 0
    print(f"\n[mac] Escape closed Settings: {not still_in_settings}")

    if still_in_settings:
        back_btn.click()
    expect(page.locator("#networksSlider")).to_be_visible()
    expect(page.locator('button[aria-label="Settings Button"]')).to_be_visible()


# Verify Tab key focus order cycles through the page instead of getting trapped
def test_tab_focus_order_is_not_trapped(page: Page):
    goto_dashboard(page)

    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    focused = []
    print("\n[mac] pressing Tab 10 times, recording focus targets")
    for i in range(10):
        page.keyboard.press("Tab")
        page.wait_for_timeout(100)
        target = page.evaluate(
            "() => { const el = document.activeElement; "
            "return el ? (el.id || el.tagName) : null; }"
        )
        print(f"[mac] tab {i + 1}: {target}")
        focused.append(target)

    assert errors == [], f"Tabbing through the page threw errors: {errors}"
    assert len(set(focused)) > 1, (
        f"Focus never moved off a single element across 10 Tab presses: {focused}"
    )
    expect(page.locator("#networksSlider")).to_be_visible()


# Verify pressing Space or Enter on the focused toggle operates it like a click
def test_space_or_enter_on_focused_toggle_operates_it_like_a_click(page: Page):
    connect_and_wait()

    goto_dashboard(page, wait_for=TOGGLE)

    toggle = page.locator(TOGGLE)
    toggle.focus()
    active_id = page.evaluate(
        "() => { const el = document.activeElement; return el ? el.id : null; }"
    )
    print(f"\n[mac] active element after focusing toggle: {active_id!r}")

    onoff = page.locator(ONOFF).first
    class_before = onoff.get_attribute("class")

    page.keyboard.press("Space")
    page.wait_for_timeout(500)
    class_after_space = onoff.get_attribute("class")

    page.keyboard.press("Enter")
    page.wait_for_timeout(500)
    class_after_enter = onoff.get_attribute("class")

    print(
        f"[mac] class before={class_before!r} after Space={class_after_space!r} "
        f"after Enter={class_after_enter!r}"
    )

    # The toggle has role="button" but no tabindex, so it isn't natively focusable
    # (confirmed: .focus() doesn't move document.activeElement onto it) - this
    # assertion documents the real, expected accessibility behavior for a
    # keyboard/VoiceOver user, and is expected to fail until that's fixed.
    assert active_id == "navbar-onoff", (
        "Toggle never received keyboard focus (role=\"button\" without a tabindex) "
        "- it can't be operated via Space/Enter by keyboard or VoiceOver users"
    )
    assert class_before != class_after_space, "Space did not change the toggle's state"


# ---------------------------------------------------------------------------
# Retina / high DPI
# ---------------------------------------------------------------------------


def _assert_canvas_matches_scale_factor(page: Page, expected_dsf: float):
    actual_dpr = page.evaluate("window.devicePixelRatio")
    assert actual_dpr == expected_dsf, f"devicePixelRatio={actual_dpr}, expected {expected_dsf}"

    chart = page.locator("#omniChart")
    expect(chart).to_be_visible()
    box = chart.bounding_box()
    canvas_px = chart.evaluate("el => ({width: el.width, height: el.height})")

    print(
        f"[mac] dsf={expected_dsf}: css box={box['width']}x{box['height']} "
        f"canvas backing store={canvas_px['width']}x{canvas_px['height']}"
    )
    assert box["width"] > 0 and box["height"] > 0

    expected_w = round(box["width"] * expected_dsf)
    expected_h = round(box["height"] * expected_dsf)
    assert abs(canvas_px["width"] - expected_w) <= 2, (
        f"Canvas backing-store width {canvas_px['width']} doesn't match the CSS box "
        f"scaled by devicePixelRatio (expected ~{expected_w}) - possible blurry rendering"
    )
    assert abs(canvas_px["height"] - expected_h) <= 2, (
        f"Canvas backing-store height {canvas_px['height']} doesn't match the CSS box "
        f"scaled by devicePixelRatio (expected ~{expected_h}) - possible blurry rendering"
    )


# Verify the graph canvas renders sharply (no blur) at a 2x Retina scale factor
def test_retina_scale_factor_renders_without_blurry_layout(browser: Browser):
    ensure_connected()

    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, device_scale_factor=2)
    try:
        page = ctx.new_page()
        goto_dashboard(page, wait_for="#omniChart", url="http://localhost:8080/", timeout=15_000)
        page.wait_for_timeout(500)
        _assert_canvas_matches_scale_factor(page, 2)
        expect(page.locator("#networksSlider")).to_be_visible()
    finally:
        ctx.close()


# Verify the graph canvas renders correctly at a standard 1x scale factor
def test_standard_scale_factor_renders_correctly(browser: Browser):
    ensure_connected()

    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, device_scale_factor=1)
    try:
        page = ctx.new_page()
        goto_dashboard(page, wait_for="#omniChart", url="http://localhost:8080/", timeout=15_000)
        page.wait_for_timeout(500)
        _assert_canvas_matches_scale_factor(page, 1)
        expect(page.locator("#networksSlider")).to_be_visible()
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# Trackpad-style scrolling
# ---------------------------------------------------------------------------


def _hover_over_content(page: Page):
    box = page.locator("#networksSlider").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


# Verify smooth, trackpad-style scrolling does not jump or stick
def test_smooth_trackpad_style_scrolling_does_not_jump_or_stick(page: Page):
    goto_dashboard(page)
    _hover_over_content(page)

    print("\n[mac] simulating trackpad scroll: many small steps")
    for i in range(30):
        page.mouse.wheel(0, 15)
        page.wait_for_timeout(20)
        if (i + 1) % 10 == 0:
            print(f"[mac] scroll step {i + 1}/30")

    expect(page.locator("#networksSlider")).to_be_visible()
    expect(page.locator("#statistics-pane")).to_be_visible()


# Verify overscrolling past the top of the page does not break the layout
def test_overscroll_past_top_does_not_break_layout(page: Page):
    goto_dashboard(page)
    _hover_over_content(page)

    # Already at the top - scroll "up" repeatedly (bounce/rubber-band territory).
    for _ in range(10):
        page.mouse.wheel(0, -200)
        page.wait_for_timeout(30)

    expect(page.locator("#dashboard")).to_be_attached()
    expect(page.locator("#networksSlider")).to_be_visible()
    expect(page.locator("#statusBox").first).to_be_visible()


# Verify overscrolling past the bottom of the page does not break the layout
def test_overscroll_past_bottom_does_not_break_layout(page: Page):
    goto_dashboard(page)
    _hover_over_content(page)

    for _ in range(15):
        page.mouse.wheel(0, 400)
        page.wait_for_timeout(30)

    expect(page.locator("#dashboard")).to_be_attached()
    expect(page.locator("#networksSlider")).to_be_visible()
    expect(page.locator("#statistics-pane")).to_be_visible()


# Verify horizontal scrolling does not introduce page overflow or break the layout
def test_horizontal_scroll_does_not_break_layout(page: Page):
    goto_dashboard(page)
    _hover_over_content(page)

    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    for _ in range(10):
        page.mouse.wheel(300, 0)
        page.wait_for_timeout(30)

    body_scroll_width = page.evaluate("document.body.scrollWidth")
    viewport_width = page.evaluate("window.innerWidth")
    print(f"\n[mac] after horizontal scroll: body scrollWidth={body_scroll_width}, viewport={viewport_width}")

    assert errors == [], f"Horizontal scrolling threw page errors: {errors}"
    assert body_scroll_width <= viewport_width + 20, "Horizontal scroll introduced page overflow"
    expect(page.locator("#networksSlider")).to_be_visible()


# ---------------------------------------------------------------------------
# Mac window sizes
# ---------------------------------------------------------------------------


def _assert_no_hidden_or_overlapping_critical_elements(page: Page):
    expect(page.locator("#dashboard")).to_be_attached()
    expect(page.locator("#networksSlider")).to_be_attached()
    expect(page.locator("#statusBox").first).to_be_attached()

    nav_box = page.locator("#networksSlider").bounding_box()
    status_box = page.locator("#statusBox").first.bounding_box()
    if nav_box and status_box:
        # The nav slider should sit below the status box, not overlap it.
        assert nav_box["y"] >= status_box["y"], "Nav slider overlaps the status box vertically"


# Verify the layout renders correctly at common macOS display resolutions
@pytest.mark.parametrize("label,size", list(MAC_DISPLAY_SIZES.items()))
def test_renders_at_common_mac_display_sizes(page: Page, label, size):
    width, height = size
    goto_dashboard(page)

    page.set_viewport_size({"width": width, "height": height})
    page.wait_for_timeout(500)
    print(f"\n[mac] {label} ({width}x{height})")

    expect(page.locator("#statusBox").first).to_be_visible()
    expect(page.locator("#networksSlider")).to_be_visible()
    expect(page.locator("#statistics-pane")).to_be_visible()
    _assert_no_hidden_or_overlapping_critical_elements(page)


# Verify the layout adjusts correctly when resizing between MacBook Air and Pro sizes
def test_resizing_between_macbook_air_and_pro_sizes_adjusts_layout(page: Page):
    goto_dashboard(page)

    page.set_viewport_size({"width": 1280, "height": 800})
    page.wait_for_timeout(500)
    small_box = page.locator("#networksSlider").bounding_box()

    page.set_viewport_size({"width": 1728, "height": 1117})
    page.wait_for_timeout(500)
    large_box = page.locator("#networksSlider").bounding_box()

    print(f"\n[mac] nav width at 1280x800: {small_box['width']}, at 1728x1117: {large_box['width']}")
    assert large_box["width"] != small_box["width"], "Layout width didn't adjust with the window size"
    expect(page.locator("#statistics-pane")).to_be_visible()


# Verify the assumed minimum window size has no hidden or overlapping elements
def test_minimum_window_size_has_no_overlapping_or_hidden_elements(page: Page):
    goto_dashboard(page)

    page.set_viewport_size(ASSUMED_MIN_WINDOW_SIZE)
    page.wait_for_timeout(500)

    _assert_no_hidden_or_overlapping_critical_elements(page)
    expect(page.locator("#networksSlider")).to_be_visible()
    expect(page.locator("#statistics-pane")).to_be_visible()


# ---------------------------------------------------------------------------
# Multiple tabs / windows
# ---------------------------------------------------------------------------


# Verify a connection state change in one tab is reflected live in another tab
def test_connection_state_syncs_across_two_tabs(page: Page):
    was_connected = get_state() == "CONNECTED"
    goto_dashboard(page, wait_for=STATUS_TEXT)

    tab2 = page.context.new_page()
    try:
        goto_dashboard(tab2, wait_for=STATUS_TEXT, url="http://localhost:8080/")

        if not was_connected:
            ensure_connected(timeout=30)
            page.wait_for_timeout(500)

        print("\n[mac] disconnecting in tab 1")
        page.locator(TOGGLE).click()
        page.wait_for_timeout(1500)
        wait_for_state(NOT_CONNECTED_STATE, timeout=10)

        expect(tab2.locator(STATUS_TEXT)).to_have_text("Disconnected", timeout=10_000)
        print("[mac] tab 2 reflects the disconnect")

        print("[mac] reconnecting in tab 2")
        tab2.locator(TOGGLE).click()
        wait_for_state("CONNECTED", timeout=30)

        expect(page.locator(STATUS_TEXT)).to_have_text("Connected", timeout=10_000)
        print("[mac] tab 1 reflects the reconnect")
    finally:
        tab2.close()

    page.wait_for_timeout(500)
    expect(page.locator("#networksSlider")).to_be_visible()
    print("[mac] tab 1 still functional after tab 2 closed")


# ---------------------------------------------------------------------------
# Page lifecycle
# ---------------------------------------------------------------------------


# Verify reloading the page while connected still shows the correct connected state
def test_reload_while_connected_shows_correct_state(page: Page):
    connect_and_wait()

    goto_dashboard(page, wait_for=STATUS_TEXT)
    expect(page.locator(STATUS_TEXT)).to_have_text("Connected")

    page.reload()
    page.wait_for_selector(STATUS_TEXT)

    expect(page.locator(STATUS_TEXT)).to_have_text("Connected", timeout=10_000)
    expect(page.locator("#networksSlider")).to_be_visible()


# Verify navigating away and back to the app fully restores the UI
def test_navigate_away_and_back_restores_ui(page: Page):
    goto_dashboard(page)

    page.goto("about:blank")
    page.wait_for_timeout(300)
    assert page.locator("#networksSlider").count() == 0

    goto_dashboard(page)
    expect(page.locator("#networksSlider")).to_be_visible()
    expect(page.locator("#statusBox").first).to_be_visible()


# Verify closing and reopening a browser context loads fresh with the correct daemon state
def test_closing_and_reopening_context_loads_fresh_with_correct_daemon_state(browser: Browser):
    # This deliberately uses a brand-new, disposable context/page rather than the
    # shared session-scoped `page` fixture - closing that one would break every
    # other test file relying on it for the rest of the run.
    connect_and_wait()

    ctx1 = browser.new_context()
    page1 = ctx1.new_page()
    goto_dashboard(page1, wait_for=STATUS_TEXT, url="http://localhost:8080/")
    expect(page1.locator(STATUS_TEXT)).to_have_text("Connected")
    ctx1.close()

    ctx2 = browser.new_context()
    try:
        page2 = ctx2.new_page()
        goto_dashboard(page2, wait_for=STATUS_TEXT, url="http://localhost:8080/")
        expect(page2.locator(STATUS_TEXT)).to_have_text("Connected", timeout=10_000)
        expect(page2.locator("#networksSlider")).to_be_visible()
        print("\n[mac] fresh context loaded with correct (connected) daemon state")
    finally:
        ctx2.close()
