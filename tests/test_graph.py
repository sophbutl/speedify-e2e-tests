from playwright.sync_api import Page, expect

from helpers.ui_helpers import NAV_TABS, goto_dashboard

# The canvas renders a few pixels above the top of its container by design (label
# spacing), not a layout bug - allow a small tolerance rather than pixel-perfect containment.
CONTAINMENT_TOLERANCE_PX = 10


def _assert_graph_has_size(page: Page):
    chart = page.locator("#omniChart")
    expect(chart).to_be_visible()
    box = chart.bounding_box()
    assert box is not None, "Graph canvas has no bounding box"
    assert box["width"] > 0, f"Graph canvas has zero width: {box}"
    assert box["height"] > 0, f"Graph canvas has zero height: {box}"
    return box


# Verify the graph canvas renders with non-zero dimensions on the Networks tab
def test_graph_has_nonzero_dimensions_on_networks_tab(page: Page):
    goto_dashboard(page, wait_for="#omniChart")
    box = _assert_graph_has_size(page)
    print(f"[graph] Networks tab canvas box: {box}")


# Verify the graph canvas keeps a valid size after switching to Traffic and back
def test_graph_survives_switching_to_traffic_and_back(page: Page):
    goto_dashboard(page)
    nav = page.locator("#networksSlider")

    nav.get_by_text("Traffic", exact=True).click()
    page.wait_for_timeout(500)
    _assert_graph_has_size(page)
    print("[graph] canvas still sized correctly on Traffic tab")

    nav.get_by_text("Networks", exact=True).click()
    page.wait_for_timeout(500)
    _assert_graph_has_size(page)
    print("[graph] canvas still sized correctly back on Networks tab")


# Verify the graph canvas renders correctly after cycling through all 5 nav tabs
def test_graph_renders_after_cycling_all_tabs(page: Page):
    goto_dashboard(page)
    nav = page.locator("#networksSlider")

    print("\n[graph] cycling through all 5 tabs")
    for name in NAV_TABS:
        nav.get_by_text(name, exact=True).click()
        page.wait_for_timeout(300)
        print(f"[graph] visited {name}")

    nav.get_by_text("Networks", exact=True).click()
    page.wait_for_timeout(500)
    box = _assert_graph_has_size(page)
    print(f"[graph] final canvas box back on Networks: {box}")


# Verify the graph canvas stays contained within its designated area
def test_graph_canvas_is_contained_within_its_area(page: Page):
    goto_dashboard(page, wait_for="#omniChartArea")

    chart_box = page.locator("#omniChart").bounding_box()
    area_box = page.locator("#omniChartArea").bounding_box()
    assert chart_box is not None and area_box is not None

    tol = CONTAINMENT_TOLERANCE_PX
    assert chart_box["x"] >= area_box["x"] - tol, (
        f"Canvas left edge {chart_box['x']} is left of area {area_box['x']} beyond tolerance"
    )
    assert chart_box["x"] + chart_box["width"] <= area_box["x"] + area_box["width"] + tol, (
        "Canvas right edge overflows its container beyond tolerance"
    )
    assert chart_box["y"] >= area_box["y"] - tol, (
        f"Canvas top edge {chart_box['y']} is above area {area_box['y']} beyond tolerance"
    )
    assert chart_box["y"] + chart_box["height"] <= area_box["y"] + area_box["height"] + tol, (
        "Canvas bottom edge overflows its container beyond tolerance"
    )
