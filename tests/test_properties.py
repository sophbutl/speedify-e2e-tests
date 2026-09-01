"""Property-based tests using Hypothesis.

Unlike the rest of the suite (which checks specific, hand-picked scenarios - a fixed
list of Mac display sizes, one rapid-click stress sequence, etc.), these tests assert
an invariant holds across a wide, randomly-generated range of inputs or action
sequences. Hypothesis looks for the smallest failing example and shrinks to it, so a
failure here points at a specific reproducible edge case rather than "sometimes flaky."

Each real interaction here drives a live browser against the real VPN daemon, which is
slow - example/step counts are kept deliberately small (not the Hypothesis defaults) to
keep runtime reasonable, and the per-example deadline is disabled since a single UI
action can legitimately take longer than Hypothesis's default 200ms budget.
"""

import re

from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule, run_state_machine_as_test
from playwright.sync_api import Page, expect

from helpers.speedify_cli import get_current_server, get_settings, get_state, set_mode
from helpers.ui_helpers import (
    NAV_TABS,
    ONOFF,
    STATUS_TEXT,
    TOGGLE,
    close_settings,
    connect_and_wait,
    disconnect_and_wait,
    goto_dashboard,
    is_nav_tab_active,
    open_settings,
    perform_named_action,
    safe_restore,
    wait_for_connection_settle,
)

# Hypothesis's shrink phase re-runs a failing example many times to minimize it - each
# re-run drives the real, slow browser/daemon again, so a single failure can otherwise
# balloon into many extra minutes. Every test here already prints its generated inputs
# on failure, so shrinking isn't needed to debug - skip it (and the similarly-expensive
# explain phase) everywhere.
NO_SHRINK_PHASES = [p for p in Phase if p not in (Phase.shrink, Phase.explain)]

# UI examples are slow (each one drives a real browser), so keep the example count
# small and disable the default per-example deadline.
UI_SETTINGS = settings(
    max_examples=12,
    phases=NO_SHRINK_PHASES,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


def _assert_no_hidden_or_overlapping_critical_elements(page: Page) -> None:
    expect(page.locator("#dashboard")).to_be_attached()
    expect(page.locator("#networksSlider")).to_be_attached()
    expect(page.locator("#statusBox").first).to_be_attached()

    nav_box = page.locator("#networksSlider").bounding_box()
    status_box = page.locator("#statusBox").first.bounding_box()
    if nav_box and status_box:
        # The nav slider should sit below the status box, not overlap it.
        assert nav_box["y"] >= status_box["y"], "Nav slider overlaps the status box vertically"


# Verify no critical dashboard element is hidden or overlapping at any viewport size in a realistic desktop range
@UI_SETTINGS
@given(
    width=st.integers(min_value=800, max_value=2000),
    height=st.integers(min_value=600, max_value=1200),
)
def test_no_overlap_at_any_viewport_size_in_desktop_range(page: Page, width, height):
    goto_dashboard(page)
    page.set_viewport_size({"width": width, "height": height})
    page.wait_for_timeout(300)

    print(f"\n[property] viewport {width}x{height}")
    _assert_no_hidden_or_overlapping_critical_elements(page)

    # The page/context are shared across the whole suite - always leave the
    # viewport at a known size for whatever test runs next.
    page.set_viewport_size({"width": 1280, "height": 720})


# ---------------------------------------------------------------------------
# Chaotic user simulation
# ---------------------------------------------------------------------------
#
# A "chaotic user" who clicks, scrolls, resizes, changes theme, waits, and reloads
# in any order, in any combination - the invariants below are the properties that
# must survive that, no matter which random moves led there.


# Verify the toggle/status-text agreement, the app's URL, and core DOM elements all
# stay consistent across a chaotic, randomly interleaved mix of every available
# action (toggle, tab clicks, settings open/close, scroll, resize, theme change,
# idle waits, and reloads)
def test_interleaved_toggle_tab_and_settings_actions_stay_consistent(page: Page):
    original_state = get_state()
    original_mode = get_settings()["bondingMode"]
    original_viewport = {"width": 1280, "height": 720}
    goto_dashboard(page)

    class DashboardStateMachine(RuleBasedStateMachine):
        def __init__(self):
            super().__init__()
            self.errors: list[str] = []
            # Tracked deterministically by the rules below, never by querying the
            # live DOM inside a precondition: Hypothesis replays/reruns a recorded
            # choice sequence to verify and (when shrinking) minimize it, and if
            # which rules are "enabled" depends on real, changing external state,
            # that replay can see a different enabled-rule set than the original
            # run and raise FlakyStrategyDefinition. Live DOM checks are fine in
            # invariants and rule bodies - they just can't gate rule *selection*.
            self.in_settings = False
            page.on("pageerror", lambda e: self.errors.append(str(e)))

        @precondition(lambda self: not self.in_settings)
        @rule()
        def click_toggle(self):
            page.locator(TOGGLE).click()
            # Give the class/text a moment to move off any transitional "pending"
            # state; a full wait-for-settle isn't used here since a stuck-pending
            # UI is itself something the invariants below should be able to catch,
            # not something this action should mask by waiting it out.
            page.wait_for_timeout(500)

        @precondition(lambda self: not self.in_settings)
        @rule(tab=st.sampled_from(NAV_TABS))
        def click_tab(self, tab):
            page.locator("#networksSlider").get_by_text(tab, exact=True).click()
            page.wait_for_timeout(150)

        @precondition(lambda self: not self.in_settings)
        @rule()
        def settings_open(self):
            open_settings(page)
            page.wait_for_timeout(200)
            self.in_settings = True

        @precondition(lambda self: self.in_settings)
        @rule()
        def settings_close(self):
            close_settings(page)
            page.wait_for_timeout(200)
            self.in_settings = False

        @precondition(lambda self: not self.in_settings)
        @rule(delta=st.integers(min_value=-500, max_value=500))
        def scroll_random(self, delta):
            page.mouse.wheel(0, delta)
            page.wait_for_timeout(100)

        @rule(
            width=st.integers(min_value=400, max_value=1920),
            height=st.integers(min_value=400, max_value=1200),
        )
        def resize_random(self, width, height):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(150)

        @precondition(lambda self: not self.in_settings)
        @rule(choice=st.sampled_from(["Default", "Light", "Dark"]))
        def change_theme(self, choice):
            open_settings(page)
            page.get_by_text("Theme", exact=True).click()
            page.locator("app-settings-choice-row").get_by_text(choice, exact=True).click()
            page.wait_for_timeout(300)
            # Settings -> Theme is 2 panes deep; goto_dashboard reliably returns to
            # a clean dashboard in one step regardless of nesting depth (a single
            # close_settings() would only pop one level).
            goto_dashboard(page)
            self.in_settings = False

        @rule(ms=st.integers(min_value=500, max_value=2000))
        def wait_random(self, ms):
            page.wait_for_timeout(ms)

        @rule()
        def reload_page(self):
            page.reload()
            page.wait_for_selector("#dashboard", timeout=15_000)
            page.wait_for_timeout(300)
            # Known behavior: reloading while Settings is open keeps the app on the
            # Settings route rather than returning to the dashboard (the #/settings
            # hash survives the reload). This is a one-off check inside a rule's own
            # body to keep our tracked state accurate for later precondition
            # decisions - not a live check used to gate rule selection itself, so it
            # doesn't hit the replay-determinism issue described above.
            self.in_settings = page.locator("app-back-done-button").count() > 0

        @invariant()
        def url_stays_on_local_app(self):
            assert page.url.startswith("http://localhost:8080"), f"Navigated away to {page.url!r}"

        @invariant()
        def toggle_class_and_status_text_agree_on_dashboard(self):
            if self.in_settings:
                return  # not on a screen where the toggle/status text apply
            cls = (page.locator(ONOFF).first.get_attribute("class") or "").split()
            if "pending" in cls:
                return  # mid-transition; nothing to compare yet
            text = page.locator(STATUS_TEXT).inner_text().strip()
            if "off" in cls:
                assert text == "Disconnected", f"class={cls} but status text is {text!r}"
            elif "on" in cls:
                # Redundant mode with only one available adapter shows a distinct
                # caveat text instead of the plain "Connected" - see the note on
                # test_toggle_and_status_agree_after_random_action_sequence below.
                assert text == "Connected" or "Redundant" in text, (
                    f"class={cls} but status text is {text!r}"
                )

        @invariant()
        def core_elements_not_permanently_removed(self):
            # #dashboard is always in the DOM (a zero-height layout wrapper) whether
            # showing the dashboard or a Settings pane stacked on top of it.
            expect(page.locator("#dashboard")).to_be_attached()

        @invariant()
        def no_page_errors_were_thrown(self):
            assert self.errors == [], f"Page threw errors during the run: {self.errors}"

    def _restore_theme_to_default():
        # goto_dashboard first: the chaotic run can leave the page anywhere, including
        # nested inside a Settings sub-page (e.g. #/settings/theme) where a plain
        # "Theme" row isn't there to click - a fresh navigation guarantees a known,
        # plain-dashboard starting point before opening Settings again. Likewise,
        # finish with goto_dashboard rather than close_settings: Settings sub-pages
        # stack (Settings -> Theme is 2 levels), so a single close only pops one -
        # a fresh navigation reliably lands back on a clean dashboard in one step.
        goto_dashboard(page)
        open_settings(page)
        page.get_by_text("Theme", exact=True).click()
        page.locator("app-settings-choice-row").get_by_text("Default", exact=True).click()
        page.wait_for_timeout(300)
        goto_dashboard(page)

    try:
        run_state_machine_as_test(
            DashboardStateMachine,
            settings=settings(
                max_examples=3,
                stateful_step_count=25,
                phases=NO_SHRINK_PHASES,
                deadline=None,
                suppress_health_check=[HealthCheck.function_scoped_fixture],
            ),
        )
    finally:
        # Restore connection state, bonding mode, theme, and viewport regardless of
        # where the chaotic run left them - each step runs independently so one
        # failure (e.g. a stuck sub-page) can't block the others from restoring.
        safe_restore(
            lambda: set_mode(original_mode),
            _restore_theme_to_default,
            lambda: page.set_viewport_size(original_viewport),
            lambda: connect_and_wait() if original_state == "CONNECTED" else disconnect_and_wait(),
        )


# ---------------------------------------------------------------------------
# State consistency
# ---------------------------------------------------------------------------
#
# These check that the toggle, the status text, the CLI, and the data on screen never
# disagree with each other or go stale, no matter what random sequence of
# connect/disconnect/mode-change actions produced the current state.

STATE_ACTIONS = ["connect", "disconnect", "toggle_ui", "mode_speed", "mode_streaming", "mode_redundant"]
MODE_ROW_TEXT = {"speed": "Speed", "streaming": "Speed +", "redundant": "Redundant"}
STATS_LABELS = ["Data Encrypted", "Top Download Speed", "Top Upload Speed"]
TIMER = ".status-box-ServerButtonTextServer"


# Verify the toggle class and status text always agree once the UI settles, no matter
# what random sequence of connect/disconnect/toggle/mode-change actions preceded it
@settings(max_examples=4, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    actions=st.lists(
        st.tuples(st.sampled_from(STATE_ACTIONS), st.integers(min_value=100, max_value=600)),
        min_size=5,
        max_size=10,
    )
)
def test_toggle_and_status_agree_after_random_action_sequence(page: Page, actions):
    original_state = get_state()
    original_mode = get_settings()["bondingMode"]
    print(f"\n[property] {len(actions)} actions: {actions}")
    try:
        goto_dashboard(page, wait_for=TOGGLE)
        for action, wait_ms in actions:
            print(f"[property]   -> {action} (wait {wait_ms}ms)")
            perform_named_action(page, action)
            page.wait_for_timeout(wait_ms)

        # Poll until the toggle leaves any transitional "pending" state.
        onoff = page.locator(ONOFF).first
        for _ in range(40):
            if "pending" not in (onoff.get_attribute("class") or ""):
                break
            page.wait_for_timeout(500)

        cls = (onoff.get_attribute("class") or "").split()
        text = page.locator(STATUS_TEXT).inner_text().strip()
        print(f"[property] settled: class={cls} status={text!r}")
        if "off" in cls:
            assert text == "Disconnected", f"class={cls} but status text is {text!r}"
        elif "on" in cls:
            # Redundant mode with only one available adapter shows a distinct caveat
            # text ("Redundant But Only 1 Connection") instead of the plain
            # "Connected" - a real, legitimate connected state, not a disagreement
            # (discovered by this test: it isn't handled by any other test in the suite).
            assert text == "Connected" or "Redundant" in text, (
                f"class={cls} but status text is {text!r}"
            )
    finally:
        set_mode(original_mode)
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()


# Verify the UI and the CLI report the same connection state once both settle, after
# any random sequence of connect/disconnect/toggle actions
@settings(max_examples=4, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(actions=st.lists(st.sampled_from(["connect", "disconnect", "toggle_ui"]), min_size=3, max_size=8))
def test_ui_and_cli_agree_on_connection_state_after_random_actions(page: Page, actions):
    original_state = get_state()
    print(f"\n[property] actions: {actions}")
    try:
        goto_dashboard(page, wait_for=STATUS_TEXT)
        for action in actions:
            print(f"[property]   -> {action}")
            perform_named_action(page, action)
            page.wait_for_timeout(400)

        cls, text = wait_for_connection_settle(page)
        cli_state = get_state()
        print(f"[property] settled: ui_class={cls} ui_text={text!r} cli_state={cli_state!r}")

        if cli_state == "CONNECTED":
            assert text == "Connected", f"CLI says CONNECTED but UI shows {text!r}"
        else:
            assert text == "Disconnected", f"CLI says {cli_state!r} but UI shows {text!r}"
    finally:
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()


# Verify the connected server's name shows in the status box when connected, and is
# gone once disconnected, after any random sequence of connect/disconnect actions
@settings(max_examples=3, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(actions=st.lists(st.sampled_from(["connect", "disconnect"]), min_size=3, max_size=6))
def test_server_name_visibility_matches_connection_state(page: Page, actions):
    original_state = get_state()
    print(f"\n[property] actions: {actions}")
    try:
        goto_dashboard(page, wait_for=STATUS_TEXT)
        status_box = page.locator("#statusBox").first
        for action in actions:
            print(f"[property]   -> {action}")
            perform_named_action(page, action)
            wait_for_connection_settle(page)

            cli_state = get_state()
            box_text = status_box.inner_text()
            if cli_state == "CONNECTED":
                server_name = get_current_server()["friendlyName"]
                assert server_name in box_text, (
                    f"Connected, but server name {server_name!r} not found in status box: {box_text!r}"
                )
            else:
                assert "Tap to Connect" in box_text, (
                    f"Disconnected, but status box doesn't show the disconnected prompt: {box_text!r}"
                )
    finally:
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()


# Verify the connection timer always resets to near-zero after a fresh reconnect,
# regardless of how long the previous connection had been running
@settings(max_examples=3, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(accumulate_ms=st.integers(min_value=1000, max_value=5000))
def test_connection_timer_resets_on_every_new_connection(page: Page, accumulate_ms):
    original_state = get_state()
    print(f"\n[property] accumulating {accumulate_ms}ms before disconnect/reconnect")
    try:
        connect_and_wait()
        goto_dashboard(page, wait_for=STATUS_TEXT)
        page.wait_for_timeout(accumulate_ms)

        disconnect_and_wait()
        connect_and_wait()
        page.wait_for_timeout(1500)

        timer_text = page.locator(TIMER).nth(1).inner_text()
        print(f"[property] timer after reconnect: {timer_text!r}")
        match = re.search(r"(\d+):(\d+)", timer_text)
        assert match, f"Could not parse timer text {timer_text!r}"
        minutes, seconds = int(match.group(1)), int(match.group(2))
        assert minutes == 0 and seconds < 10, (
            f"Timer shows {timer_text!r} right after reconnecting - looks like it continued "
            "instead of resetting"
        )
    finally:
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()


# Verify adapter speed values are numeric when connected and absent when disconnected -
# never a stale value left over from a previous connection
@settings(max_examples=3, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(actions=st.lists(st.sampled_from(["connect", "disconnect"]), min_size=3, max_size=5))
def test_adapter_speed_values_never_stale_across_connection_changes(page: Page, actions):
    original_state = get_state()
    print(f"\n[property] actions: {actions}")
    try:
        goto_dashboard(page)
        for action in actions:
            print(f"[property]   -> {action}")
            perform_named_action(page, action)
            wait_for_connection_settle(page)
            page.wait_for_timeout(500)

            cli_state = get_state()
            dl_count = page.locator('img[aria-label="Download Speed"]').count()
            if cli_state == "CONNECTED":
                assert dl_count > 0, "Connected, but no Download Speed indicator is present"
                dl_value = (
                    page.locator('img[aria-label="Download Speed"]')
                    .first.locator("xpath=following-sibling::*[1]")
                    .inner_text()
                    .strip()
                )
                print(f"[property]   download speed: {dl_value!r}")
                assert dl_value != "", "Download speed value is blank while connected"
            else:
                assert dl_count == 0, (
                    f"Disconnected, but a stale Download Speed indicator is still present: count={dl_count}"
                )
    finally:
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()


# Verify the UI's Bonding Mode row always matches the CLI's mode, after any random
# sequence of mode changes made via the CLI
@settings(max_examples=3, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(modes=st.lists(st.sampled_from(["speed", "streaming", "redundant"]), min_size=2, max_size=5))
def test_bonding_mode_agrees_between_ui_and_cli_after_random_changes(page: Page, modes):
    original_mode = get_settings()["bondingMode"]
    print(f"\n[property] mode sequence: {modes}")
    try:
        for mode in modes:
            print(f"[property]   -> mode: {mode}")
            set_mode(mode)
            goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
            open_settings(page)
            mode_row = page.get_by_text("Bonding Mode", exact=True)
            expect(mode_row).to_be_visible()
            row_value = mode_row.locator("xpath=following-sibling::*[1]")
            expect(row_value).to_have_text(MODE_ROW_TEXT[mode], timeout=10_000)
            close_settings(page)
    finally:
        set_mode(original_mode)


# Verify the Statistics values never show negative numbers or nonsense text, no matter
# what random sequence of connect/disconnect/toggle/tab-switch actions preceded the check
@settings(max_examples=3, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    actions=st.lists(
        st.sampled_from(["connect", "disconnect", "toggle_ui"] + NAV_TABS), min_size=3, max_size=8
    )
)
def test_statistics_values_never_negative_or_nonsense(page: Page, actions):
    original_state = get_state()
    print(f"\n[property] actions: {actions}")
    try:
        goto_dashboard(page, wait_for="#statistics-pane")
        for action in actions:
            print(f"[property]   -> {action}")
            if action in NAV_TABS:
                page.locator("#networksSlider").get_by_text(action, exact=True).click()
            else:
                perform_named_action(page, action)
            page.wait_for_timeout(300)

        stats = page.locator("#statistics-pane")
        for label in STATS_LABELS:
            value = stats.get_by_text(label, exact=True).locator("xpath=following-sibling::*[1]")
            text = value.inner_text().strip()
            print(f"[property]   {label}: {text!r}")
            assert text != "", f"{label} is blank"
            assert "-" not in text, f"{label} shows a negative-looking value: {text!r}"
            assert "NaN" not in text and "undefined" not in text, f"{label} shows nonsense: {text!r}"
    finally:
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


# Verify random tab-click sequences never throw a JS error or navigate away from the app
@settings(max_examples=4, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(tabs=st.lists(st.sampled_from(NAV_TABS), min_size=10, max_size=20))
def test_random_tab_clicks_never_throw_or_navigate_away(page: Page, tabs):
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    print(f"\n[property] {len(tabs)} tab clicks: {tabs}")
    goto_dashboard(page)
    nav = page.locator("#networksSlider")
    for tab in tabs:
        nav.get_by_text(tab, exact=True).click()
        page.wait_for_timeout(150)
        assert page.url.startswith("http://localhost:8080"), f"Navigated away to {page.url!r}"

    assert errors == [], f"Tab clicking threw page errors: {errors}"
    expect(page.locator("#omniChart")).to_be_visible()


# Verify random settings open/close cycles never break the dashboard afterward
@settings(max_examples=4, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(delays_ms=st.lists(st.integers(min_value=100, max_value=600), min_size=3, max_size=10))
def test_random_settings_open_close_cycles_never_break_dashboard(page: Page, delays_ms):
    print(f"\n[property] {len(delays_ms)} open/close cycles, delays={delays_ms}")
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    for i, delay in enumerate(delays_ms):
        open_settings(page)
        page.wait_for_timeout(delay)
        if page.locator("app-back-done-button").count() == 0:
            # Known Bug 1 (see test_stress.py): rapid settings open/close can drop
            # the open click. Note it and move on instead of hanging on a doomed
            # close click - this test is about the dashboard surviving, not about
            # re-proving Bug 1 itself.
            print(f"[property]   cycle {i + 1}/{len(delays_ms)}: settings-drop (Bug 1) reproduced, skipping close")
        else:
            close_settings(page)
        page.wait_for_timeout(delay)
        print(f"[property]   cycle {i + 1}/{len(delays_ms)} (delay {delay}ms) done")

    expect(page.locator("#networksSlider")).to_be_visible()
    expect(page.locator(STATUS_TEXT)).to_be_visible()
    expect(page.locator(TOGGLE)).to_be_visible()


# Verify navigating back to the dashboard always attaches all core elements, no matter
# what random mix of actions happened first
@settings(max_examples=4, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(actions=st.lists(st.sampled_from(NAV_TABS + ["toggle_ui", "open_settings"]), min_size=3, max_size=10))
def test_dashboard_core_elements_always_attached_after_random_actions(page: Page, actions):
    original_state = get_state()
    print(f"\n[property] actions: {actions}")
    try:
        goto_dashboard(page)
        for action in actions:
            print(f"[property]   -> {action}")
            if action in NAV_TABS:
                page.locator("#networksSlider").get_by_text(action, exact=True).click()
            elif action == "toggle_ui":
                page.locator(TOGGLE).click()
            elif action == "open_settings":
                open_settings(page)
                page.wait_for_timeout(200)
                if page.locator("app-back-done-button").count() > 0:
                    close_settings(page)
                else:
                    print("[property]     settings-drop (Bug 1) reproduced, skipping close")
            page.wait_for_timeout(200)

        goto_dashboard(page)
        expect(page.locator(TOGGLE)).to_be_attached()
        expect(page.locator("#networksSlider")).to_be_attached()
        expect(page.locator(STATUS_TEXT)).to_be_attached()
    finally:
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()


# Verify exactly one nav tab is ever active - matching the last one clicked - never two,
# never zero, no matter the random click sequence
@settings(max_examples=5, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(tabs=st.lists(st.sampled_from(NAV_TABS), min_size=5, max_size=15))
def test_exactly_one_nav_tab_is_ever_active(page: Page, tabs):
    print(f"\n[property] tab sequence: {tabs}")
    goto_dashboard(page)
    nav = page.locator("#networksSlider")
    tab_locators = {name: nav.get_by_text(name, exact=True) for name in NAV_TABS}

    for tab in tabs:
        tab_locators[tab].click()
        page.wait_for_timeout(200)
        active = [name for name, loc in tab_locators.items() if is_nav_tab_active(loc)]
        print(f"[property]   clicked {tab!r} -> active tabs: {active}")
        assert active == [tab], f"Expected only {tab!r} active, got {active}"


# Verify Settings always opens successfully regardless of connection state at the time
@settings(max_examples=4, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(pre_state=st.sampled_from(["connected", "disconnected", "mid_transition"]))
def test_settings_always_opens_regardless_of_connection_state(page: Page, pre_state):
    original_state = get_state()
    print(f"\n[property] pre-state: {pre_state}")
    try:
        goto_dashboard(page, wait_for=TOGGLE)
        if pre_state == "connected":
            connect_and_wait()
        elif pre_state == "disconnected":
            disconnect_and_wait()
        else:  # mid_transition: fire the CLI call but don't wait for it to settle
            if get_state() == "CONNECTED":
                perform_named_action(page, "disconnect")
            else:
                perform_named_action(page, "connect")
            page.wait_for_timeout(200)

        open_settings(page)
        expect(page.locator("app-back-done-button")).to_be_visible(timeout=10_000)
        close_settings(page)
    finally:
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()


# Verify closing Settings always returns to a fully functional dashboard, regardless of
# connection state at the time
@settings(max_examples=4, phases=NO_SHRINK_PHASES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(pre_state=st.sampled_from(["connected", "disconnected", "mid_transition"]))
def test_closing_settings_always_returns_to_functional_dashboard(page: Page, pre_state):
    original_state = get_state()
    print(f"\n[property] pre-state: {pre_state}")
    try:
        goto_dashboard(page, wait_for=TOGGLE)
        if pre_state == "connected":
            connect_and_wait()
        elif pre_state == "disconnected":
            disconnect_and_wait()
        else:
            if get_state() == "CONNECTED":
                perform_named_action(page, "disconnect")
            else:
                perform_named_action(page, "connect")
            page.wait_for_timeout(200)

        open_settings(page)
        page.wait_for_timeout(300)
        close_settings(page)

        expect(page.locator("#networksSlider")).to_be_visible()
        expect(page.locator(STATUS_TEXT)).to_be_visible()
        expect(page.locator(TOGGLE)).to_be_visible()
    finally:
        if original_state == "CONNECTED":
            connect_and_wait()
        else:
            disconnect_and_wait()
