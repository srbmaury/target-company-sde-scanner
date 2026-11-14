"""Dashboard interactions in Chromium with fixture API responses."""
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from browser_support import launch_for_test


STATIC = Path(__file__).resolve().parents[1] / "jobbot" / "ui" / "static"
JOB = {"n": 1, "company": "Example Co.", "title": "Backend Engineer",
       "url": "https://example.com/job", "fit_score": 90}


class DashboardUITests(unittest.TestCase):
    def setUp(self):
        playwright = self.enterContext(sync_playwright())
        self.browser = launch_for_test(self, playwright.chromium.launch)
        self.addCleanup(self.browser.close)
        self.page = self.browser.new_page(viewport={"width": 1100, "height": 800})
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(error))
        self.hosted, self.dry_run, self.active = True, False, False
        self.answers = []
        self.browser_actions = []
        self.tasks = []
        self.page.route("http://jobbot.test/**", self.respond)

    def respond(self, route):
        path = route.request.url.split("jobbot.test", 1)[1].split("?", 1)[0]
        if not path.startswith("/api/"):
            route.fulfill(path=str(STATIC / (path.lstrip("/") or "index.html")))
            return
        if path == "/api/apply" and route.request.method == "POST":
            self.dry_run = route.request.post_data_json["dry_run"]
            self.active = True
        if path == "/api/apply/preview":
            command = route.request.post_data_json
            self.browser_actions.append(command["action"])
            if command["action"] == "release":
                self.active = False
                route.fulfill(json={})
            else:
                route.fulfill(json={"control": "controller", "frame_id": "frame", "width": 1000, "height": 600,
                                    "image": "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"})
            return
        if path == "/api/apply/answer":
            self.answers.append(route.request.post_data_json)
            self.active = False
        summary = {"account": self.hosted, "applications": {}, "open_jobs": 1,
                   "total": 0, "response_rate": 0, "statuses": ["applied"], "gmail": True}
        prompt = {"kind": "action", "id": "example", "final": True, "check_ok": True,
                  "dry_run": self.dry_run, "choices": ["submit", "quit"], "interactive": self.hosted}
        run = {"status": "waiting", "current": 0, "jobs": [JOB], "events": [], "results": {},
               "prompt": prompt, "dry_run": self.dry_run,
               "audits": [{"job": JOB, "step": 1, "fields": [{"id": "location", "kind": "text", "label": "Work location", "actual": "Bengaluru",
                                                            "answer_source": "Profile"}]}]}
        fixtures = {
            "/api/summary": summary, "/api/workspace": summary, "/api/jobs": [JOB], "/api/tasks": self.tasks,
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

    def test_runs_remain_visible_when_history_fails(self):
        self.active = True
        self.page.add_init_script("localStorage.setItem('jobbot.tab', 'apply')")
        self.page.route("**/api/runs", lambda route: route.fulfill(status=503, json={"error": "Unavailable"}), times=1)
        self.open()
        panel = self.page.locator("#tab-apply")
        expect(panel.get_by_text("Needs review", exact=True)).to_be_visible()
        expect(panel.get_by_role("button", name="Take control")).to_be_visible()
        panel.get_by_role("button", name="Retry history").click()
        expect(panel.get_by_text("No saved runs yet.")).to_be_visible()
        self.assertEqual(self.errors, [])

    def test_runs_retry_when_initial_data_request_fails(self):
        self.page.add_init_script("localStorage.setItem('jobbot.tab', 'apply')")
        self.page.route("**/api/apply", lambda route: route.fulfill(status=503, json={"error": "Try again"}), times=1)
        self.open()
        panel = self.page.locator("#tab-apply")
        expect(panel.get_by_text("Could not load application runs.", exact=False)).to_be_visible()
        expect(panel.get_by_text("No runs yet", exact=True)).to_have_count(0)
        panel.get_by_role("button", name="Retry", exact=True).click()
        expect(panel.get_by_text("No runs yet", exact=True)).to_be_visible()
        expect(self.page.locator("#local-run-options")).to_be_hidden()
        self.assertEqual(self.errors, [])

    def test_hosted_pages_and_keyboard_navigation(self):
        self.open()
        self.page.locator("[data-select]").check()
        expect(self.page.get_by_role("button", name="Fill for review")).to_be_enabled()
        expect(self.page.locator("#dry-selected")).to_be_enabled()
        expect(self.page.locator("#hosted-apply-note")).to_be_visible()
        self.page.locator("#nav-jobs").press("ArrowDown")
        expect(self.page.locator("#nav-apply")).to_be_focused()
        expect(self.page.get_by_text("No hosted run yet")).to_be_visible()
        for tab, title in (("applications", "Application history"), ("actions", "Actions"),
                           ("logs", "Activity logs"), ("profile", "Resume library"), ("docs", "Jobbot guide")):
            self.page.locator("#nav-" + tab).click()
            expect(self.page.get_by_role("heading", name=title, exact=True)).to_be_visible()
        self.page.set_viewport_size({"width": 320, "height": 700})
        self.page.locator("#nav-docs").press("ArrowRight")
        expect(self.page.locator("#nav-jobs")).to_be_focused()
        self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        self.assertEqual(self.errors, [])

    def test_activity_scroll_keeps_navigation_fixed_and_details_open(self):
        self.tasks = [
            {"id": str(i), "name": "scan", "status": "done", "started": "2026-11-14T09:04:48+00:00",
             "ended": "2026-11-14T09:05:48+00:00", "lines": ["Scan output"],
             "activity": {"scan": {"summary": "1 matching role · 1 new", "total": 1, "jobs": [
                 {"title": "Backend Engineer", "company": "Example Co", "location": "India",
                  "experience": "2+ yrs stated", "new": True}]}}}
            for i in range(12)
        ]
        self.open()
        self.page.locator("#nav-actions").click()
        first = self.page.locator(".task").first
        expect(first.get_by_text("1 matching role · 1 new")).to_be_visible()
        first.get_by_text("Scan results").click()
        expect(first.get_by_text("Backend Engineer")).to_be_visible()
        self.tasks[0]["lines"].append("Updated scan output")
        self.page.evaluate("loadTasks()")
        expect(first.get_by_text("Backend Engineer")).to_be_visible()
        before = self.page.locator(".tabs").bounding_box()
        self.page.locator("main").evaluate("(main) => main.scrollTop = main.scrollHeight")
        self.assertGreater(self.page.locator("main").evaluate("(main) => main.scrollTop"), 0)
        self.assertEqual(before, self.page.locator(".tabs").bounding_box())
        expect(self.page.get_by_role("heading", name="Actions", exact=True)).to_be_in_viewport()
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

    def test_correction_editor_sends_only_the_selected_field(self):
        self.active = True
        self.open()
        self.page.locator("#nav-apply").click()
        self.page.get_by_text("Edit a field", exact=True).click()
        expect(self.page.locator("#correction-field")).to_be_visible()
        expect(self.page.locator("#correction-value")).to_have_value("Bengaluru")
        self.page.locator("#correction-value").fill("Hyderabad")
        self.page.get_by_role("button", name="Save and re-check").click()
        expect(self.page.locator("#run-title")).to_have_text("No runs yet")
        self.assertEqual(self.answers, [{"prompt_id": "example", "value": {
            "action": "correct", "field": "location", "value": "Hyderabad"}}])
        self.assertEqual(self.errors, [])

    def test_dry_run_never_shows_submit(self):
        self.open()
        self.page.locator("[data-select]").check()
        self.page.get_by_role("button", name="Dry run", exact=True).click()
        self.page.get_by_role("button", name="Start dry run").click()
        expect(self.page.get_by_text("Dry run: submitting is disabled.")).to_be_visible()
        expect(self.page.locator("[data-submit-review], [data-answer=submit]")).to_have_count(0)
        self.assertEqual(self.errors, [])

    def test_hosted_takeover_controls_same_preview_until_released(self):
        self.active = True
        self.open()
        self.page.locator("#nav-apply").click()
        self.page.get_by_role("button", name="Take control").click()
        expect(self.page.get_by_text("You have control. Jobbot is paused.")).to_be_visible()
        self.page.locator("#live-image").click(position={"x": 15, "y": 15})
        frame = self.page.locator("#live-image")
        frame.hover()
        self.page.mouse.wheel(0, 300)
        expect(self.page.locator("#live-send")).to_be_enabled()
        expect(self.page.locator("#live-input")).to_have_attribute("type", "text")
        self.page.get_by_label("Hide text").check()
        expect(self.page.locator("#live-input")).to_have_attribute("type", "password")
        self.page.get_by_label("Hide text").uncheck()
        self.page.locator("#live-input").fill("Bengaluru")
        self.page.get_by_role("button", name="Type text").click()
        self.page.get_by_role("button", name="Return control and recheck").click()
        expect(self.page.get_by_text("No hosted run yet")).to_be_visible()
        self.assertEqual([a for a in self.browser_actions if a != "frame"], ["open", "click", "scroll", "text", "release"])
        self.assertEqual(self.answers, [])
        self.assertEqual(self.errors, [])
