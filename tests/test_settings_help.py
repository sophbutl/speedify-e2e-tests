"""Settings > HELP group - verification-only, no interaction.

About Speedify, Getting Started Guide, and Search for Help are visible-only checks
here; none are clicked into.

Generate Logs and Developer Tools: visible, but intentionally never clicked. DOM
inspection found nothing distinguishing about either row (no href, no data attributes
hinting at behavior) - with no way to confirm what they do without clicking, they're
left unexercised per the safety rules for this task.

Clear Settings and Quit App: visible, but intentionally NEVER clicked under any
circumstances - both are destructive (Clear Settings would wipe real configuration,
Quit App would kill the daemon this whole test suite depends on).
"""

from playwright.sync_api import Page, expect

from helpers.ui_helpers import goto_dashboard, open_settings

HELP_ROWS = [
    "About Speedify",
    "Getting Started Guide",
    "Search for Help",
    "Generate Logs",
    "Developer Tools",
    "Clear Settings",
    "Quit App",
]


# Verify every HELP group row is visible in Settings
def test_all_help_rows_are_visible(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    for label in HELP_ROWS:
        expect(page.get_by_text(label, exact=True).last).to_be_visible()
        print(f"[settings] visible: {label}")


# Verify Generate Logs and Developer Tools are visible but never clicked (see module docstring)
def test_generate_logs_and_developer_tools_are_not_exercised(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    for label in ["Generate Logs", "Developer Tools"]:
        expect(page.get_by_text(label, exact=True).last).to_be_visible()
    # No .click() here, deliberately - see module docstring.


# Verify Clear Settings and Quit App are visible but never clicked (see module docstring)
def test_clear_settings_and_quit_app_are_never_clicked(page: Page):
    goto_dashboard(page, wait_for='button[aria-label="Settings Button"]')
    open_settings(page)
    for label in ["Clear Settings", "Quit App"]:
        expect(page.get_by_text(label, exact=True).last).to_be_visible()
    # No .click() here, ever - see module docstring.
