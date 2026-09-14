"""More property-based tests using Hypothesis - continued from test_properties.py.

Split out purely for file length; see test_properties.py's module docstring for the
general approach (small example counts, disabled deadline, restore-in-finally
discipline). This file covers: toggle resilience, graph/live-data rendering, layout
and viewport edge cases, theme/display, mixed CLI+UI interaction, and page lifecycle.
"""

import pytest
from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st
from playwright.sync_api import Browser, Page, expect

from helpers.speedify_cli import connect, disconnect, get_settings, get_state, set_mode
from helpers.ui_helpers import (
    NAV_TABS,
    ONOFF,
    STATUS_TEXT,
    TOGGLE,
    close_settings,
    connect_and_wait,
    disconnect_and_wait,
    ensure_connected,
    goto_dashboard,
    is_nav_tab_active,
    open_settings,
    safe_restore,
    wait_for_connection_settle,
)

pytestmark = pytest.mark.slow

# See test_properties.py's module docstring: skip Hypothesis's shrink/explain phases,
# since re-running a failing example against a real, slow browser+daemon to minimize
# it can cost many extra minutes, and every test here already prints its generated
# inputs on failure.
NO_SHRINK_PHASES = [p for p in Phase if p not in (Phase.shrink, Phase.explain)]

THEME_CHOICES = ["Default", "Light", "Dark"]  # "Default" follows the OS ("system") theme
MODE_ROW_TEXT = {"speed": "Speed", "streaming": "Speed +", "redundant": "Redundant"}


# ---------------------------------------------------------------------------
# Toggle resilience
# ---------------------------------------------------------------------------


# Verify any sequence of toggle clicks (even mid-pending) eventually settles to a
# consistent on/off state within 30 seconds of the last click
@settings(max_examples=3, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(num_clicks=st.integers(min_value=5, max_value=10))
def test_toggle_clicks_always_settle_within_30_seconds(page: Page, num_clicks):
    original_state = get_state()
    print(f"\n[property] {num_clicks} toggle clicks")
    try:
        goto_dashboard(page, wait_for=TOGGLE)
        toggle = page.locator(TOGGLE)
        onoff = page.locator(ONOFF).first
        for i in range(num_clicks):
            toggle.click()
            print(f"[property]   click {i + 1}/{num_clicks} -> class={onoff.get_attribute('class')!r}")
            page.wait_for_timeout(300)

        settled = False
        for _ in range(60):
            if "pending" not in (onoff.get_attribute("class") or ""):
                settled = True
                break
            page.wait_for_timeout(500)
        assert settled, "Toggle never left the pending state within 30s of the last click"

        cls = (onoff.get_attribute("class") or "").split()
        assert "on" in cls or "off" in cls, f"Toggle settled to an unrecognized class: {cls}"
    finally:
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()


# Verify the UI stays responsive after any toggle-click sequence - the toggle remains
# attached and the status text is never left blank
@settings(max_examples=3, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(num_clicks=st.integers(min_value=3, max_value=8))
def test_ui_remains_responsive_after_toggle_click_sequence(page: Page, num_clicks):
    original_state = get_state()
    print(f"\n[property] {num_clicks} toggle clicks")
    try:
        goto_dashboard(page, wait_for=TOGGLE)
        toggle = page.locator(TOGGLE)
        for i in range(num_clicks):
            toggle.click()
            page.wait_for_timeout(400)

        wait_for_connection_settle(page)
        expect(toggle).to_be_attached()
        status_text = page.locator(STATUS_TEXT).inner_text().strip()
        print(f"[property] status text after sequence: {status_text!r}")
        assert status_text != "", "Status text is blank after the toggle sequence"
    finally:
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()


MIXED_TOGGLE_ACTIONS = ["toggle", "settings_cycle"] + [f"tab:{t}" for t in NAV_TABS]


# Verify clicking the toggle interleaved with tab switches and settings open/close
# never permanently freezes it
@settings(max_examples=3, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(actions=st.lists(st.sampled_from(MIXED_TOGGLE_ACTIONS), min_size=4, max_size=8))
def test_toggle_does_not_freeze_when_mixed_with_other_actions(page: Page, actions):
    original_state = get_state()
    print(f"\n[property] mixed actions: {actions}")
    try:
        goto_dashboard(page, wait_for=TOGGLE)
        for action in actions:
            print(f"[property]   -> {action}")
            if action == "toggle":
                page.locator(TOGGLE).click()
            elif action == "settings_cycle":
                open_settings(page)
                page.wait_for_timeout(150)
                if page.locator("app-back-done-button").count() > 0:
                    close_settings(page)
                else:
                    print("[property]     settings-drop (Bug 1) reproduced, skipping close")
            elif action.startswith("tab:"):
                tab_name = action.split(":", 1)[1]
                # The nav tab bar only renders while connected - it's simply absent
                # from the DOM while disconnected, not a timing issue (confirmed by
                # polling for 60s with no change). Skip gracefully if it's not there.
                tab_locator = page.locator("#networksSlider").get_by_text(tab_name, exact=True)
                if tab_locator.count() > 0:
                    tab_locator.click()
                else:
                    print("[property]     nav tab bar not present (disconnected), skipping click")
            page.wait_for_timeout(250)

        onoff = page.locator(ONOFF).first
        settled = False
        for _ in range(60):
            if "pending" not in (onoff.get_attribute("class") or ""):
                settled = True
                break
            page.wait_for_timeout(500)
        assert settled, "Toggle stayed frozen in a pending state after mixed actions"
    finally:
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()


# Verify a page reload after any toggle sequence still shows the daemon's real state
@settings(max_examples=3, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(num_clicks=st.integers(min_value=2, max_value=5))
def test_reload_after_toggle_sequence_shows_correct_daemon_state(page: Page, num_clicks):
    original_state = get_state()
    print(f"\n[property] {num_clicks} toggle clicks before reload")
    try:
        goto_dashboard(page, wait_for=TOGGLE)
        toggle = page.locator(TOGGLE)
        for i in range(num_clicks):
            toggle.click()
            page.wait_for_timeout(500)
        wait_for_connection_settle(page)

        cli_state = get_state()
        page.reload()
        page.wait_for_selector(STATUS_TEXT, timeout=15_000)
        expected_text = "Connected" if cli_state == "CONNECTED" else "Disconnected"
        expect(page.locator(STATUS_TEXT)).to_have_text(expected_text, timeout=10_000)
        print(f"[property] cli_state={cli_state!r}, UI after reload matches")
    finally:
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()


# ---------------------------------------------------------------------------
# Graph and live data
# ---------------------------------------------------------------------------


# Verify the graph canvas always has non-zero dimensions on Networks, after any
# random sequence of tab switches
@settings(max_examples=4, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(tabs=st.lists(st.sampled_from(NAV_TABS), min_size=10, max_size=15))
def test_graph_has_nonzero_dimensions_after_random_tab_switches(page: Page, tabs):
    print(f"\n[property] tab sequence: {tabs}")
    goto_dashboard(page)
    nav = page.locator("#networksSlider")
    for tab in tabs:
        nav.get_by_text(tab, exact=True).click()
        page.wait_for_timeout(150)

    nav.get_by_text("Networks", exact=True).click()
    page.wait_for_timeout(400)
    chart = page.locator("#omniChart")
    expect(chart).to_be_visible()
    box = chart.bounding_box()
    print(f"[property] final canvas box: {box}")
    assert box["width"] > 0 and box["height"] > 0, f"Graph canvas has zero size: {box}"


# Verify the graph canvas never overflows its container, at any random viewport size
@settings(max_examples=5, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    width=st.integers(min_value=800, max_value=2000),
    height=st.integers(min_value=600, max_value=1200),
)
def test_graph_canvas_never_overflows_container_at_any_viewport_size(page: Page, width, height):
    print(f"\n[property] viewport {width}x{height}")
    goto_dashboard(page, wait_for="#omniChartArea")
    page.set_viewport_size({"width": width, "height": height})
    page.wait_for_timeout(300)

    tol = 10
    chart_box = page.locator("#omniChart").bounding_box()
    area_box = page.locator("#omniChartArea").bounding_box()
    assert chart_box is not None and area_box is not None
    assert chart_box["x"] >= area_box["x"] - tol
    assert chart_box["x"] + chart_box["width"] <= area_box["x"] + area_box["width"] + tol
    assert chart_box["y"] >= area_box["y"] - tol
    assert chart_box["y"] + chart_box["height"] <= area_box["y"] + area_box["height"] + tol

    page.set_viewport_size({"width": 1280, "height": 720})


# Verify the graph canvas still exists and renders with non-zero size after any
# random connect/disconnect cycle
@settings(max_examples=3, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(num_toggles=st.integers(min_value=3, max_value=5))
def test_graph_renders_after_connect_disconnect_cycles(page: Page, num_toggles):
    original_state = get_state()
    print(f"\n[property] {num_toggles} toggle clicks")
    try:
        goto_dashboard(page, wait_for=TOGGLE)
        toggle = page.locator(TOGGLE)
        for i in range(num_toggles):
            toggle.click()
            page.wait_for_timeout(500)
        wait_for_connection_settle(page)

        # The Networks tab (and its graph) only render while connected - the random
        # toggle count can legitimately leave us disconnected, but this test is
        # specifically about the graph surviving a connect/disconnect cycle, so make
        # sure we land back on a connected, graph-showing state before checking it.
        ensure_connected()
        page.wait_for_timeout(500)

        page.locator("#networksSlider").get_by_text("Networks", exact=True).click()
        page.wait_for_timeout(400)
        chart = page.locator("#omniChart")
        expect(chart).to_be_visible()
        box = chart.bounding_box()
        print(f"[property] canvas box: {box}")
        assert box["width"] > 0 and box["height"] > 0
    finally:
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()


# ---------------------------------------------------------------------------
# Layout and viewport
# ---------------------------------------------------------------------------


# Verify no JS errors occur and core elements stay in the DOM at any random viewport
# size, including extreme small/large sizes outside the realistic-desktop range
@settings(max_examples=5, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    width=st.integers(min_value=300, max_value=2500),
    height=st.integers(min_value=200, max_value=1500),
)
def test_no_js_errors_and_core_elements_remain_at_any_viewport_size(page: Page, width, height):
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    print(f"\n[property] viewport {width}x{height}")
    goto_dashboard(page)
    page.set_viewport_size({"width": width, "height": height})
    page.wait_for_timeout(400)

    expect(page.locator(TOGGLE)).to_be_attached()
    expect(page.locator(STATUS_TEXT)).to_be_attached()
    expect(page.locator("#networksSlider")).to_be_attached()
    assert errors == [], f"Page threw errors at {width}x{height}: {errors}"

    page.set_viewport_size({"width": 1280, "height": 720})


# Verify scrolling by any random amount never pushes past the actual page bounds
@settings(max_examples=5, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(scroll_amounts=st.lists(st.integers(min_value=-3000, max_value=3000), min_size=5, max_size=10))
def test_scrolling_never_exceeds_page_bounds(page: Page, scroll_amounts):
    print(f"\n[property] scroll amounts: {scroll_amounts}")
    goto_dashboard(page)
    box = page.locator("#networksSlider").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

    for amount in scroll_amounts:
        page.mouse.wheel(0, amount)
        page.wait_for_timeout(100)
        scroll_y, max_scroll = page.evaluate(
            "[window.scrollY, document.body.scrollHeight - window.innerHeight]"
        )
        print(f"[property]   scrolled {amount} -> scrollY={scroll_y}, max={max_scroll}")
        assert scroll_y >= -1, f"scrollY went negative: {scroll_y}"
        assert scroll_y <= max(max_scroll, 0) + 1, f"scrollY {scroll_y} exceeds page bounds (max {max_scroll})"


# Verify alternating resize/scroll/resize sequences never crash the page or remove
# core elements from the DOM
@settings(max_examples=4, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    steps=st.lists(
        st.tuples(
            st.integers(min_value=400, max_value=1920),
            st.integers(min_value=400, max_value=1200),
            st.integers(min_value=-1000, max_value=1000),
        ),
        min_size=5,
        max_size=8,
    )
)
def test_resize_scroll_resize_sequences_never_crash_or_remove_elements(page: Page, steps):
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    print(f"\n[property] {len(steps)} resize/scroll/resize steps")
    goto_dashboard(page)

    for width, height, scroll_amount in steps:
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_timeout(150)
        page.mouse.wheel(0, scroll_amount)
        page.wait_for_timeout(150)
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_timeout(150)
        print(f"[property]   {width}x{height}, scroll {scroll_amount}")

    assert errors == [], f"Page threw errors during resize/scroll sequence: {errors}"
    expect(page.locator("#dashboard")).to_be_attached()
    expect(page.locator("#networksSlider")).to_be_attached()

    page.set_viewport_size({"width": 1280, "height": 720})


# Verify resizing the viewport mid-animation (right as Settings opens) doesn't break the layout
@settings(max_examples=4, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(width=st.integers(min_value=600, max_value=1920), height=st.integers(min_value=500, max_value=1200))
def test_resizing_during_settings_open_animation_does_not_break_layout(page: Page, width, height):
    print(f"\n[property] resizing to {width}x{height} immediately after opening Settings")
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    page.set_viewport_size({"width": width, "height": height})
    page.wait_for_timeout(400)

    expect(page.locator("app-back-done-button")).to_be_visible(timeout=10_000)
    close_settings(page)
    expect(page.locator("#networksSlider")).to_be_visible()
    expect(page.locator(STATUS_TEXT)).to_be_visible()

    page.set_viewport_size({"width": 1280, "height": 720})


# ---------------------------------------------------------------------------
# Theme and display
# ---------------------------------------------------------------------------


# Verify switching between Default/Light/Dark themes in any order never hides core elements
@settings(max_examples=3, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(choices=st.lists(st.sampled_from(THEME_CHOICES), min_size=5, max_size=8))
def test_theme_switches_in_any_order_never_hide_core_elements(page: Page, choices):
    print(f"\n[property] theme sequence: {choices}")
    try:
        goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
        for choice in choices:
            print(f"[property]   -> {choice}")
            open_settings(page)
            page.get_by_text("Theme", exact=True).click()
            page.locator("app-settings-choice-row").get_by_text(choice, exact=True).click()
            page.wait_for_timeout(400)
            # Settings -> Theme is 2 panes deep, so a single close_settings() only
            # pops one - goto_dashboard reliably lands back on a clean dashboard
            # in one step regardless of nesting depth.
            goto_dashboard(page)

            expect(page.locator(TOGGLE)).to_be_visible()
            expect(page.locator(STATUS_TEXT)).to_be_visible()
            expect(page.locator("#networksSlider")).to_be_visible()
    finally:
        # Restore the Default theme regardless of where the sequence left it. The
        # steps are inherently dependent (each needs the previous to have worked), so
        # this is one try/except rather than independent safe_restore steps - the
        # point here is just "don't let a restore failure escape and mask the real
        # test outcome," not "let later independent steps run if an earlier one fails."
        try:
            goto_dashboard(page)
            open_settings(page)
            page.get_by_text("Theme", exact=True).click()
            page.locator("app-settings-choice-row").get_by_text("Default", exact=True).click()
            goto_dashboard(page)
        except Exception as exc:
            print(f"[restore] WARNING: theme restore failed: {exc}")


# Verify the toggle, nav tabs, and settings button all remain genuinely clickable
# after any theme change (not just visible)
@settings(max_examples=3, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(choice=st.sampled_from(THEME_CHOICES))
def test_interactive_elements_remain_clickable_after_theme_change(page: Page, choice):
    original_state = get_state()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    print(f"\n[property] theme: {choice}")
    try:
        goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
        open_settings(page)
        page.get_by_text("Theme", exact=True).click()
        page.locator("app-settings-choice-row").get_by_text(choice, exact=True).click()
        page.wait_for_timeout(400)
        # Settings -> Theme is 2 panes deep; goto_dashboard reliably returns to a
        # clean dashboard in one step regardless of nesting depth.
        goto_dashboard(page)

        page.locator("#networksSlider").get_by_text("Traffic", exact=True).click()
        page.wait_for_timeout(200)
        page.locator("#networksSlider").get_by_text("Networks", exact=True).click()
        page.wait_for_timeout(200)
        page.locator(TOGGLE).click()
        wait_for_connection_settle(page)
        open_settings(page)
        expect(page.locator("app-back-done-button")).to_be_visible()
        close_settings(page)  # only 1 pane deep here, a single close is enough

        assert errors == [], f"Clicking around after a theme change threw errors: {errors}"
    finally:

        def _restore_theme():
            goto_dashboard(page)
            open_settings(page)
            page.get_by_text("Theme", exact=True).click()
            page.locator("app-settings-choice-row").get_by_text("Default", exact=True).click()
            goto_dashboard(page)

        safe_restore(
            _restore_theme,
            lambda: connect_and_wait() if original_state == "CONNECTED" else disconnect_and_wait(),
        )


# ---------------------------------------------------------------------------
# CLI and UI mixed interaction
# ---------------------------------------------------------------------------

MIXED_CLI_UI_ACTIONS = ["ui_toggle", "cli_connect", "cli_disconnect"]


# Verify any interleaving of UI toggle clicks and CLI connect/disconnect commands
# eventually reaches a state where the CLI and UI agree, within 30 seconds
@settings(max_examples=3, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(actions=st.lists(st.sampled_from(MIXED_CLI_UI_ACTIONS), min_size=5, max_size=8))
def test_mixed_cli_and_ui_actions_eventually_reach_agreement(page: Page, actions):
    original_state = get_state()
    print(f"\n[property] mixed actions: {actions}")
    try:
        goto_dashboard(page, wait_for=STATUS_TEXT)
        for action in actions:
            print(f"[property]   -> {action}")
            if action == "ui_toggle":
                page.locator(TOGGLE).click()
            elif action == "cli_connect":
                connect()
            elif action == "cli_disconnect":
                disconnect()
            page.wait_for_timeout(300)

        agreed = False
        cli_state = ui_text = None
        for _ in range(60):  # 60 * 500ms = 30s
            cli_state = get_state()
            ui_text = page.locator(STATUS_TEXT).inner_text().strip()
            if (cli_state == "CONNECTED") == (ui_text == "Connected") and ui_text in (
                "Connected",
                "Disconnected",
            ):
                agreed = True
                break
            page.wait_for_timeout(500)

        print(f"[property] final: cli={cli_state!r} ui={ui_text!r} agreed={agreed}")
        assert agreed, f"CLI ({cli_state}) and UI ({ui_text!r}) never agreed within 30s"
    finally:
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()


# Verify connecting via the CLI updates the UI to "Connected" within 15s, with no page refresh
@settings(max_examples=3, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(pre_wait_ms=st.integers(min_value=0, max_value=1000))
def test_cli_connect_updates_ui_within_15_seconds_without_refresh(page: Page, pre_wait_ms):
    original_state = get_state()
    print(f"\n[property] pre_wait={pre_wait_ms}ms")
    try:
        disconnect_and_wait()
        goto_dashboard(page, wait_for=STATUS_TEXT)
        expect(page.locator(STATUS_TEXT)).to_have_text("Disconnected")

        page.wait_for_timeout(pre_wait_ms)
        connect()
        expect(page.locator(STATUS_TEXT)).to_have_text("Connected", timeout=15_000)
    finally:
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()


# Verify disconnecting via the CLI updates the UI to "Disconnected" within 15s
@settings(max_examples=3, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(pre_wait_ms=st.integers(min_value=0, max_value=1000))
def test_cli_disconnect_updates_ui_within_15_seconds(page: Page, pre_wait_ms):
    original_state = get_state()
    print(f"\n[property] pre_wait={pre_wait_ms}ms")
    try:
        connect_and_wait()
        goto_dashboard(page, wait_for=STATUS_TEXT)
        expect(page.locator(STATUS_TEXT)).to_have_text("Connected")

        page.wait_for_timeout(pre_wait_ms)
        disconnect()
        expect(page.locator(STATUS_TEXT)).to_have_text("Disconnected", timeout=15_000)
    finally:
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()


# Verify changing the bonding mode via the CLI while Settings is open in the UI is
# reflected once the mode row is reopened
@settings(max_examples=3, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(mode=st.sampled_from(["speed", "streaming", "redundant"]))
def test_cli_mode_change_while_settings_open_reflects_after_reopen(page: Page, mode):
    original_mode = get_settings()["bondingMode"]
    print(f"\n[property] mode: {mode}")
    try:
        goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
        open_settings(page)

        set_mode(mode)
        page.wait_for_timeout(500)

        close_settings(page)
        open_settings(page)
        mode_row = page.get_by_text("Bonding Mode", exact=True)
        expect(mode_row).to_be_visible()
        row_value = mode_row.locator("xpath=following-sibling::*[1]")
        expect(row_value).to_have_text(MODE_ROW_TEXT[mode], timeout=10_000)
        close_settings(page)
    finally:
        set_mode(original_mode)


# ---------------------------------------------------------------------------
# Page lifecycle
# ---------------------------------------------------------------------------


# Verify a reload inserted at any random point in an action sequence still leaves the
# UI showing the correct daemon state afterward
@settings(max_examples=4, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    actions=st.lists(st.sampled_from(["connect", "disconnect", "toggle_ui"]), min_size=3, max_size=5),
    reload_at=st.integers(min_value=0, max_value=4),
)
def test_reload_inserted_at_random_point_shows_correct_state_after(page: Page, actions, reload_at):
    original_state = get_state()
    reload_index = min(reload_at, len(actions))
    print(f"\n[property] actions={actions}, reload after index {reload_index}")
    try:
        goto_dashboard(page, wait_for=STATUS_TEXT)
        for i, action in enumerate(actions):
            if i == reload_index:
                page.reload()
                page.wait_for_selector(STATUS_TEXT, timeout=15_000)
                print("[property]   -- reload --")
            print(f"[property]   -> {action}")
            if action == "connect":
                connect()
            elif action == "disconnect":
                disconnect()
            elif action == "toggle_ui":
                page.locator(TOGGLE).click()
            page.wait_for_timeout(400)
        if reload_index >= len(actions):
            page.reload()
            page.wait_for_selector(STATUS_TEXT, timeout=15_000)
            print("[property]   -- reload (at end) --")

        wait_for_connection_settle(page)
        cli_state = get_state()
        ui_text = page.locator(STATUS_TEXT).inner_text().strip()
        print(f"[property] final: cli={cli_state!r} ui={ui_text!r}")
        expected_text = "Connected" if cli_state == "CONNECTED" else "Disconnected"
        assert ui_text == expected_text, f"CLI={cli_state!r} but UI shows {ui_text!r}"
    finally:
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()


# Verify navigating to about:blank and back to "/" always recovers the correct daemon state
@settings(max_examples=3, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(target=st.sampled_from(["connected", "disconnected"]))
def test_navigate_to_blank_and_back_recovers_correct_state(page: Page, target):
    original_state = get_state()
    print(f"\n[property] target pre-state: {target}")
    try:
        if target == "connected":
            connect_and_wait()
        else:
            disconnect_and_wait()

        goto_dashboard(page)
        page.goto("about:blank")
        page.wait_for_timeout(300)
        assert page.locator("#networksSlider").count() == 0

        goto_dashboard(page)
        expected_text = "Connected" if target == "connected" else "Disconnected"
        expect(page.locator(STATUS_TEXT)).to_have_text(expected_text, timeout=10_000)
        expect(page.locator("#networksSlider")).to_be_visible()
    finally:
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()


# Verify the page stays responsive after a 15-20s idle period following some actions
@settings(max_examples=3, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(idle_seconds=st.integers(min_value=15, max_value=20))
def test_page_stays_responsive_after_idle_period(page: Page, idle_seconds):
    print(f"\n[property] idling for {idle_seconds}s")
    goto_dashboard(page)
    page.locator("#networksSlider").get_by_text("Traffic", exact=True).click()
    page.wait_for_timeout(300)
    page.locator("#networksSlider").get_by_text("Networks", exact=True).click()
    page.wait_for_timeout(300)

    page.wait_for_timeout(idle_seconds * 1000)

    toggle = page.locator(TOGGLE)
    expect(toggle).to_be_visible()
    tab = page.locator("#networksSlider").get_by_text("Traffic", exact=True)
    tab.click()
    page.wait_for_timeout(300)
    assert is_nav_tab_active(tab), "Tab click had no effect after idling"
    page.locator("#networksSlider").get_by_text("Networks", exact=True).click()


# Verify a second browser context survives independently - closing one context leaves
# the other fully functional and showing the correct state
@settings(max_examples=3, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(close_first=st.booleans())
def test_second_context_survives_independently_after_the_other_closes(browser: Browser, close_first):
    original_state = get_state()
    print(f"\n[property] closing {'first' if close_first else 'second'} context")
    ctx1 = browser.new_context()
    ctx2 = browser.new_context()
    try:
        page1 = ctx1.new_page()
        page2 = ctx2.new_page()
        goto_dashboard(page1, url="http://localhost:8080/")
        goto_dashboard(page2, url="http://localhost:8080/")

        page1.locator(TOGGLE).click()
        page1.wait_for_timeout(800)
        page2.locator(TOGGLE).click()
        page2.wait_for_timeout(800)

        if close_first:
            ctx1.close()
            survivor = page2
        else:
            ctx2.close()
            survivor = page1

        expect(survivor.locator(TOGGLE)).to_be_visible()
        # Wait for a true settle rather than checking immediately: the daemon can
        # pass through transitional status text (e.g. "Testing servers" while
        # auto-selecting a server) that isn't "Connected" or "Disconnected" yet, and
        # a fixed short wait can catch it mid-transition.
        _, ui_text = wait_for_connection_settle(survivor, timeout_ms=30_000)
        cli_state = get_state()
        expected_text = "Connected" if cli_state == "CONNECTED" else "Disconnected"
        assert ui_text == expected_text, f"CLI={cli_state!r} but surviving context settled to {ui_text!r}"

        survivor.locator("#networksSlider").get_by_text("Traffic", exact=True).click()
        survivor.wait_for_timeout(300)
        expect(survivor.locator("#omniChart")).to_be_visible()
    finally:
        for ctx in (ctx1, ctx2):
            try:
                ctx.close()
            except Exception:
                pass
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()
