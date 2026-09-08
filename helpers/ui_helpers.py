"""Shared Playwright helpers for the Speedify UI test suite.

These wrap the setup/teardown patterns that recur across the test files:
loading the dashboard, connecting/disconnecting via the CLI and waiting for
the daemon to catch up, opening/closing Settings, and reading nav-tab state.
"""

from __future__ import annotations

from typing import Optional

from playwright.sync_api import Page

from helpers.speedify_cli import NOT_CONNECTED_STATE, connect, disconnect, get_state, set_mode, wait_for_state

# Selectors shared across multiple test files for the connect/disconnect toggle.
TOGGLE = "#navbar-onoff"
ONOFF = "#onOff"
STATUS_TEXT = "#status-box-ServerButtonTextStatus"

# The 5 dashboard nav tabs, in their on-screen order.
NAV_TABS = ["Networks", "Traffic", "Latency", "Loss", "Local"]


def goto_dashboard(
    page: Page,
    wait_for: str = "#networksSlider",
    url: str = "/",
    timeout: Optional[float] = None,
) -> None:
    """Navigates to the dashboard and waits for the given element to appear."""
    page.goto(url)
    page.wait_for_selector(wait_for, timeout=timeout)


def connect_and_wait(timeout: float = 30) -> None:
    """Connects via the CLI and waits until the daemon reports CONNECTED."""
    connect()
    wait_for_state("CONNECTED", timeout=timeout)


def disconnect_and_wait(timeout: float = 10) -> None:
    """Disconnects via the CLI and waits until the daemon reports the not-connected state."""
    disconnect()
    wait_for_state(NOT_CONNECTED_STATE, timeout=timeout)


def safe_restore(*steps) -> None:
    """Runs each zero-arg teardown callable in turn, independently of the others.

    A `finally` block with several sequential restore statements is only as safe as
    its flakiest line - if step 2 raises (a click that times out, an element that
    isn't where a prior test left it), steps 3+ never run and whatever they were
    supposed to restore (viewport, connection state, theme, ...) stays broken for
    every test that follows, since `page` is shared across the whole session. Each
    step here gets its own try/except so one failure can't block the rest; failures
    are printed (not swallowed) so they stay visible in test output.
    """
    for step in steps:
        try:
            step()
        except Exception as exc:
            print(f"[restore] WARNING: a teardown step failed and was skipped: {exc}")


def ensure_connected(timeout: float = 30) -> None:
    """Connects via the CLI only if not already connected, then waits for CONNECTED."""
    if get_state() != "CONNECTED":
        connect_and_wait(timeout)


def open_settings(page: Page, timeout: Optional[float] = None) -> None:
    """Clicks the Settings button to open the Settings panel."""
    page.locator('button[aria-label="Settings Button"]').click(timeout=timeout)


def close_settings(page: Page, timeout: Optional[float] = None) -> None:
    """Clicks the Back/Done button to close the Settings panel (or one level of it).

    Settings sub-pages stack (e.g. Settings -> Theme leaves two app-back-done-button
    elements in the DOM at once - one per pane). .last targets the topmost pane's
    button; an unqualified locator can resolve to a stale one from an underlying pane
    that's visually covered and never becomes clickable, hanging until the timeout
    (discovered via property testing - nothing else in the suite closes Settings from
    a nested sub-page). One call pops one level; call it again to go up further.
    """
    page.locator("app-back-done-button").last.click(timeout=timeout)


def click_settings_row(page: Page, label: str, timeout: Optional[float] = None) -> None:
    """Clicks a Settings row (or a Settings sub-page's choice row) by its exact text.

    Uses `.last`: Settings sub-pages stack in the DOM rather than replacing the
    previous view, and some row labels (e.g. "Bypass") also appear as headings on
    the dashboard underneath - `.first` can silently click the wrong (non-Settings)
    element instead of the current, topmost pane's row.
    """
    page.get_by_text(label, exact=True).last.click(timeout=timeout)


def is_nav_tab_active(tab) -> bool:
    """Returns whether a Networks-slider nav tab locator is in its active state."""
    cls = tab.get_attribute("class") or ""
    return "darkText" in cls and "darkText40" not in cls


def perform_named_action(page: Page, action: str) -> None:
    """Dispatches a property-test action by name.

    Recognizes "connect", "disconnect", "toggle_ui", and "mode_<speed|streaming|redundant>"
    - shared across the property test files so their Hypothesis-generated action
    sequences can name a small, consistent vocabulary of state-changing moves.
    """
    if action == "connect":
        connect()
    elif action == "disconnect":
        disconnect()
    elif action == "toggle_ui":
        page.locator(TOGGLE).click()
    elif action.startswith("mode_"):
        set_mode(action.removeprefix("mode_"))
    else:
        raise ValueError(f"Unrecognized action: {action!r}")


def wait_for_connection_settle(page: Page, timeout_ms: int = 20_000):
    """Polls until the status text reaches a terminal Connected/Disconnected state.

    The "pending" CSS class alone isn't a reliable settle signal - under load the
    status text can pass through other transitional values (e.g. "Disconnecting")
    without that class being present, so poll the text instead. Returns the final
    (class_list, status_text) once settled.
    """
    status = page.locator(STATUS_TEXT)
    onoff = page.locator(ONOFF).first
    waited = 0
    last_text = ""
    last_cls: list[str] = []

    # Give Angular a beat to re-render after a click before the first read - otherwise
    # a stale pre-click snapshot can be misread as the new terminal state.
    page.wait_for_timeout(150)
    waited += 150

    while waited < timeout_ms:
        # Read class and text back to back so a caller can't observe a moment where
        # they disagree (this account can auto-reconnect quickly, and the two don't
        # appear to update in the same Angular render tick).
        last_cls = (onoff.get_attribute("class") or "").split()
        last_text = status.inner_text().strip()
        if last_text in ("Connected", "Disconnected") and "pending" not in last_cls:
            return last_cls, last_text
        page.wait_for_timeout(300)
        waited += 300
    raise AssertionError(
        f"UI never reached a stable terminal state, last class={last_cls} text={last_text!r}"
    )
