"""Browser test setup shared by the dashboard and form suites."""

import os

from playwright.sync_api import Error


def launch_for_test(test, launch, *args, **kwargs):
    try:
        return launch(*args, **kwargs)
    except Error as exc:
        if "Executable doesn't exist" not in str(exc) or os.getenv("JOBBOT_REQUIRE_BROWSER_TESTS") == "1":
            raise
        test.skipTest("Playwright Chromium is missing. Run python -m playwright install chromium.")
