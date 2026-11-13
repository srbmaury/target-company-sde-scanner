"""Dashboard interactions in Chromium with fixture API responses."""
import unittest
from pathlib import Path

from playwright.sync_api import Error, expect, sync_playwright


STATIC = Path(__file__).resolve().parents[1] / "jobbot" / "ui" / "static"
JOB = {"n": 1, "company": "Example Co.", "title": "Backend Engineer",
       "url": "https://example.com/job", "fit_score": 90}


class DashboardUITests(unittest.TestCase):
    def setUp(self):
        playwright = self.enterContext(sync_playwright())
        try:
            self.browser = playwright.chromium.launch()
        except Error as exc:
            if "Executable doesn't exist" in str(exc):
                self.skipTest("Playwright Chromium is not installed")
            raise
        self.addCleanup(self.browser.close)
        self.page = self.browser.new_page(viewport={"width": 1100, "height": 800})
        self.errors = []
        self.page.on("pageerror", self.errors.append)
        self.hosted, self.dry_run, self.active = True, False, False
        self.answers = []
        self.page.route("http://jobbot.test/**", self.respond)

    def respond(self, route):
        path = route.request.url.split("jobbot.test", 1)[1].split("?", 1)[0]
        if not path.startswith("/api/"):
            route.fulfill(path=str(STATIC / (path.lstrip("/") or "index.html")))
            return
        if path == "/api/apply/answer":
            self.answers.append(route.request.post_data_json)
            self.active = False
        summary = {"account": self.hosted, "applications": {}, "open_jobs": 1,
                   "total": 0, "response_rate": 0, "statuses": ["applied"], "gmail": True}
        prompt = {"kind": "action", "id": "example", "final": True, "check_ok": True,
                  "dry_run": self.dry_run, "choices": ["submit", "quit"]}
        run = {"status": "waiting", "current": 0, "jobs": [JOB], "events": [], "results": {},
               "prompt": prompt, "dry_run": self.dry_run,
               "audits": [{"job": JOB, "step": 1, "fields": [{"label": "Work location", "actual": "Bengaluru",
                                                            "answer_source": "Profile"}]}]}
        fixtures = {
            "/api/summary": summary, "/api/jobs": [JOB], "/api/tasks": [],
            "/api/apply": run if self.active else {"status": "idle"}, "/api/apply/answer": {},
            "/api/runs": [], "/api/applications": [], "/api/logs": {"dates": [], "lines": []},
            "/api/profile": {"path": "Account profile", "text": "personal: {}", "mtime": "1",
                             **({"resume_keys": ["backend"]} if self.hosted else {})},
            "/api/account/resumes": {"keys": ["backend"], "resumes": [{"key": "backend", "name": "Backend"}]},
            "/api/docs": [{"name": "README", "title": "Docs index"}],
            "/api/docs/README": {"text": "# Getting started"},
        }
        if path not in fixtures:
            route.fulfill(status=404, json={"error": "Unexpected route"})
            return
        route.fulfill(json=fixtures[path])

    def open(self):
        self.page.goto("http://jobbot.test/")
        expect(self.page.locator("#workspace-mode")).to_have_text(
            "Hosted account" if self.hosted else "Local workspace")

    def test_hosted_pages_and_keyboard_navigation(self):
        self.open()
        self.page.locator("[data-select]").check()
        expect(self.page.locator("#apply-selected")).to_be_disabled()
        expect(self.page.locator("#dry-selected")).to_be_disabled()
        expect(self.page.locator("#hosted-apply-note")).to_be_visible()
        self.page.locator("#nav-jobs").press("ArrowDown")
        expect(self.page.locator("#nav-apply")).to_be_focused()
        expect(self.page.get_by_text("Browser runs are local")).to_be_visible()
        for tab, title in (("applications", "Application history"), ("actions", "Workspace actions"),
                           ("logs", "Activity logs"), ("profile", "Resume library"), ("docs", "Jobbot guide")):
            self.page.locator("#nav-" + tab).click()
            expect(self.page.get_by_role("heading", name=title, exact=True)).to_be_visible()
        self.page.set_viewport_size({"width": 320, "height": 700})
        self.page.locator("#nav-docs").press("ArrowRight")
        expect(self.page.locator("#nav-jobs")).to_be_focused()
        self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        self.assertEqual(self.errors, [])

    def test_local_submission_waits_for_confirmation(self):
        self.hosted, self.active = False, True
        self.open()
        self.page.locator("[data-select]").check()
        expect(self.page.locator("#apply-selected")).to_be_enabled()
        self.page.locator("#nav-apply").click()
        self.page.get_by_text("Review filled fields", exact=False).click()
        expect(self.page.get_by_text("Bengaluru")).to_be_visible()
        self.page.get_by_role("button", name="Review and submit").click()
        self.assertEqual(self.answers, [])
        self.page.get_by_role("button", name="Back to review").click()
        expect(self.page.get_by_role("button", name="Confirm submission")).to_be_hidden()
        self.page.get_by_role("button", name="Review and submit").click()
        self.page.get_by_role("button", name="Confirm submission").click()
        expect(self.page.locator("#run-title")).to_have_text("No runs yet")
        self.assertEqual(self.answers, [{"prompt_id": "example", "value": "submit"}])
        self.assertEqual(self.errors, [])

    def test_dry_run_never_shows_submit(self):
        self.hosted, self.active, self.dry_run = False, True, True
        self.open()
        self.page.locator("#nav-apply").click()
        expect(self.page.get_by_text("Dry run: submitting is disabled.")).to_be_visible()
        expect(self.page.locator("[data-submit-review], [data-answer=submit]")).to_have_count(0)
        self.assertEqual(self.errors, [])
