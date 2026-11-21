"""Tests for application review."""

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from jobbot import tracker
from jobbot.profile import Profile

from core_fixtures import PROFILE, set_up_workspace


def setUpModule():
    set_up_workspace()


class ApplicationReviewRegressionTests(unittest.TestCase):
    def test_ollama_review_requires_complete_coverage(self):
        from jobbot.apply.engine import Session
        from jobbot.apply.verify import Check
        from unittest.mock import Mock
        session = Session.__new__(Session)
        session.profile, session.llm, session.ui = Mock(), Mock(enabled=True), Mock()
        session.audit_fields = Mock(return_value=[{"id": "salary", "label": "Salary expectations", "actual": "30 LPA"}])
        resolver = Mock(resume_key=None, job={})
        page = Mock()
        page.inner_text.return_value = "Salary expectations"
        session.llm.review_application_step.return_value = {"approved": True, "reviewed_field_ids": [], "issues": []}
        check = Check()
        session._ollama_review(page, resolver, {}, check, 1)
        self.assertFalse(check.ok)
        session.llm.review_application_step.return_value["reviewed_field_ids"] = ["salary"]
        check = Check()
        session._ollama_review(page, resolver, {}, check, 1)
        self.assertTrue(check.ok)
        session.llm.review_application_step.side_effect = TimeoutError()
        check = Check()
        session._ollama_review(page, resolver, {}, check, 1)
        self.assertFalse(check.ok)

    def test_ollama_review_batches_and_retries_skipped_fields(self):
        # 21 fields: reviewed 8 at a time; the model skips one id per batch, then covers it on the retry.
        from jobbot.apply.engine import REVIEW_BATCH, Session
        from jobbot.apply.verify import Check
        from unittest.mock import Mock
        session = Session.__new__(Session)
        session.profile, session.llm, session.ui = Mock(), Mock(enabled=True), Mock()
        session.audit_fields = Mock(return_value=[{"id": f"f{i}", "label": f"Q{i}", "actual": "x"} for i in range(21)])
        calls = []

        def review(fields, *a):
            calls.append(len(fields))
            ids = [f["id"] for f in fields]
            return {"approved": True, "reviewed_field_ids": ids[:-1] if len(ids) > 1 else ids, "issues": []}
        session.llm.review_application_step.side_effect = review
        check = Check()
        session._ollama_review(Mock(inner_text=Mock(return_value="")), Mock(resume_key=None, job={}), {}, check, 1)
        self.assertTrue(check.ok)
        self.assertTrue(all(n <= REVIEW_BATCH for n in calls))
        self.assertEqual(sorted(calls), [1, 1, 1, 5, 8, 8])   # batches run in parallel, then one retry each

    def test_ollama_review_rejection_blocks_even_without_expected_values(self):
        # Seen from qwen2.5:7b on Socure: "already filled", "expected not provided", ids from elsewhere.
        from jobbot.apply.engine import Session
        from jobbot.apply.verify import Check
        from unittest.mock import Mock
        session = Session.__new__(Session)
        session.profile, session.llm, session.ui = Mock(), Mock(enabled=True), Mock()
        session.audit_fields = Mock(return_value=[{"id": "g", "label": "Gender", "actual": "Male"},
                                                  {"id": "auth", "label": "Authorized to work?", "actual": "Yes"},
                                                  {"id": "cv", "label": "Software Engineer -II", "kind": "file", "actual": ""},
                                                  {"id": "sms", "label": "SMS text messages", "kind": "radio", "actual": ""}])
        noise = [{"field_id": "g", "reason": "Gender is required and already filled", "expected": ""},
                 {"field_id": "cv", "reason": "The resume is not uploaded", "expected": "resume.pdf"},
                 {"field_id": "sms", "reason": "Consent field is required and empty", "expected": "No"},
                 {"field_id": "auth", "reason": "Expected value is not provided.", "expected": "yes"},
                 {"field_id": "elsewhere", "reason": "Expected 'No'", "expected": "No"}]
        session.llm.review_application_step.return_value = {"approved": False, "reviewed_field_ids": ["g", "auth", "cv", "sms"], "issues": noise}
        resolver = Mock(resume_key=None, job={})
        resolver._profile_fact.return_value = None
        check = Check()
        session._ollama_review(Mock(inner_text=Mock(return_value="")), resolver, {}, check, 1)
        self.assertFalse(check.ok)
        self.assertIn("LLM did not approve this step.", check.errors)
        session.llm.review_application_step.return_value["issues"] = [{"field_id": "auth", "reason": "wrong", "expected": "No"}]
        check = Check()
        session._ollama_review(Mock(inner_text=Mock(return_value="")), resolver, {}, check, 1)
        self.assertFalse(check.ok)

    def test_ollama_review_covers_verified_and_optional_fields(self):
        from jobbot.apply.engine import Session
        from jobbot.apply.verify import Check
        from unittest.mock import Mock
        session = Session.__new__(Session)
        session.profile, session.llm, session.ui = Mock(), Mock(enabled=True), Mock()
        session.audit_fields = Mock(return_value=[
            {"id": "email", "label": "Email", "actual": "a@example.com", "status": "verified"},
            {"id": "notes", "label": "Notes", "actual": "", "status": "optional, empty"}])
        session.llm.review_application_step.return_value = {"approved": True, "reviewed_field_ids": [], "issues": []}
        check = Check()
        session._ollama_review(Mock(inner_text=Mock(return_value="")), Mock(resume_key=None, job={}), {}, check, 1)
        self.assertFalse(check.ok)

    def test_ollama_reviews_empty_final_page(self):
        from jobbot.apply.engine import Session
        from jobbot.apply.verify import Check
        from unittest.mock import Mock
        session = Session.__new__(Session)
        session.profile, session.llm, session.ui = Mock(), Mock(enabled=True), Mock()
        session.audit_fields = Mock(return_value=[])
        session._buttons = lambda page, pattern: [{"id": "b"}] if "submit" in pattern else []   # Submit, no Next
        session.llm.review_application_step.return_value = {"approved": False, "reviewed_field_ids": [], "issues": []}
        check = Check()
        session._ollama_review(Mock(inner_text=Mock(return_value="Review and Submit")), Mock(resume_key=None, job={}), {}, check, 1)
        session.llm.review_application_step.assert_called_once()
        self.assertFalse(check.ok)

    def test_empty_middle_page_is_not_sent_for_review(self):
        from jobbot.apply.engine import Session
        from jobbot.apply.verify import Check
        from unittest.mock import Mock
        session = Session.__new__(Session)
        session.profile, session.llm, session.ui = Mock(), Mock(enabled=True), Mock()
        session.audit_fields = Mock(return_value=[])
        session._buttons = lambda page, pattern: [{"id": "b"}] if "continue" in pattern else []   # Continue only
        check = Check()
        # the page text mentions "submit", but only buttons decide what the final page is
        session._ollama_review(Mock(inner_text=Mock(return_value="Autofill with Resume. Before you submit, upload a CV.")),
                               Mock(resume_key=None, job={}), {}, check, 1)
        self.assertTrue(check.ok)
        session.llm.review_application_step.assert_not_called()

    def test_deadline_applies_within_a_page(self):
        import time
        from jobbot.apply.engine import MAX_APPLY_SECONDS, Session
        from jobbot.apply.unattended import NeedsYou
        session = Session.__new__(Session)
        session.unattended, session._started = True, time.time() - MAX_APPLY_SECONDS - 1
        with self.assertRaises(NeedsYou):
            session._check_deadline()
        session._started = time.time()
        session._check_deadline()   # within the limit: nothing happens

    def test_unconfirmed_submit_is_recorded_only_after_a_form(self):
        from unittest.mock import Mock
        from jobbot.apply.runner import run_jobs
        from jobbot.apply.unattended import NeedsYou
        conn = tracker.connect(Path(tempfile.mkdtemp()) / "t.db")
        prof = Mock(); prof.resumes.return_value = {"r": {}}; prof.get.return_value = 0
        job = {"company": "Acme", "title": "Engineer", "url": "https://acme.example/jobs/1"}
        for raised, want in (("Submit clicked but confirmation was not detected; check the site.", "submission_unverified"),
                             ("A Submit-like button was clicked on a page with no application fields; nothing was submitted.",
                              "needs you")):
            session = Mock(); session.apply.side_effect = NeedsYou(raised)
            with unittest.mock.patch("jobbot.resumes.parse_all"), unittest.mock.patch("jobbot.apply.hot.refresh"):
                (_, status, _, _), = run_jobs(session, conn, prof, [dict(job, url=job["url"] + want[0])], Mock())
            self.assertEqual(status, want)

    def test_button_finder_reaches_nested_components(self):
        from jobbot.apply.fields import BUTTONS_JS
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("playwright not installed")
        html = """<div id=a></div><script>
          const outer = document.getElementById('a').attachShadow({mode: 'open'});
          outer.innerHTML = '<div id=b></div>';
          const inner = outer.getElementById('b').attachShadow({mode: 'open'});
          inner.innerHTML = '<button>Next</button>';</script>"""
        try:
            with sync_playwright() as p:
                b = p.chromium.launch(headless=True)
                page = b.new_page(); page.set_content(html)
                hits = page.evaluate(BUTTONS_JS, ["^next$", False])
                b.close()
        except Exception as e:
            self.skipTest(f"no browser: {type(e).__name__}")
        self.assertEqual([h["text"] for h in hits], ["Next"])

    def test_model_slot_wait_is_bounded(self):
        from unittest.mock import patch
        from jobbot import llm
        model = llm.LLM.__new__(llm.LLM)
        model.enabled, model.model, model.provider = True, "qwen2.5:7b", "ollama"
        with patch.object(llm, "MODEL_SLOTS") as slots, patch.object(llm, "SLOT_WAIT", 0):
            slots.acquire.return_value = False   # every slot busy
            with self.assertRaises(TimeoutError):
                model.chat("system", "user")

    def test_every_model_call_uses_one_context_size(self):
        import io
        import json
        from unittest.mock import patch
        from jobbot import llm
        model = llm.LLM.__new__(llm.LLM)
        model.enabled, model.model, model.provider = True, "qwen2.5:7b", "ollama"
        sent = []
        def capture(req, timeout=None):
            sent.append(json.loads(req.data)["options"]["num_ctx"])
            return io.BytesIO(json.dumps({"message": {"content": "{}"}}).encode())
        with patch("jobbot.llm.urllib.request.urlopen", side_effect=capture):
            model.chat("s", "u")
            model.review_application_step([], "", "", "", {})
        self.assertEqual(sent, [llm.CONTEXT_TOKENS, llm.CONTEXT_TOKENS])   # no reload between calls

    def test_batch_30_reported_values(self):
        # From the 30-role batch: Keka's phone box pre-filled with "+91" cut the number off; a number-only
        # CTC box needs a unit; a currency box got a place name.
        from jobbot.answers import Resolver
        from jobbot.apply.values import format_value
        p = Profile({**PROFILE, "personal": {**PROFILE["personal"], "phone": "9876543210", "phone_country_code": "+91"},
                     "work": {**PROFILE.get("work", {}), "expected_ctc_lpa": 30}, "automation": {"numeric_salary_unit": "INR"}}, "x")
        self.assertEqual(format_value(p, {"value": "+91", "maxlength": 13}, "Mobile Phone *", "x"), "9876543210")
        self.assertEqual(format_value(p, {"type": "number"}, "Expected CTC *", "x"), "3000000")
        r = Resolver(p, None, job={"company": "Teachmint"})
        self.assertEqual(r.resolve("Currency", "choice", options=["USD", "INR - Indian Rupee"], quick=True).display,
                         "INR - Indian Rupee")

    def test_profile_check_catches_wrong_values_and_passes_right_ones(self):
        # Real mistakes from 2026-10-10 runs and the false blocks a first version made.
        from jobbot.answers import Resolver
        from jobbot.apply import consistency
        prof = Profile({**PROFILE, "personal": {**PROFILE["personal"], "phone_country": "India", "phone_country_code": "+91",
                                                "city": "Hyderabad", "email": "asha@example.com"},
                        "eligibility": {"authorized_countries": ["India"], "needs_sponsorship": False}}, "x")
        r = Resolver(prof, None, job={"company": "Point72", "location": "Bengaluru, India"})
        f = lambda label, actual, kind="text", options=(): {"id": label, "label": label, "kind": kind,  # noqa: E731
                                                         "actual": actual, "options": list(options), "required": True}
        bad, ok = consistency.check(r, [
            f("Phone country*", "British Indian Ocean Territory +246", "combo"),
            f("Are you legally authorized to work in the United States?*", "Yes", "radio", ["Yes", "No"]),
            f("Email*", "asha@exmaple.com"),
        ])
        self.assertEqual({x["id"] for x, _ in bad}, {"Phone country*", "Are you legally authorized to work in the United States?*", "Email*"})
        bad, ok = consistency.check(r, [
            f("Country*", "+91", "combo"),                       # the picker shows only the dialling code
            f("Are you legally authorized to work in the United States?*", "No", "radio", ["Yes", "No"]),
            f("Email*", "asha@example.com"),
            f("How did you hear about this job?*", "Career Website", "combo"),   # the site's own list
        ])
        self.assertEqual(bad, [])
        self.assertIn("Email*", ok)
        self.assertFalse(consistency.same_value("https://www.linkedin.com/in/asha", "https://linkedin.com/in/someone-else"))
        self.assertFalse(consistency.same_value("Hyderabad, Telangana, India", "Mumbai, Maharashtra, India"))
        self.assertTrue(consistency.same_value("Hyderabad, Bengaluru, Noida, Remote", "Bengaluru, India"))
        r2 = Resolver(Profile({**PROFILE, "education": {"school_name": "Indian Institute of Technology (BHU), Varanasi",
                                                         "school": ["IIT (BHU)", "BHU University"]}}, "x"), None, job={"company": "X"})
        bad, ok = consistency.check(r2, [f("School", "BHU University")])   # the site's own name for your school
        self.assertEqual(bad, [])
        bad, ok = consistency.check(r2, [f("School", "Indian Institute of Technology Bombay (IITB)")])
        self.assertEqual(len(bad), 1)
        self.assertEqual(consistency.check(r2, [f("School", "Other")])[0], [])   # your college is not in the site's list
        consent = f("I confirm, that I have read the Privacy Notice*", "I confirm")
        self.assertIn(consent["id"], consistency.check(r2, [consent])[1])
        self.assertNotIn("n", consistency.check(r2, [{**consent, "id": "n", "actual": "I do not agree"}])[1])
        self.assertEqual(len(consistency.check(r2, [f("Facebook", "Telangana")])[0]), 1)   # a stray value in a profile you don't list
        self.assertIsNone(r2.resolve("X (fka Twitter)", "text", quick=True))
        from jobbot.apply.dropdowns import matching_option
        self.assertEqual(matching_option(["Hyderabad, Sindh, Pakistan", "Hyderabad, India"], "Hyderabad", "Hyderabad, Telangana, India"), 1)
        self.assertIsNone(matching_option(["Hyderabad, Sindh, Pakistan"], "Hyderabad", "Hyderabad, Telangana, India"))
        upload = {"id": "cv", "label": "Resume/CV", "kind": "file", "actual": "Asha_Resume.pdf", "options": [], "required": True}
        autofill = {"id": "af", "label": "Software Engineer -II", "kind": "file", "actual": "", "options": [], "required": False}
        self.assertEqual(consistency.check(r2, [upload, autofill]), ([], {"cv", "af"}))
        group = [dict(f(x, "checked" if x == "Company Website" else ""), kind="checkbox") for x in ("LinkedIn", "Company Website", "Recruiter Outreach")]
        self.assertEqual(consistency.check(r2, group), ([], {"LinkedIn", "Company Website", "Recruiter Outreach"}))
        bad, ok = consistency.check(r2, [f("Security code", "e"), f("A verification code was sent to you. Enter the 8-character code", "m")])
        self.assertEqual((bad, ok), ([], {"Security code", "A verification code was sent to you. Enter the 8-character code"}))
