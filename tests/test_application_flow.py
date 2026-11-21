"""Tests for application flow."""

import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from jobbot import tracker
from jobbot.answers import Resolver
from jobbot.profile import Profile
from jobbot.apply.engine import detect_ats, start_url
from jobbot.apply.runner import excluded

from core_fixtures import PROFILE, set_up_workspace


def setUpModule():
    set_up_workspace()


class StartUrlTest(unittest.TestCase):
    def test_workday_site_named_apply(self):
        url = "https://ebay.wd5.myworkdayjobs.com/apply/job/Bengaluru-India/Capacity-Planning-Engineer_R0074934"
        self.assertEqual(start_url(url, "workday"), url)
        self.assertEqual(start_url("https://c.wd5.myworkdayjobs.com/Careers/job/Pune/SWE_1/apply/applyManually", "workday"),
                         "https://c.wd5.myworkdayjobs.com/Careers/job/Pune/SWE_1")

    def test_sources_map_to_apply_flows(self):
        self.assertEqual(detect_ats("https://www.amazon.jobs/en/jobs/1/x", {"ats": "amazon"}), "generic")
        careers = {"ats": "careers-page", "board": "https://www.digitalocean.com/careers",
                   "url": "https://www.digitalocean.com/careers/position/apply/?gh_jid=8047031"}
        self.assertEqual(detect_ats(careers["url"], careers), "greenhouse")
        self.assertNotIn("digitalocean.com/careers&", start_url(careers["url"], "greenhouse", careers))


class ExcludeTest(unittest.TestCase):
    def test_excluded_companies(self):
        self.assertTrue(excluded("Inito Inc.", ["inito"]))
        self.assertTrue(excluded("Amazon", ["Amazon", "Google"]))
        self.assertTrue(excluded("Salesforce India", ["Salesforce"]))
        self.assertFalse(excluded("Google", ["Goldman Sachs"]))
        self.assertFalse(excluded("Stripe", []))


class AutonomyTest(unittest.TestCase):
    def test_code_from_email_text(self):
        from jobbot.gmail import extract_code
        self.assertEqual(extract_code("Your verification code is 482913"), "482913")
        self.assertEqual(extract_code("482913 is your Amazon verification code"), "482913")
        self.assertEqual(extract_code("Workday: Use code AB3D9KQ2 to verify"), "AB3D9KQ2")
        self.assertIsNone(extract_code("Welcome to the 2026 hiring season"))
        self.assertIsNone(extract_code("Your code: please click the link below"))

    def test_draft_unknown_is_not_an_answer(self):
        from jobbot.llm import LLM
        m = LLM(enabled=False)
        for reply, want in (("UNKNOWN", ""), ("The provided facts do not mention Debezium.", ""),
                            ("No, but I have built CDC pipelines with Kafka Connect.", "No, but I have built CDC pipelines with Kafka Connect.")):
            m.chat = lambda *a, reply=reply, **k: reply
            self.assertEqual(m.draft("Have you used Debezium?", {}, {}, ""), want)

    def test_tools_from_resume_and_signature(self):
        prof = Profile({**PROFILE, "automation": {"auto_sign": True}}, "x")
        prof.resume_text = lambda key: "Built services in Java and Spring Boot; Redis caching; GraphQL."
        prof.resumes = lambda: {"backend": {}}
        r = Resolver(prof, ask=lambda *a: None)
        yn = ["Yes", "No"]
        self.assertIsNone(r.resolve("Have you worked with Debezium, PeerDB? ✱", "choice", options=yn))
        self.assertEqual(r.resolve("Do you have experience with Java and Spring Boot?", "choice", options=yn).display, "Yes")
        self.assertIsNone(r.resolve("Are you familiar with our code of conduct?", "choice", options=yn))
        self.assertEqual(r.resolve("Signature", "text").value, "Asha Example")


class ReviewFixesTest(unittest.TestCase):
    def test_employer_needs_same_company_not_substring(self):
        prof = Profile({**PROFILE, "work": {**PROFILE["work"], "past_employers": ["Salesforce", "Razorpay"]}}, "x")
        yn = ["Yes", "No"]
        r = Resolver(prof, job={"company": "Sales Hub"}, ask=lambda *a: None)
        self.assertEqual(r.resolve("Have you worked at Sales Hub before?", "choice", options=yn).display, "No")
        r = Resolver(prof, job={"company": "Salesforce India"}, ask=lambda *a: None)
        self.assertEqual(r.resolve("Have you previously worked for Salesforce?", "choice", options=yn).display, "Yes")

    def test_tech_years_whole_words(self):
        prof = Profile(PROFILE, "x")
        prof.resume_text = lambda key: "Built a Google Cloud pipeline; good test coverage; Java."
        prof.resumes = lambda: {"backend": {}}
        r = Resolver(prof, ask=lambda *a: None)
        self.assertIsNone(r.resolve("Years of experience with Go", "text"))
        self.assertEqual(r.resolve("Years of experience with Java", "text").value, "2")

    def test_hear_never_defaults_to_first_option(self):
        r = Resolver(Profile({**PROFILE, "preferences": {"how_did_you_hear": "Company website"}}, "x"))
        self.assertEqual(r.resolve("How did you hear about us?", "choice",
                                   options=["Employee Referral", "Agency", "Other"]).display, "Other")
        self.assertIsNone(r.resolve("How did you hear about us?", "choice", options=["Employee Referral", "Agency"]))
        self.assertEqual(r.resolve("How did you hear about us?", "choice", options=["Employee Referral", "Event"]).display,
                         "Event")

    def test_exclude_is_exact(self):
        self.assertFalse(excluded("Metabase", ["Meta"]))
        self.assertTrue(excluded("Meta Platforms Inc", ["Meta"]))
        self.assertFalse(excluded("Uberall", ["Uber"]))

    def test_import_unknown_status(self):
        with tempfile.TemporaryDirectory() as d:
            conn = tracker.connect(os.path.join(d, "t.db"))
            path = os.path.join(d, "in.csv")
            with open(path, "w") as fh:
                fh.write("company,title,status\nAcme,SDE II,Applied - phone screen\nBeta,SDE,interviewing\n")
            self.assertEqual(tracker.import_csv(conn, path), 2)
            got = {a["company"]: a["status"] for a in tracker.list_applications(conn)}
            self.assertEqual(got, {"Acme": "applied", "Beta": "interview"})   # "interviewing" -> interview


class DropdownTest(unittest.TestCase):
    def test_open_dropdown_falls_back(self):
        from jobbot.apply.engine import Session
        calls = []

        class Loc:
            def click(self, timeout=None, force=False):
                calls.append("force" if force else "click")
                if not force:
                    raise TimeoutError("covered by an overlay")

            def focus(self):
                calls.append("focus")

            def press(self, key):
                calls.append(key)
        Session._open_dropdown(Loc())
        self.assertEqual(calls, ["click", "force"])

    def test_memory_skips_employer_named_questions(self):
        from jobbot.memory import Memory
        with tempfile.TemporaryDirectory() as d:
            m = Memory(Path(d) / "p.yaml")
            self.assertFalse(m.remember("Why do you want to join Go Digit?", "x", company="Go Digit"))
            self.assertTrue(m.remember("Do you have a good internet connection?", "Yes", company="Go Digit"))


class UnattendedTest(unittest.TestCase):
    def test_unattended_ui_never_blocks(self):
        from jobbot.apply.engine import NeedsYou, UnattendedUI

        class Inner:
            def info(self, m):
                self.last = m
        ui = UnattendedUI(Inner())
        self.assertIsNone(ui.ask("Security clearance?", ["Yes", "No"], True, None, "x"))
        self.assertIsNone(ui.ask("Optional note", [], False, None, "x"))
        self.assertEqual(ui.unanswered, ["Security clearance?"])
        self.assertFalse(ui.confirm("Tick consent boxes?"))
        self.assertEqual(ui.next_action(True, False, False, True, final_page=True), "hold")
        self.assertEqual(ui.next_action(True, False, False, False, final_page=True, page=object()), "quit")
        with self.assertRaises(NeedsYou):
            ui.wait_for_user("Sign in, then press Enter")
        ui.info("passes through")
        self.assertEqual(ui.inner.last, "passes through")

    def test_hosted_home_address_uses_configured_street_address(self):
        profile = Profile({"personal": {"address_line1": "12 Example Street"}}, "profile.yaml")
        resolver = Resolver(profile, profile_first=True)
        self.assertEqual(resolver.resolve("Home Address*", required=True).value, "12 Example Street")


class WrongDetailTest(unittest.TestCase):
    def setUp(self):
        self.r = Resolver(Profile({**PROFILE, "eligibility": {**PROFILE["eligibility"], "willing_to_relocate": True}}, "x"),
                          job={"company": "Acme"})

    def test_relocation_is_not_location(self):
        self.assertEqual(self.r.resolve("Are you open to relocation?", "choice", ["Yes", "No"]).display, "Yes")
        self.assertEqual(self.r.resolve("Are you open to relocation?", "text").value, "Yes")

    def test_mobile_development_is_not_phone(self):
        self.assertIsNone(self.r._builtin("Do you have mobile development experience?"))
        self.assertEqual(self.r.resolve("Mobile Number*").value, "9876543210")

    def test_other_people_never_get_your_details(self):
        for q in ("Referrer's name", "Emergency contact phone number", "Manager's email", "Reference name"):
            self.assertIsNone(self.r._builtin(q), q)

    def test_upgrade_is_not_grade(self):
        self.assertIsNone(self.r._builtin("Would you like to upgrade your account?"))


class UnavailablePostingTest(unittest.TestCase):
    def test_explicit_missing_and_closed_messages(self):
        from jobbot.apply.sites import unavailable_reason
        from unittest.mock import Mock
        for text in ("The page you are looking for doesn't exist.",
                     "This job is no longer available", "This position has been closed",
                     "Thank you for your interest. This role is no longer available.",
                     "We're sorry, but it looks like this job may be no longer available or does not exist."):
            self.assertIsNotNone(unavailable_reason(Mock(inner_text=Mock(return_value=text))))
        self.assertIsNone(unavailable_reason(Mock(inner_text=Mock(return_value="Software Engineer. Apply now"))))

    def test_bare_decline_only_on_a_privacy_banner(self):
        # JPMorgan's Oracle site: "IMPORTANT NOTICE ... Privacy Notice [ACCEPT] [DECLINE]" covers Next.
        from jobbot.apply.engine import Session
        from unittest.mock import Mock
        def page(text):
            pg = Mock(inner_text=Mock(return_value=text))
            specific, bare = Mock(), Mock()
            specific.count.return_value = 0
            bare.count.return_value = 1
            bare.first.is_visible.return_value = True
            pg.get_by_role.side_effect = [specific, bare]
            return pg, bare
        pg, bare = page("IMPORTANT NOTICE: PLEASE READ CAREFULLY. Privacy Notice ACCEPT DECLINE Manage Preferences")
        self.assertTrue(Session._decline_cookies(pg))
        bare.first.click.assert_called_once()
        pg, bare = page("Would you relocate? Accept Decline")   # a form question, not a banner
        self.assertFalse(Session._decline_cookies(pg))
        bare.first.click.assert_not_called()

    def test_site_maintenance_is_not_a_closed_posting(self):
        # Workday's outage page: the role must be retried later, never dismissed as gone.
        from jobbot.apply.sites import maintenance, unavailable_reason
        from unittest.mock import Mock
        text = ("English Workday is currently unavailable. We are experiencing a service interruption. "
                "Your service will be restored as quickly as possible. Otherwise, please check back later.")
        page = Mock(url="https://static.community.workday.com/maintenance-page.html", inner_text=Mock(return_value=text))
        self.assertTrue(maintenance(page))
        self.assertIsNone(unavailable_reason(page))
        page = Mock(url="https://acme.wd5.myworkdayjobs.com/job/1", inner_text=Mock(return_value="Software Engineer II. Apply"))
        self.assertFalse(maintenance(page))

    def test_waits_for_late_workday_message(self):
        # Workday shows a blank body, then a spinner, then "doesn't exist" about 5 seconds after load.
        from jobbot.apply.sites import unavailable_reason, wait_rendered
        from unittest.mock import Mock
        page = Mock()
        page.inner_text.side_effect = ["", "", "Loading", "Skip to main content Sign In Search for Jobs "
                                       "The page you are looking for doesn't exist.", "x"]
        page.locator.return_value.count.side_effect = [0, 0, 1, 0]
        wait_rendered(page)
        self.assertEqual(page.wait_for_timeout.call_count, 3)
        page.inner_text.side_effect = None
        page.inner_text.return_value = "The page you are looking for doesn't exist."
        self.assertIsNotNone(unavailable_reason(page))

    def test_unattended_gives_up_after_three_attempts(self):
        # A Submit the site keeps rejecting must not hold up the batch.
        from jobbot.apply.engine import MAX_ATTEMPTS, NeedsYou, Session
        from jobbot.apply.verify import Check
        from unittest.mock import Mock
        page = Mock(url="https://boards.example.com/job/1")
        page.inner_text.return_value = "Software Engineer application form"
        session = Session.__new__(Session)
        session.profile, session.ui, session.unattended, session.dry_run = Profile(PROFILE, "x"), Mock(), True, False
        session.auto_submit, session.auto_next, session.llm, session.upload = True, True, None, False
        session.memory, session._started = None, 0
        session.profile.resumes = lambda: {"backend": {"path": "resume.pdf"}}
        page.locator.return_value.count.return_value = 0
        session.ctx = Mock(pages=[page])
        session.ctx.new_page.return_value = page
        session._enter_form = Mock(return_value=page)
        session._upload_resume = Mock()
        session._fields = Mock(return_value=[{"label": "Email"}])
        bad = Check(); bad.errors.append("Email is required")
        session.review_page = Mock(return_value=({"filled": [], "skipped": [], "records": []}, Check(), 1))
        session._buttons = Mock(side_effect=lambda pg, rx: [{"id": "b"}] if "submit" in rx else [])
        session._click = Mock()
        session._confirmation = Mock(return_value=None)
        session._decline_cookies = Mock()
        import jobbot.apply.engine as engine
        real = engine.check_page
        engine.check_page = Mock(return_value=bad)
        try:
            with self.assertRaisesRegex(NeedsYou, f"after {MAX_ATTEMPTS} attempts"):
                session._apply({"url": "https://boards.example.com/job/1", "company": "Acme", "title": "SDE"}, "backend")
        finally:
            engine.check_page = real
        self.assertEqual(session._click.call_count, MAX_ATTEMPTS)

    def test_missing_posting_never_reaches_upload_or_review(self):
        from jobbot.apply.engine import Session
        from unittest.mock import Mock
        page = Mock()
        page.inner_text.return_value = "The page you are looking for doesn't exist."
        session = Session.__new__(Session)
        session.profile = Mock()
        session.profile.resumes.return_value = {"backend": {"path": "resume.pdf"}}
        session.ui = Mock()
        session.unattended = False
        session.ctx = Mock(pages=[page])
        session._enter_form = Mock()
        session._upload_resume = Mock()
        result = session._apply({"url": "https://example.com/job/1", "company": "Test", "title": "Engineer"}, "backend")
        self.assertIsNone(result[0])
        self.assertIn("posting unavailable", result[1])
        session._enter_form.assert_not_called()
        session._upload_resume.assert_not_called()


class HotReloadTest(unittest.TestCase):
    def test_fixed_apply_code_is_picked_up_between_applications(self):
        import os
        import time
        from jobbot.apply import engine, hot, values
        from jobbot.ui import bridge
        session = engine.Session.__new__(engine.Session)
        hot.changed()   # record what is loaded now
        st = os.stat(values.__file__)
        try:
            os.utime(values.__file__, (st.st_atime, time.time() + 5))   # as if values.py was just edited
            old_class = engine.Session
            self.assertTrue(hot.refresh(session))
            new_engine = __import__("jobbot.apply.engine", fromlist=["Session"])
            self.assertIs(session.__class__, new_engine.Session)
            self.assertIsNot(new_engine.Session, old_class)
            self.assertFalse(hot.refresh(session))   # nothing new since
            other = old_class.__new__(old_class)     # another worker's session, still on the old code
            self.assertTrue(hot.refresh(other))
            self.assertIs(other.__class__, new_engine.Session)
            with unittest.mock.patch.object(bridge, "LOADED_AT", time.time() + 1):
                self.assertFalse(bridge.code_changed())   # form-filling code never blocks a new run
        finally:
            os.utime(values.__file__, (st.st_atime, st.st_mtime))


class RetryTest(unittest.TestCase):
    def test_only_temporary_failures_are_retried(self):
        from jobbot.ui.bridge import retry_worthy
        self.assertTrue(retry_worthy({"status": "needs you", "note": "Workday is down for maintenance; retry this role later."}))
        self.assertTrue(retry_worthy({"status": "needs you", "note": "Gave up after 3 attempts on page 2: Next did not move"}))
        self.assertTrue(retry_worthy({"status": "not submitted", "note": "error: TargetClosedError"}))
        self.assertFalse(retry_worthy({"status": "needs you", "note": "This site needs you to sign in (or create an account)"}))
        self.assertFalse(retry_worthy({"status": "needs you", "note": "unanswered: CAPTCHA (requires your action)"}))
        self.assertFalse(retry_worthy({"status": "applied", "note": "Thank you for applying"}))


class StrictReadbackTest(unittest.TestCase):
    def test_empty_and_partial_choices_fail(self):
        from jobbot.apply.verify import matches
        self.assertFalse(matches("India", "", "combo"))
        self.assertFalse(matches("India", "Ind", "select"))
        self.assertFalse(matches("Male", "Female", "select"))
        self.assertFalse(matches("Male", "Gender Female", "combo"))
        self.assertFalse(matches("India", "Indiana", "combo"))
        self.assertFalse(matches("a" * 50 + "correct suffix", "a" * 50 + "wrong suffix", "textarea"))

    def test_rerendered_field_still_verified(self):
        from jobbot.apply.verify import check_page, READBACK_JS
        from unittest.mock import Mock
        page = Mock()
        def evaluate(script, records=None):
            if script == READBACK_JS:
                return [{"id": records[0]["id"], "found": records[0]["id"] == "new", "value": "wrong"}]
            return {"errors": [], "captcha": False, "invalid": 0}
        page.evaluate.side_effect = evaluate
        check = check_page(page, [{"id": "old", "label": "Name", "expected": "Asha", "kind": "text"}], [],
                           [{"id": "new", "label": "Name", "kind": "text", "value": "wrong"}])
        self.assertFalse(check.ok)
        self.assertEqual(check.mismatches[0][0], "Name")
