import pytest
from playwright.sync_api import Page, expect

from helpers.speedify_cli import connect, disconnect, get_state, wait_for_state

# The page/context fixtures are session-scoped (shared across every test file), so a
# viewport left small/large here would leak into whatever runs next. Always restore it.
DEFAULT_VIEWPORT = {"width": 1280, "height": 720}

NOT_CONNECTED_STATE = "LOGGED_IN"


@pytest.fixture(autouse=True)
def restore_viewport(page: Page):
    yield
    page.set_viewport_size(DEFAULT_VIEWPORT)
    page.wait_for_timeout(300)


def test_very_small_viewport_does_not_crash(page: Page):
    page.goto("/")
    page.wait_for_selector("#networksSlider")

    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.set_viewport_size({"width": 400, "height": 300})
    page.wait_for_timeout(1000)

    # At this size elements may be squeezed off-screen, so check DOM attachment
    # rather than visibility.
    expect(page.locator("#dashboard")).to_be_attached()
    expect(page.locator("#networksSlider")).to_be_attached()
    expect(page.locator("#statusBox").first).to_be_attached()
    assert errors == [], f"Page threw errors at 400x300: {errors}"
    print("[viewport] 400x300 - key elements still in DOM, no page errors")


def test_very_large_viewport_renders_without_broken_layout(page: Page):
    page.goto("/")
    page.wait_for_selector("#networksSlider")

    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.set_viewport_size({"width": 1920, "height": 1080})
    page.wait_for_timeout(1000)

    expect(page.locator("#statusBox").first).to_be_visible()
    expect(page.locator("#networksSlider")).to_be_visible()
    expect(page.locator("#statistics-pane")).to_be_visible()
    expect(page.locator("#omniChart")).to_be_visible()

    body_scroll_width = page.evaluate("document.body.scrollWidth")
    viewport_width = page.evaluate("window.innerWidth")
    assert body_scroll_width <= viewport_width + 20, (
        f"Body scrollWidth ({body_scroll_width}) exceeds viewport width "
        f"({viewport_width}) by more than a small tolerance — layout may be overflowing"
    )
    assert errors == [], f"Page threw errors at 1920x1080: {errors}"
    print("[viewport] 1920x1080 - major sections visible, no horizontal overflow")


def test_resize_while_scrolled_to_bottom_does_not_lose_content(page: Page):
    page.goto("/")
    page.wait_for_selector("#networksSlider")

    box = page.locator("#networksSlider").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.wheel(0, 2000)
    page.wait_for_timeout(500)

    page.set_viewport_size({"width": 800, "height": 500})
    page.wait_for_timeout(1000)

    expect(page.locator("#dashboard")).to_be_attached()
    expect(page.locator("#networksSlider")).to_be_attached()
    expect(page.locator("#statistics-pane")).to_be_attached()
    print("[viewport] resized while scrolled down - content still present")


def test_connect_disconnect_still_works_after_resizing_small_to_large(page: Page):
    was_connected = get_state() == "CONNECTED"
    try:
        page.set_viewport_size({"width": 400, "height": 600})
        page.goto("/")
        page.wait_for_selector("#navbar-onoff")

        toggle = page.locator("#navbar-onoff")
        onoff = page.locator("#onOff").first
        status = page.locator("#status-box-ServerButtonTextStatus")

        toggle.click(timeout=5000)

        # Poll status text rather than just the "pending" class — under load the text
        # can pass through other transitional values without that class being set.
        waited = 0
        while waited < 20_000:
            if status.inner_text().strip() in ("Connected", "Disconnected"):
                break
            page.wait_for_timeout(300)
            waited += 300

        page.set_viewport_size({"width": 1920, "height": 1080})
        page.wait_for_timeout(1000)

        final_cls = (onoff.get_attribute("class") or "").split()
        final_text = status.inner_text().strip()
        print(f"[viewport] after resize small->large: class={final_cls} status={final_text!r}")

        if "off" in final_cls:
            assert final_text == "Disconnected"
        else:
            assert final_text == "Connected"

        expect(page.locator("#networksSlider")).to_be_visible()
    finally:
        if was_connected and get_state() != "CONNECTED":
            connect()
            wait_for_state("CONNECTED", timeout=20)
        elif not was_connected and get_state() == "CONNECTED":
            disconnect()
            wait_for_state(NOT_CONNECTED_STATE, timeout=10)
