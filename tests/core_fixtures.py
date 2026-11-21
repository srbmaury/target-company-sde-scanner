"""Shared candidate profile and temporary workspace for core tests."""

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import addModuleCleanup
from unittest.mock import patch

from jobbot import paths


PROFILE = {
    "personal": {"first_name": "Asha", "last_name": "Example", "email": "a@example.com", "phone": "9876543210",
                 "phone_country": "India", "city": "Bengaluru", "country": "India",
                 "location_autocomplete": "Bengaluru, Karnataka, India"},
    "links": {"linkedin": "https://www.linkedin.com/in/x"},
    "work": {"current_company": "Example Corp", "total_experience_years": 2, "past_employers": ["Example Corp"],
             "notice_period_days": 30},
    "eligibility": {"authorized_countries": ["India"], "needs_sponsorship": False},
    "eeo": {"gender": "Male", "veteran": "Decline"},
    "answers": [{"match": "pwc", "answer": "No"}],
    "always_ask": ["signature"],
}


def set_up_workspace():
    stack = ExitStack()
    addModuleCleanup(stack.close)
    home = Path(stack.enter_context(TemporaryDirectory(prefix="jobbot-test-")))
    stack.enter_context(patch.multiple(
        paths,
        HOME=home,
        DB=home / "applications.db",
        LEGACY_PROFILE=home / "profile.yaml",
        BROWSER_PROFILE=home / "browser-profile",
        CACHE=home / "cache",
    ))
