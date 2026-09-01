# Speedify UI E2E Tests

End-to-end tests for the [Speedify](https://speedify.com) macOS VPN app's UI, driven with
[Playwright](https://playwright.dev/python/) and pytest. `conftest.py` serves the app's
own UI bundle over local HTTP and drives it in a real browser, using the Speedify CLI
(`speedify_cli`) to control and verify the underlying VPN daemon state. Most tests run
against Chromium; `tests/test_mac_platform.py` additionally runs core scenarios in WebKit,
since the real app renders its UI inside WKWebView.

## Prerequisites

- macOS with [Speedify](https://speedify.com) installed and the app running (the daemon
  and CLI must be reachable, and the UI bundle must exist under
  `/Applications/Speedify.app/Contents/Resources/`).
- Python 3.9+.

## Setup

```bash
pip install -r requirements.txt
playwright install          # installs all browser engines (chromium, webkit, ...)
```

## Running the tests

```bash
pytest -v                       # verbose test names and pass/fail
pytest -v -s                    # also show print() output (stress/diagnostic logs)
pytest --browser webkit         # run the default suite against WebKit instead of Chromium
pytest -v -k "toggle"           # run only tests whose name matches a keyword
```

Tests run headed (not headless) since they interact with the real local VPN daemon.

## Project structure

- `conftest.py` — serves the Speedify UI bundle on `localhost:8080`, configures the
  shared browser/page fixtures, and restores connection state after every test.
- `helpers/speedify_cli.py` — thin wrapper around the `speedify_cli` binary
  (connect/disconnect, state, adapters, settings, etc.).
- `helpers/ui_helpers.py` — shared Playwright helpers (loading the dashboard,
  connect/disconnect-and-wait, opening/closing Settings, nav-tab state, shared selectors).
- `tests/test_basics.py` — core dashboard elements load and display.
- `tests/test_navigation.py` — Settings panel and nav-tab navigation.
- `tests/test_graph.py` — the traffic graph canvas.
- `tests/test_data_display.py` — adapter cards, speed values, statistics, account info.
- `tests/test_state_consistency.py` — connect/disconnect and bonding-mode state agrees
  between the UI and the CLI.
- `tests/test_connect_disconnect_edge_cases.py` — repeated/edge-case connect-disconnect
  scenarios (already connected, rapid toggling, timer resets).
- `tests/test_viewport.py` — behavior across different window/viewport sizes.
- `tests/test_stress.py` — rapid-click and scroll stress tests.
- `tests/test_mac_specific.py` — macOS-specific behavior: theme/color scheme, keyboard
  shortcuts, Retina scaling, trackpad scrolling, window sizes, multi-tab sync, page lifecycle.
- `tests/test_mac_platform.py` — WebKit rendering, reduced motion, adapter changes, page
  recovery, WebKit-specific stress, forced color schemes, and accessibility contrast checks.
- `tests/test_properties.py` — [Hypothesis](https://hypothesis.readthedocs.io/) property-based
  tests: a layout invariant checked across randomly generated viewport sizes, and a stateful
  test that interleaves random connect/disconnect, tab-switch, and Settings actions.
