"""End-to-end: the real apply engine fills and verifies local copies of real-site form patterns.

Runs headless Chrome (Playwright). Skipped when Playwright or a browser is not available.
"""

import os
import tempfile

# Never touch your real ~/.jobbot from tests (tracker, logs, answer log, browser profile).
os.environ["JOBBOT_HOME"] = tempfile.mkdtemp(prefix="jobbot-test-")
import functools
import http.server
import importlib.util
import os
import tempfile
import threading
import unittest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "forms"
HAVE_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None

PROFILE = {
    "personal": {"first_name": "Asha", "last_name": "Example", "email": "asha@example.com", "phone": "9876543210",
                 "phone_country": "India", "phone_country_code": "+91", "city": "Hyderabad", "country": "India",
                 "location_autocomplete": "Hyderabad, Telangana, India"},
    "work": {"current_company": "Example Corp", "total_experience_years": 2, "past_employers": ["Example Corp"]},
    "eligibility": {"authorized_countries": ["India"], "needs_sponsorship": False},
    "eeo": {"gender": "Male", "race": "Asian"},
    "preferences": {"how_did_you_hear": "Company website"},
    "automation": {"auto_consent": True, "read_codes_from_email": True},
}


class RecordingUI:
    """Answers nothing by itself; records what jobbot asked and how the final step looked."""

    def __init__(self, answers=None):
        self.asked, self.final, self.answers = [], None, answers or {}

    def info(self, m): pass
    def warn(self, m): pass
    def report(self, *a, **k): pass
    def wait_for_user(self, m): raise AssertionError(f"waited for the user: {m}")
    def confirm(self, m): return False
    def ask_code(self, p): self.asked.append("code"); return None

    def ask(self, question, options, required, suggestion, reason):
        self.asked.append(question)
        return next((v for k, v in self.answers.items() if k in question), None)

    def next_action(self, can_submit, can_next, dry_run, check_ok=True, final_page=False):
        self.final = {"final_page": final_page, "check_ok": check_ok}
        return "quit"


@unittest.skipUnless(HAVE_PLAYWRIGHT, "Playwright not installed")
class FormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FIXTURES))
        handler.log_message = lambda *a: None
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["JOBBOT_HEADLESS"] = "1"
        from jobbot import paths
        home = Path(cls.tmp.name) / "home"
        paths.HOME, paths.BROWSER_PROFILE, paths.CACHE = home, home / "browser-profile", home / "cache"
        cls.resume = Path(cls.tmp.name) / "resume.pdf"
        cls.resume.write_bytes(b"%PDF-1.4\n%fake\n")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.tmp.cleanup()

    def session(self, ui, profile_extra=None, unattended=False):
        from jobbot.apply.engine import Session
        from jobbot.llm import LLM
        from jobbot.profile import Profile
        data = {**PROFILE, "resumes": {"backend": {"path": str(self.resume)}}, **(profile_extra or {})}
        prof = Profile(data, Path(self.tmp.name) / "profile.yaml")
        prof.resume_text = lambda key: "Backend services in Java and Spring Boot; Redis; GraphQL."
        try:
            s = Session(prof, LLM(enabled=False), ui, dry_run=False, upload=True, unattended=unattended)
            s.__enter__()
        except Exception as e:   # no browser available here
            self.skipTest(f"browser not available: {e}")
        self.addCleanup(s.__exit__, None, None, None)
        return s

    @staticmethod
    def job(url, ats=None):
        return {"url": url, "company": "TestCo", "title": "Backend Engineer II", "location": "Hyderabad", "ats": ats,
                "board": None, "description": "", "experience": "2+ yrs"}

    def test_nested_ashby_yesno_and_css_required(self):
        ui = RecordingUI()
        session = self.session(ui, {"automation": {"auto_consent": False}})
        session.auto_submit = True
        self.approving_model(session)
        page = session.ctx.pages[0]
        page.goto(self.base + "/ashby-nested.html")
        fields = session._fields(page)
        yesno = [f for f in fields if f["kind"] == "yesno"]
        self.assertEqual(len(yesno), 2)
        self.assertTrue(all(f["required"] for f in yesno))
        from jobbot.apply.verify import check_page
        self.assertFalse(check_page(page, [], [], fields).ok)
        session.apply(self.job(self.base + "/ashby-nested.html"), "backend")
        self.assertEqual(page.get_by_role("button", name="Yes", exact=True).nth(0).get_attribute("aria-pressed"), "true")
        self.assertEqual(page.get_by_role("button", name="No", exact=True).nth(1).get_attribute("aria-pressed"), "true")
        self.assertFalse(ui.final["check_ok"])  # consent was declined; the page must not pass

    def test_authorized_submit_requires_verified_final_page(self):
        ui = RecordingUI({"Why do you want": "I like building backend systems."})
        session = self.session(ui)
        session.auto_submit = True
        self.approving_model(session)
        status, note = session.apply(self.job(self.base + "/greenhouse.html"), "backend")
        self.assertEqual(status, "applied")
        self.assertIn("Thank you for applying", note)
        self.assertIsNone(ui.final)  # authorized submission did not ask for a second approval

    @staticmethod
    def approving_model(session):
        from unittest.mock import Mock
        session.llm = Mock(enabled=True)
        session.llm.answer.side_effect = RuntimeError("Use deterministic fixture answers")
        session.llm.review_application_step.side_effect = lambda fields, *a: {
            "approved": True, "reviewed_field_ids": [f["id"] for f in fields], "issues": []}

    def test_auto_submit_without_model_never_submits_or_prompts(self):
        ui = RecordingUI()
        session = self.session(ui, {"answers": [{"match": "why do you want", "answer": "I like backend work."}]}, unattended=True)
        session.auto_submit = True
        from jobbot.apply.engine import NeedsYou
        with self.assertRaises(NeedsYou):
            session.apply(self.job(self.base + "/greenhouse.html"), "backend")
        self.assertEqual(ui.asked, [])
        self.assertIsNone(ui.final)

    def test_greenhouse_style_form(self):
        ui = RecordingUI({"Why do you want": "I like building backend systems."})
        s = self.session(ui)
        s.apply(self.job(f"{self.base}/greenhouse.html"), "backend")
        page = s.ctx.pages[0]
        val = lambda sel: page.eval_on_selector(sel, "el => el.value")
        shown = lambda rid: page.eval_on_selector(f"#{rid} .sv", "el => el.textContent")
        self.assertEqual((val("#fn"), val("#ln"), val("#em")), ("Asha", "Example", "asha@example.com"))
        self.assertIn("9876543210", val("#ph"))
        self.assertEqual(shown("country"), "India")                          # react-select
        self.assertEqual(shown("hear"), "Company Website")                   # covered by an overlay; never "Employee Referral"
        self.assertEqual(shown("loc"), "Hyderabad, Telangana, India")        # type-ahead suggestion picked
        self.assertEqual(page.eval_on_selector("#dbz", "el => el.value"), "No")   # label wraps the select; resume says no
        self.assertEqual(page.eval_on_selector("#race", "el => el.value"), "Asian (Not Hispanic or Latino)")
        self.assertEqual(page.eval_on_selector("#gender", "el => el.value"), "Male")
        self.assertTrue(page.eval_on_selector("#terms", "el => el.checked"))  # hidden behind its label
        self.assertEqual(val("#hp"), "")                                      # honeypot untouched
        self.assertEqual(val("#extra"), "")                                   # optional catch-all left blank
        self.assertEqual(val("#why"), "I like building backend systems.")
        self.assertEqual(ui.asked, ["Why do you want to join TestCo?"])      # the only thing nothing answers
        self.assertEqual(ui.final, {"final_page": True, "check_ok": True})

    def test_unattended_submit(self):
        ui = RecordingUI()
        s = self.session(ui, {"answers": [{"match": "why do you want to join", "answer": "I like backend work."}]},
                         unattended=True)
        url = f"{self.base}/greenhouse.html"
        status, _ = s.apply(self.job(url), "backend")
        self.assertEqual(status, "ready")
        status, note = s.submit_ready(url)
        self.assertEqual(status, "applied")
        self.assertIn("Thank you", note)

    def test_workday_style_multistep(self):
        ui = RecordingUI()
        s = self.session(ui)
        s.apply(self.job(f"{self.base}/workday.html", ats="workday"), "backend")
        page = s.ctx.pages[0]
        self.assertIn("current step 3 of 3", page.inner_text("body"))       # moved through both steps by itself
        txt = lambda rid: page.eval_on_selector(f"#{rid}", "el => el.textContent")
        self.assertEqual(txt("pc"), "India (+91)")
        self.assertEqual(txt("hh"), "Company Website")                       # nested list: Website > Company Website
        self.assertEqual((txt("au"), txt("sp")), ("Yes", "No"))
        self.assertEqual(ui.asked, [])
        self.assertEqual(ui.final, {"final_page": True, "check_ok": True})

    def test_sign_in_first_then_sign_up(self):
        # No account for this email: sign-in is tried once, then the account is created with the Keychain
        # password, only the terms box is ticked (never marketing), and the application continues.
        from unittest.mock import patch
        from jobbot.apply import auth
        ui = RecordingUI()
        s = self.session(ui, {"automation": {"create_accounts": True}}, unattended=True)
        page = s.ctx.pages[0]
        page.goto(self.base + "/signup.html")
        with patch.object(auth, "host_allowed", return_value=True), \
             patch.object(auth.credentials, "get", return_value="Str0ng!Pass"):
            self.assertTrue(auth.ensure_signed_in(s, page))
        self.assertTrue(page.evaluate("window.signInTried"))
        created = page.evaluate("window.created")
        self.assertEqual((created["email"], created["password"], created["marketing"]),
                         (PROFILE["personal"]["email"], "Str0ng!Pass", False))
        self.assertIn("Apply for", page.inner_text("body"))

    def test_code_from_email(self):
        from jobbot import gmail
        orig = (gmail.is_connected, gmail.latest_code)
        gmail.is_connected, gmail.latest_code = (lambda: True), (lambda *a, **k: "482913")
        self.addCleanup(lambda: (setattr(gmail, "is_connected", orig[0]), setattr(gmail, "latest_code", orig[1])))
        ui = RecordingUI()
        s = self.session(ui)
        s.apply(self.job(f"{self.base}/code.html"), "backend")
        boxes = s.ctx.pages[0].eval_on_selector_all("input", "els => els.map(e => e.value).join('')")
        self.assertEqual(boxes, "482913")
        self.assertNotIn("code", ui.asked)


if __name__ == "__main__":
    unittest.main()
