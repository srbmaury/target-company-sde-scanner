import os
import tempfile

# Never touch your real ~/.jobbot from tests (tracker, logs, answer log, browser profile).
os.environ["JOBBOT_HOME"] = tempfile.mkdtemp(prefix="jobbot-test-")

import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import yaml

from jobbot import tracker
from jobbot.answers import Resolver, bucket, pick
from jobbot.profile import Profile
from jobbot.rank import keyword_rank
from jobbot.apply.engine import detect_ats, start_url
from jobbot.apply.runner import excluded
from jobbot.careers_page import jobs_in_json
from jobbot.scan import _pick, classify, stated_years

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


class PickTest(unittest.TestCase):
    def test_male_never_matches_female(self):
        self.assertEqual(pick("Male", ["Female", "Male", "Non Binary"]), 1)

    def test_no_matches_long_option(self):
        opts = ["YES, I am currently or have been employed by PwC", "No, I have not been employed by PwC"]
        self.assertEqual(pick("No", opts), 1)

    def test_country_with_dial_code(self):
        self.assertEqual(pick("India", ["British Indian Ocean Territory +246", "India +91"]), 1)

    def test_decline(self):
        self.assertEqual(pick("Decline", ["Yes", "No", "I don't wish to answer"]), 2)

    def test_ambiguous_returns_none(self):
        self.assertIsNone(pick("Engineering", ["Electrical Engineering", "Mechanical Engineering"]))


class ResolverTest(unittest.TestCase):
    def setUp(self):
        self.asked = []
        ask = lambda q, opts, req, sug, why: self.asked.append(q) or None
        self.r = Resolver(Profile(PROFILE, "x"), job={"company": "Acme"}, ask=ask)

    def test_open_to_preferred_location(self):
        r = Resolver(Profile({**PROFILE, "preferences": {"locations": "bengaluru|bangalore|pune"}}, "x"),
                     ask=lambda *a: self.asked.append(a[0]))
        self.assertEqual(r.resolve("Are you open for Bangalore location ?", "choice", options=["Yes", "No"]).display, "Yes")
        self.assertEqual(self.asked, [])

    def test_new_profile_fields(self):
        prof = {**PROFILE, "personal": {**PROFILE["personal"], "languages": ["Hindi"], "phone_device_type": "Mobile"},
                "work": {**PROFILE["work"], "outside_business_activities": "No"},
                "eligibility": {**PROFILE["eligibility"], "military_service": "No"},
                "eeo": {**PROFILE["eeo"], "veteran": "I am not a protected veteran"},
                "preferences": {"preferred_work_locations": ["Bengaluru", "Hyderabad"]}}
        r = Resolver(Profile(prof, "x"), ask=lambda *a: self.asked.append(a[0]))
        yn = ["Yes", "No"]
        self.assertEqual(r.resolve("Have you served in the military?", "choice", options=yn).display, "No")
        self.assertEqual(r.resolve("Do you have any outside business activity(ies) (advisory, consulting, or board "
                                   "roles, or side businesses)?", "choice", options=yn).display, "No")
        self.assertEqual(r.resolve("In which language(s) are you fluent (spoken) other than English?", "text").value,
                         "Hindi")
        self.assertEqual(r.resolve("Phone Device Type", "choice", options=["Home", "Mobile"]).display, "Mobile")
        self.assertEqual(r.resolve("What is your preferred work location?", "choice",
                                   options=["New York", "Hyderabad", "London"]).display, "Hyderabad")
        self.assertEqual(r.resolve("Veteran Status", "choice", options=["I am not a protected veteran", "Decline"]).display,
                         "I am not a protected veteran")
        self.assertEqual(self.asked, [])

    def test_amazon_screening_questions(self):
        ranges = ["Less than 1 year", "1 year to less than 2 years", "2 years to less than 3 years",
                  "3 years to less than 4 years", "4 years to less than 5 years", "5 years or more"]
        prof = {**PROFILE, "work": {**PROFILE["work"], "sdlc_experience_years": 3},
                "education": {"cs_or_equivalent": True}, "eligibility": {**PROFILE["eligibility"], "government_employee": "No"}}
        r = Resolver(Profile(prof, "x"), ask=lambda *a: self.asked.append(a[0]))
        yn = ["Yes", "No"]
        q = "Which option best describes your total non-internship professional software development experience?"
        self.assertEqual(r.resolve(q, "choice", options=ranges).display, "2 years to less than 3 years")
        q = ("Which option best describes your total non-internship design or architecture (design patterns, "
             "reliability and scaling) of new and existing systems experience?")
        self.assertEqual(r.resolve(q, "choice", options=ranges).display, "2 years to less than 3 years")
        q = ("Which option best describes your total full software development life cycle, including coding standards, "
             "code reviews, source control management, build processes, testing, and operations experience?")
        self.assertEqual(r.resolve(q, "choice", options=ranges).display, "3 years to less than 4 years")
        q = "Do you have experience programming with at least one software programming language?"
        self.assertEqual(r.resolve(q, "choice", options=yn).display, "Yes")
        q = "Do you have a Bachelor's degree in computer science or equivalent?"
        self.assertEqual(r.resolve(q, "choice", options=yn).display, "Yes")
        for q in ("Are you currently or have you ever been a government employee?",
                  "Have you ever worked for the government or a state-owned entity?",
                  "Are you a current or former government official?"):
            self.assertEqual(r.resolve(q, "choice", options=yn).display, "No", q)
        self.assertEqual(self.asked, [])
        # about a relative, not you: never answered from your own status
        self.assertIsNone(r.resolve("Does any immediate family member work for the government?", "choice", options=yn))

    def test_bucket(self):
        self.assertEqual(bucket(2, ["0-1 years", "1-3 years", "3-5 years", "5+ years"]), 1)
        self.assertEqual(bucket(0.5, ["None", "Less than 1 year", "1+ years"]), 1)
        self.assertIsNone(bucket(2, ["Yes", "No"]))

    def test_eeo_description_does_not_trigger_always_ask(self):
        prof = {**PROFILE, "eeo": {"race": "Asian"}, "always_ask": [r"sanction|\bcuba\b|iran", "citizenship"]}
        r = Resolver(Profile(prof, "x"), ask=lambda *a: self.asked.append(a[0]))
        q = ("Race - A person of Cuban, Mexican, Puerto Rican, South or Central American, or other Spanish culture "
             "or origin regardless of race. - A person having origins in any of the original peoples of Europe, "
             "the Middle East, or North Africa (Iran).")
        opts = ["Hispanic or Latino", "White (Not Hispanic or Latino)", "Asian (Not Hispanic or Latino)",
                "Decline to self-identify"]
        self.assertEqual(r.resolve(q, "choice", options=opts).display, "Asian (Not Hispanic or Latino)")
        self.assertEqual(self.asked, [])
        r.resolve("Are you a resident of Cuba?", "choice", options=["Yes", "No"])
        self.assertEqual(len(self.asked), 1)   # a real sanctions question is still yours

    def test_credentials_and_fact_only_questions(self):
        prof = Profile(PROFILE, "x")
        prof.resume_text = lambda key: "Backend on AWS (Lambda, S3). Certifications: Oracle Certified Java Programmer."
        prof.resumes = lambda: {"backend": {}}

        class FakeLLM:   # would answer anything; must not be consulted for fact-only questions
            enabled, calls = True, []
            def choose(self, q, *a, **k):
                self.calls.append(q)
                return 1
        llm = FakeLLM()
        r = Resolver(prof, llm=llm, ask=lambda *a: self.asked.append(a[0]))
        yn = ["Yes", "No"]
        self.assertEqual(r.resolve("Do you hold a PMP certification?", "choice", options=yn).display, "No")
        self.assertEqual(r.resolve("Do you have a valid AWS certification?", "choice", options=yn).display, "No")
        self.assertEqual(r.resolve("Do you hold an Oracle Certified Java Programmer certification?", "choice",
                                   options=yn).display, "Yes")
        for q in ("Are you a US citizen?", "Have you ever been convicted of a felony?"):
            self.assertIsNone(r.resolve(q, "choice", options=yn, required=True))
        self.assertEqual(llm.calls, [])
        self.assertEqual(len(self.asked), 2)
        self.assertEqual(r.resolve("Are you open to working weekends occasionally?", "choice", options=yn).display, "No")
        self.assertEqual(len(llm.calls), 1)   # preference questions do reach the model

    def test_asks_once_per_application(self):
        # review rounds re-read the page; an unanswered question must not be asked again
        for _ in range(3):
            self.assertIsNone(self.r.resolve("Have you worked with Debezium, PeerDB?", "text", required=True))
        self.assertEqual(len(self.asked), 1)

    def test_basic_fields(self):
        self.assertEqual(self.r.resolve("First Name*").value, "Asha")
        self.assertEqual(self.r.resolve("Preferred Name").value, "Asha")
        self.assertEqual(self.r.resolve("Share your LinkedIn Profile site").value, "https://www.linkedin.com/in/x")

    def test_choices(self):
        ans = self.r.resolve("Will you now or in the future require employment sponsorship?", "choice", ["Yes", "No"])
        self.assertEqual(ans.display, "No")
        ans = self.r.resolve("Have you ever worked at Acme before?", "choice", ["Yes", "No"])
        self.assertEqual(ans.display, "No")
        ans = self.r.resolve("Gender", "choice", ["Select...", "Female", "Male"])
        self.assertEqual(ans.display, "Male")

    def test_custom_answer_wins(self):
        opts = ["YES, I am currently or have been employed by PwC", "No, I have not been employed by PwC"]
        self.assertEqual(self.r.resolve("Are you employed by PwC?", "choice", opts).value, 1)

    def test_always_ask(self):
        self.assertIsNone(self.r.resolve("Name (Signature Field)", required=True))
        self.assertEqual(self.asked, ["Name (Signature Field)"])

    def test_consent_checkbox_not_auto_ticked(self):
        self.assertIsNone(self.r.resolve("I agree to the privacy policy", "checkbox"))


class ScanParsingTest(unittest.TestCase):
    def test_stated_years(self):
        self.assertEqual(stated_years("Requirements 2 to 5 years of Python engineering expertise")[0], 2)
        self.assertEqual(stated_years("Has 2-5 years of professional software engineering experience")[0], 2)
        self.assertIsNone(stated_years("We were founded 12 years ago.")[0])

    def test_classify(self):
        import re
        loc = re.compile("india|bengaluru", re.I)
        job = {"title": "Software Engineer II", "location": "Bengaluru", "text": "4+ years of experience building"}
        self.assertIsNone(classify(job, loc, 3))
        job["text"] = "2+ years of experience building services"
        self.assertEqual(classify(job, loc, 3)[0], "2+ yrs stated")
        self.assertIsNone(classify({**job, "title": "Senior Software Engineer"}, loc, 3))
        self.assertIsNone(classify({**job, "title": "Backend Engineer - 5+ Years"}, loc, 3))
        self.assertEqual(classify({**job, "title": "Site Reliability Engineer (1 to 4 Years)", "text": ""}, loc, 3)[0],
                         "1+ yrs in title")

    def test_json_feed_fields(self):
        item = {"title": "SDE II", "portalJobPost": {"portalUrl": "https://x.test/1"}, "locations": ["Pune", "Remote"]}
        self.assertEqual(_pick(item, "portalJobPost.portalUrl|applyUrl"), "https://x.test/1")
        self.assertEqual(_pick(item, "missing|locations"), "Pune; Remote")
        self.assertEqual(_pick(item, "missing"), "")

    def test_jobs_in_json(self):
        payload = {"data": {"search": {"all_jobs": [
            {"id": "101", "title": "Software Engineer, Infra", "locations": ["Bangalore, India"]},
            {"id": "102", "title": "Production Engineer", "locations": ["Hyderabad, India"]},
            {"id": "103", "title": "Data Scientist", "location": {"city": "Pune", "country": "India"}}]},
            "filters": [{"name": "Engineering"}, {"name": "Sales"}]}}
        jobs = jobs_in_json(payload)
        self.assertEqual([j["id"] for j in jobs], ["101", "102", "103"])
        self.assertEqual(jobs[0]["location"], "Bangalore, India")
        self.assertIn("Pune", jobs[2]["location"])


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
        self.assertEqual(r.resolve("Have you worked with Debezium, PeerDB? ✱", "choice", options=yn).display, "No")
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
        self.assertEqual(r.resolve("Years of experience with Go", "text").value, "0")
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


class MailImportTest(unittest.TestCase):
    def test_email_matches_existing_and_never_downgrades_offer(self):
        from jobbot import mailimport
        with tempfile.TemporaryDirectory() as d:
            conn = tracker.connect(os.path.join(d, "t.db"))
            tracker.add_application(conn, "Salesforce", "Software Development Engineer 2", status="offer")
            rows = [{"company": "Salesforce India", "title": "SDE II", "status": "interview", "date": "2026-10-01",
                     "applied_on": "2026-09-01", "notes": "Interview reminder"}]
            self.assertEqual(mailimport.import_rows(conn, rows), (0, 0))
            self.assertEqual([a["status"] for a in tracker.list_applications(conn)], ["offer"])


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
        self.assertEqual(ui.next_action(False, False, False, False, final_page=False), "quit")
        with self.assertRaises(NeedsYou):
            ui.wait_for_user("Sign in, then press Enter")
        ui.info("passes through")
        self.assertEqual(ui.inner.last, "passes through")


class AnswerLogAndCapTest(unittest.TestCase):
    def test_model_answers_logged_and_reviewed(self):
        from jobbot import answerlog, paths
        with tempfile.TemporaryDirectory() as d:
            old = paths.HOME
            paths.HOME = Path(d)
            try:
                class FakeLLM:
                    enabled, last_reasoning = True, "A motivated engineer would."
                    def choose(self, *a, **k): return 0
                r = Resolver(Profile(PROFILE, "x"), llm=FakeLLM(), job={"company": "Acme"})
                self.assertEqual(r.resolve("Are you comfortable with on-call rotations?", "choice", ["Yes", "No"]).display, "Yes")
                rows = answerlog.load()
                self.assertEqual((rows[0]["answer"], rows[0]["reasoning"]), ("Yes", "A motivated engineer would."))
                rows[0]["verdict"] = "ok"
                answerlog.save(rows)
                self.assertEqual(answerlog.accuracy(answerlog.load()), (1, 0))
            finally:
                paths.HOME = old

    def test_daily_cap_stops_batch(self):
        from jobbot.apply.runner import run_jobs
        with tempfile.TemporaryDirectory() as d:
            conn = tracker.connect(os.path.join(d, "t.db"))
            tracker.add_application(conn, "Acme", "SDE", source="jobbot")
            prof = Profile({**PROFILE, "automation": {"max_applications_per_day": 1}}, "x")
            prof.resumes = lambda: {"backend": {}}
            warned = []

            class UI:
                def warn(self, m): warned.append(m)
                def info(self, m): pass

            class S:
                def apply(self, *a): raise AssertionError("must not apply past the daily limit")
            run_jobs(S(), conn, prof, [{"url": "u", "company": "B", "title": "t"}], UI())
            self.assertTrue(any("Daily limit" in w for w in warned))


    def test_gone_posting_is_dismissed(self):
        # A posting that says it no longer exists leaves the New list instead of being picked again.
        from jobbot.apply.runner import run_jobs
        with tempfile.TemporaryDirectory() as d:
            conn = tracker.connect(os.path.join(d, "t.db"))
            tracker.upsert_jobs(conn, [{"url": "u1", "company": "Acme", "title": "SDE II", "location": "Remote",
                                        "ats": "workday", "board": "acme", "experience": "", "evidence": ""}])
            prof = Profile(PROFILE, "x")
            prof.resumes = lambda: {"backend": {}}

            class UI:
                def warn(self, m): pass
                def info(self, m): pass

            class S:
                def apply(self, *a): return None, "posting unavailable: This role is no longer available"
            run_jobs(S(), conn, prof, [dict(tracker.get_job(conn, "u1"))], UI(), dry_run=True)
            self.assertEqual(tracker.get_job(conn, "u1")["dismissed"], 1)

    def test_excluded_companies_leave_new_roles(self):
        # Apply skips excluded companies; the page marks them instead of letting you pick them.
        from unittest.mock import patch
        from jobbot.ui import server
        with tempfile.TemporaryDirectory() as d:
            conn = tracker.connect(os.path.join(d, "t.db"))
            tracker.upsert_jobs(conn, [{"url": u, "company": c, "title": "SDE II", "location": "", "experience": "", "evidence": ""}
                                       for u, c in (("u1", "Amazon"), ("u2", "Socure"))])
            with patch.object(server, "_excluded_companies", return_value=["amazon"]):
                flags = {j["company"]: j["excluded"] for j in server.jobs_payload(conn, {})}
                self.assertEqual(flags, {"Amazon": True, "Socure": False})
                self.assertEqual(server._new_jobs(conn), 1)

    def test_roles_missing_from_a_good_scan_are_gone(self):
        # Acme's board was read and no longer lists u1; Beta's board errored, so u3 is kept.
        with tempfile.TemporaryDirectory() as d:
            conn = tracker.connect(os.path.join(d, "t.db"))
            job = lambda u, c: {"url": u, "company": c, "title": "SDE II", "location": "", "experience": "", "evidence": ""}
            tracker.upsert_jobs(conn, [job("u1", "Acme"), job("u2", "Acme"), job("u3", "Beta")])
            self.assertEqual(tracker.mark_gone(conn, ["u2"], ["Acme"]), 1)
            self.assertEqual({r["url"] for r in tracker.list_jobs(conn)}, {"u2", "u3"})
            self.assertEqual(len(tracker.list_jobs(conn, include_gone=True)), 3)
            tracker.upsert_jobs(conn, [job("u1", "Acme")])   # listed again
            self.assertEqual({r["url"] for r in tracker.list_jobs(conn)}, {"u1", "u2", "u3"})

class DocsTabTest(unittest.TestCase):
    def test_docs_pages_only_from_docs_folder(self):
        from jobbot.ui.server import doc_page, docs_index
        names = [p["name"] for p in docs_index()]
        self.assertEqual(names[0], "README")
        self.assertIn("apply", names)
        self.assertIn("Unattended mode", doc_page("apply")["text"])
        for bad in ("../README", "..", "../profile", "apply.md", "a/b", ""):
            self.assertIsNone(doc_page(bad), bad)


class BridgeTest(unittest.TestCase):
    def test_prompt_round_trip_and_history(self):
        import threading
        from jobbot.ui import bridge
        run = bridge.ApplyRun()
        ui = bridge.WebUI(run)
        got = {}
        t = threading.Thread(target=lambda: got.setdefault("v", ui.next_action(True, False, False, True, final_page=True)))
        t.start()
        for _ in range(50):
            if run.prompt:
                break
            threading.Event().wait(0.02)
        run.answer(run.prompt["id"], "submit")
        t.join(2)
        self.assertEqual(got["v"], "submit")
        run.results["u"] = {"status": "needs you", "note": "sign in", "application": None}
        run.save()
        self.assertEqual(bridge.history()[0]["counts"], {"needs you": 1})
        self.assertEqual(bridge.saved_run(run.id)["results"]["u"]["note"], "sign in")


class NotDuplicateTest(unittest.TestCase):
    def test_not_duplicate_clears_possible(self):
        with tempfile.TemporaryDirectory() as d:
            conn = tracker.connect(os.path.join(d, "t.db"))
            tracker.add_application(conn, "Amazon", "Software Development Engineer II", applied_on="2026-09-17")
            tracker.upsert_jobs(conn, [{"url": "u1", "company": "Amazon", "title": "Software Development Engineer II",
                                        "location": "", "experience": "", "evidence": "", "posted": "2026-10-01"}])
            job = tracker.get_job(conn, "u1")
            self.assertEqual(tracker.job_level(conn, job)[0], "possible")   # same title, posted after you applied
            tracker.set_not_duplicate(conn, "u1")
            self.assertEqual(tracker.job_level(conn, tracker.get_job(conn, "u1"))[0], None)
            tracker.set_not_duplicate(conn, "u1", False)
            self.assertEqual(tracker.job_level(conn, tracker.get_job(conn, "u1"))[0], "possible")


class EditApplicationTest(unittest.TestCase):
    def test_naming_the_role_stops_possible_matches(self):
        with tempfile.TemporaryDirectory() as d:
            conn = tracker.connect(os.path.join(d, "t.db"))
            app = tracker.add_application(conn, "Apple", "(role not stated in email)", applied_on="2026-09-17")
            tracker.upsert_jobs(conn, [{"url": "u1", "company": "Apple", "title": "Software Engineer - Distributed Systems",
                                        "location": "", "experience": "", "evidence": ""}])
            self.assertEqual(tracker.job_level(conn, tracker.get_job(conn, "u1"))[0], "possible")
            tracker.edit_application(conn, app["id"], title="Software Engineer - Siri Infrastructure")
            self.assertIsNone(tracker.job_level(conn, tracker.get_job(conn, "u1"))[0])
            self.assertIn("edited title", tracker.events_for(conn, app["id"])[-1]["note"])


class TrackerTest(unittest.TestCase):
    def test_lifecycle(self):
        with tempfile.TemporaryDirectory() as d:
            conn = tracker.connect(os.path.join(d, "t.db"))
            a = tracker.add_application(conn, "Acme", "SWE II", url="https://x/1")
            self.assertEqual(a["status"], "applied")
            tracker.update_status(conn, a["id"], "interview", "phone screen")
            self.assertEqual(tracker.find_application(conn, "https://x/1")["status"], "interview")
            self.assertEqual(len(tracker.events_for(conn, a["id"])), 2)
            self.assertTrue(tracker.is_applied(conn, company="acme", title="swe ii"))
            path = os.path.join(d, "out.csv")
            tracker.export_csv(conn, path)
            conn2 = tracker.connect(os.path.join(d, "t2.db"))
            self.assertEqual(tracker.import_csv(conn2, path), 1)

    def test_jobs_upsert_and_exclusion_of_applied(self):
        with tempfile.TemporaryDirectory() as d:
            conn = tracker.connect(os.path.join(d, "t.db"))
            row = {"url": "https://x/2", "company": "Acme", "title": "SWE", "location": "India",
                   "experience": "2+ yrs stated", "evidence": "", "description": "java spring"}
            self.assertEqual(tracker.upsert_jobs(conn, [row]), ["https://x/2"])
            self.assertEqual(tracker.upsert_jobs(conn, [row]), [])
            self.assertEqual(len(tracker.list_jobs(conn)), 1)
            tracker.add_application(conn, "Acme", "SWE", url="https://x/2")
            self.assertEqual(len(tracker.list_jobs(conn)), 0)


class RankTest(unittest.TestCase):
    def test_keyword_rank_prefers_matching_resume(self):
        job = {"title": "Backend Engineer", "description": "java spring kafka microservices", "experience": "2+ yrs stated"}
        score, key, _ = keyword_rank(job, {"fe": "react css figma", "be": "java spring kafka microservices redis"})
        self.assertEqual(key, "be")
        self.assertGreater(score, 0)


if __name__ == "__main__":
    unittest.main()


class VerifyMatchTest(unittest.TestCase):
    def test_matches(self):
        from jobbot.apply.verify import matches
        self.assertTrue(matches("+91 9876543210", "98765 43210", "text"))       # sites reformat phones
        self.assertTrue(matches("Male", "Gender Male", "combo"))               # react-select shows label + value
        self.assertFalse(matches("Hyderabad", "", "text"))                     # wiped by the page
        self.assertFalse(matches("No", "", "radio"))
        self.assertTrue(matches("No", "checked", "radio"))
        self.assertTrue(matches("India +91", "India +91", "combo"))


class ExpandKeysTest(unittest.TestCase):
    def test_ranges(self):
        from jobbot.cli import expand_job_keys
        self.assertEqual(expand_job_keys(["12-14"]), ["12", "13", "14"])
        self.assertEqual(expand_job_keys(["14..12", "20"]), ["12", "13", "14", "20"])
        self.assertEqual(expand_job_keys(["3,5"]), ["3", "5"])
        self.assertEqual(expand_job_keys(["https://x.test/a,b"]), ["https://x.test/a,b"])


class AppliedMatchTest(unittest.TestCase):
    def test_title_and_company_normalisation(self):
        self.assertTrue(tracker.titles_match("Software Engineer 2", "Software Engineer II"))
        self.assertTrue(tracker.titles_match("SDE II - Backend", "Software Development Engineer 2 Backend"))
        self.assertFalse(tracker.titles_match("Software Engineer II", "Software Engineer"))
        self.assertTrue(tracker.titles_match("Software Engineer II (200047960)", "Software Engineer II"))
        self.assertEqual(tracker.norm_company("Sarvam AI"), tracker.norm_company("Sarvam"))

    def test_levels(self):
        with tempfile.TemporaryDirectory() as d:
            conn = tracker.connect(os.path.join(d, "t.db"))
            tracker.add_application(conn, "Sarvam", "Agent Engineer", applied_on="2026-08-31")
            tracker.add_application(conn, "Cisco", "(role not stated in email)", applied_on="2026-08-28")
            tracker.add_application(conn, "Microsoft", "Software Engineer II", status="rejected",
                                    applied_on="2026-08-01")
            m = tracker.applied_match
            self.assertEqual(m(conn, "u1", "Sarvam AI", "Agent Engineer", posted="2026-08-20")[0], "likely")
            self.assertEqual(m(conn, "u2", "Sarvam AI", "Agent Engineer", posted="2026-09-15")[0], "possible")
            self.assertEqual(m(conn, "u3", "Cisco", "Software Engineer")[0], "possible")
            self.assertEqual(m(conn, "u4", "Microsoft", "Software Engineer II", first_seen="2026-10-05")[0], "possible")
            self.assertIsNone(m(conn, "u5", "Sarvam AI", "Frontend Engineer")[0])


class MemoryTest(unittest.TestCase):
    def test_remember_and_reuse(self):
        from pathlib import Path
        from jobbot.memory import Memory
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "profile.yaml"
            path.write_text("# my profile\npersonal:\n  first_name: Asha  # keep this comment\n")
            m = Memory(path)
            self.assertTrue(m.remember("Are you comfortable working from our Bangalore office 3 days a week?", "Yes"))
            self.assertFalse(m.remember("Why do you want to join Acme?", "x", company="Acme"))
            text = path.read_text()
            self.assertIn("keep this comment", text)
            self.assertIn("learned_answers:", text)
            m.remember("Are you comfortable working from our Bangalore office 3 days a week?", "No")
            self.assertEqual(path.read_text().count("Bangalore office"), 1)   # replaced, not duplicated
            m2 = Memory(path, __import__("yaml").safe_load(path.read_text())["learned_answers"])
            self.assertEqual(m2.lookup("Are you comfortable working from the Bangalore office 3 days a week?"), "No")
            self.assertIsNone(m2.lookup("What is your expected CTC?"))

    def test_resolver_uses_memory_and_hybrid_rule(self):
        from jobbot.memory import Memory
        prof = Profile({**PROFILE, "eligibility": {**PROFILE["eligibility"], "willing_to_relocate": True}}, "x")
        mem = Memory(items=[{"question": "Do you have experience with Kafka in production?", "answer": "Yes"}])
        r = Resolver(prof, job={"company": "Acme"}, memory=mem)
        self.assertEqual(r.resolve("Do you have experience with Kafka in production?", "choice", ["Yes", "No"]).source,
                         "remembered")
        q = "Abnormal AI operates a hybrid working model. This role is based in our Bangalore office. Are you okay with that?"
        self.assertEqual(r.resolve(q, "choice", ["Yes", "No"]).display, "Yes")


class WorkdayQuestionsTest(unittest.TestCase):
    def setUp(self):
        self.r = Resolver(Profile({**PROFILE, "preferences": {"how_did_you_hear": "Company website"}}, "x"),
                          job={"company": "Cisco"}, ask=lambda *a: (_ for _ in ()).throw(AssertionError("asked")))

    def test_how_did_you_hear_never_asks(self):
        self.assertEqual(self.r.resolve("How Did You Hear About Us?*", "choice",
                                        ["Job Board", "Cisco Careers Website", "Referral"]).display, "Cisco Careers Website")
        self.assertEqual(self.r.resolve("How did you hear about us?", "choice", ["Event", "Agency"]).display, "Event")

    def test_employer_history(self):
        q = "Have you ever been issued a Cisco Employee ID or Cisco email address? This includes interns and contractors."
        self.assertEqual(self.r.resolve(q, "choice", ["Yes", "No"]).display, "No")
        r = Resolver(Profile({**PROFILE, "work": {"past_employers": ["Cisco Systems"]}}, "x"), job={"company": "Cisco"})
        self.assertEqual(r.resolve(q, "choice", ["Yes", "No"]).display, "Yes")

    def test_phone_code_answer(self):
        self.assertEqual(self.r.resolve("Country Phone Code*", "choice", ["Indonesia (+62)", "India (+91)"]).display,
                         "India (+91)")


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


class GmailFlowTest(unittest.TestCase):
    """Sign-in and sync with Google's endpoints simulated; no network."""

    def test_login_and_search(self):
        import json
        import threading
        import urllib.parse
        import urllib.request
        from pathlib import Path
        from unittest import mock
        from jobbot import gmail, mailimport, paths

        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            client = home / "client.json"
            client.write_text(json.dumps({"installed": {"client_id": "abc.apps.googleusercontent.com",
                                                        "client_secret": "s"}}))
            posted = []

            def fake_post(url, data):
                posted.append((url, data))
                return {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}

            def fake_open(url):   # play the browser: Google redirects back with a code
                q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                self.assertEqual(q["scope"], [gmail.SCOPE])          # read-only scope only
                self.assertEqual(q["code_challenge_method"], ["S256"])
                back = q["redirect_uri"][0] + "/?" + urllib.parse.urlencode({"code": "c0de", "state": q["state"][0]})
                threading.Thread(target=lambda: urllib.request.urlopen(back).read()).start()
                return True

            api = {"profile": {"emailAddress": "asha@example.com"},
                   "messages": {"messages": [{"id": "m1"}]},
                   "messages/m1": {"snippet": "Thank you for applying for the Backend Engineer role at Acme.",
                                   "internalDate": "1790000000000", "labelIds": ["INBOX"],
                                   "payload": {"headers": [{"name": "From", "value": "no-reply@acme.com"},
                                                           {"name": "Subject", "value": "Thank you for applying to Acme"}]}}}
            with mock.patch.object(paths, "HOME", home), mock.patch.object(gmail, "_post", fake_post), \
                    mock.patch.object(gmail.webbrowser, "open", fake_open), \
                    mock.patch.object(gmail, "_get", lambda path, params=None: api[path]):
                self.assertEqual(gmail.login(str(client)), "asha@example.com")
                token = home / "gmail_token.json"
                self.assertTrue(token.exists())
                self.assertEqual(oct(token.stat().st_mode & 0o777), "0o600")
                self.assertEqual(posted[0][1]["code"], "c0de")
                self.assertIn("code_verifier", posted[0][1])
                msgs = gmail.search(days=30)
                rows = mailimport.rows_from(msgs)
                self.assertEqual((rows[0]["company"], rows[0]["status"]), ("Acme", "applied"))
                self.assertTrue(gmail.logout())
                self.assertFalse(token.exists())


class DashboardApiTest(unittest.TestCase):
    def test_api(self):
        import json
        import threading
        import urllib.request
        from pathlib import Path
        from unittest import mock
        from jobbot import paths
        from jobbot.ui import server as ui

        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            prof = home / "profile.yaml"
            prof.write_text("personal:\n  first_name: Asha\n")
            with mock.patch.object(paths, "HOME", home), mock.patch.object(paths, "DB", home / "a.db"), \
                    mock.patch.object(paths, "PROFILE", prof):
                conn = tracker.connect()
                tracker.upsert_jobs(conn, [{"url": "https://x/1", "company": "Acme", "title": "SWE II", "location": "India",
                                            "experience": "2+ yrs stated", "evidence": "", "description": ""}])
                srv = ui.make_server(0)
                threading.Thread(target=srv.serve_forever, daemon=True).start()
                base, tok = f"http://127.0.0.1:{srv.server_port}", srv.RequestHandlerClass.token

                def call(path, body=None, token=tok):
                    req = urllib.request.Request(base + "/api/" + path, data=None if body is None else json.dumps(body).encode(),
                                                 headers={"X-Jobbot-Token": token, "Content-Type": "application/json"})
                    try:
                        with urllib.request.urlopen(req) as r:
                            return r.status, json.load(r)
                    except urllib.error.HTTPError as e:
                        return e.code, json.load(e)

                self.assertEqual(call("summary", token="wrong")[0], 403)
                self.assertIn(tok, urllib.request.urlopen(base + "/").read().decode())
                self.assertEqual(len(call("jobs")[1]), 1)
                self.assertEqual(call("jobs/1/dismiss", {})[0], 200)
                self.assertEqual(len(call("jobs")[1]), 0)
                code, app = call("applications", {"company": "Acme", "title": "SWE II", "status": "applied"})
                self.assertEqual(code, 200)
                self.assertEqual(call(f"applications/{app['id']}/status", {"status": "interview", "note": "R1"})[1]["status"],
                                 "interview")
                self.assertEqual(len(call(f"applications/{app['id']}")[1]["events"]), 2)
                self.assertEqual(call("profile", {"text": "not: [valid"})[0], 400)
                self.assertEqual(call("profile", {"text": "personal:\n  first_name: Bea\n"})[0], 200)
                self.assertTrue((home / "profile.yaml.bak").exists())
                self.assertEqual(call("tasks/rm-rf", {})[0], 400)
                srv.shutdown()


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


class StaleCodeTest(unittest.TestCase):
    def test_run_refused_after_code_changes(self):
        # A dashboard started before a code update would mix old and new modules mid-run.
        from unittest.mock import patch
        from jobbot.ui import bridge
        with patch.object(bridge, "LOADED_AT", 0):
            with self.assertRaisesRegex(ValueError, "Restart it"):
                bridge.start(["1"])
        self.assertFalse(bridge.code_changed())


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


class ValidationPromptTest(unittest.TestCase):
    def test_confirmed_facts_ignore_model_and_bad_memory(self):
        from unittest.mock import Mock
        data = {**PROFILE, "personal": {**PROFILE["personal"], "pronouns": "he/him/his"},
                "work": {"expected_ctc": "INR 30 LPA fixed, negotiable based on role and bonus/equity"},
                "education": {"start_month": "2020-09", "end_month": "2024-06", "school_name": "IIT (BHU), Varanasi"},
                "eligibility": {"military_service": "No"}, "eeo": {"veteran": "I am not a protected veteran"}}
        model = Mock(enabled=True)
        memory = Mock()
        memory.lookup.return_value = "Bengaluru"
        resolver = Resolver(Profile(data, "x"), llm=model, memory=memory)
        for question, expected in [("Salary and benefit expectations", data["work"]["expected_ctc"]),
                                   ("Pronouns", "he/him/his"), ("College start date", "2020-09"),
                                   ("College graduation date", "2024-06"), ("University/ College", "IIT (BHU), Varanasi"),
                                   ("Phone Number", "9876543210")]:
            self.assertEqual(resolver.resolve(question).value, expected)
        self.assertEqual(resolver.resolve("Are you a veteran?", "choice", options=["Yes", "No"]).display, "No")
        model.answer.assert_not_called()
        memory.lookup.assert_not_called()

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
        self.assertIn("Ollama did not approve this step.", check.errors)
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
        session.llm.review_application_step.return_value = {"approved": False, "reviewed_field_ids": [], "issues": []}
        check = Check()
        session._ollama_review(Mock(inner_text=Mock(return_value="Review and Submit")), Mock(resume_key=None, job={}), {}, check, 1)
        session.llm.review_application_step.assert_called_once()
        self.assertFalse(check.ok)

    def test_parallel_workers_never_share_a_code(self):
        from jobbot import gmail
        from unittest.mock import patch
        msg = {"internalDate": "9999999999000", "snippet": "Your verification code is 482913",
               "payload": {"headers": [{"name": "From", "value": "no-reply@greenhouse-mail.io"}]}}
        gmail._USED_CODES.clear()
        with patch.object(gmail, "_get", side_effect=lambda path, params=None: {"messages": [{"id": "m"}]} if path == "messages" else msg):
            self.assertEqual(gmail.latest_code(0, hint=["greenhouse"], wait=0), "482913")
            self.assertIsNone(gmail.latest_code(0, hint=["greenhouse"], wait=0))   # the next application waits for its own
        gmail._USED_CODES.clear()

    def test_learned_answers_merge_across_workers(self):
        from jobbot.memory import Memory
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "profile.yaml"
            path.write_text("personal: {}\n", encoding="utf-8")
            a, b = Memory(path, []), Memory(path, [])
            a.remember("Notice period buy-out possible?", "Yes")
            b.remember("Open to relocation within India?", "Yes")
            self.assertEqual(len(Memory(path, yaml.safe_load(path.read_text())["learned_answers"]).items), 2)

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

    def test_password_only_on_job_platforms_and_the_postings_own_site(self):
        from jobbot.apply.auth import host_allowed
        p = Profile({}, "x")
        job = "https://careers.qualcomm.com/careers/job/1"
        self.assertTrue(host_allowed("https://careers.qualcomm.com/careers/login", p, job))
        self.assertTrue(host_allowed("https://factset.wd108.myworkdayjobs.com/x", p))
        self.assertFalse(host_allowed("https://accounts.google.com/signin", p, "https://careers.google.com/jobs/1"))
        self.assertFalse(host_allowed("https://login.example.net/", p, job))
        self.assertFalse(host_allowed("http://careers.qualcomm.com/login", p, job))

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

    def test_greenhouse_security_code(self):
        from jobbot.gmail import extract_code
        text = ("Security code for your application to Point72 . Copy and paste this code into the security "
                "code field on your application: XMnd6oJx After you enter the code, resubmit your application.")
        self.assertEqual(extract_code(text), "XMnd6oJx")

    def test_email_code_never_uses_another_sites_code(self):
        from jobbot import gmail
        from unittest.mock import patch
        unrelated = {"internalDate": "200000", "snippet": "Verification code 123456",
                     "payload": {"headers": [{"name": "From", "value": "auth@unrelated.example"}]}}
        with patch.object(gmail, "_get", side_effect=[{"messages": [{"id": "one"}]}, unrelated]):
            self.assertIsNone(gmail.latest_code(0, hint=["workday", "socure"], wait=0))

    def test_email_login_fills_code_without_prompting(self):
        from jobbot.apply.engine import Session
        from unittest.mock import Mock
        session = Session.__new__(Session)
        session._fields = Mock(return_value=[{"id": "otp", "kind": "text", "label": "Verification code", "value": ""}])
        session._code_from_email = Mock(return_value="123456")
        session._buttons = Mock(return_value=[{"text": "Verify"}])
        session._click, session.ui = Mock(), Mock()
        page = Mock()
        self.assertTrue(session._email_login_step(page))
        page.locator.return_value.fill.assert_called_once_with("123456")
        session._click.assert_called_once()

    def test_skip_is_never_consent(self):
        from jobbot.ui.bridge import WebUI, ApplyRun
        from jobbot.apply.engine import NeedsYou
        from unittest.mock import patch
        ui = WebUI(ApplyRun())
        with patch.object(ui, "_wait", return_value="skip"):
            with self.assertRaises(NeedsYou):
                ui.confirm("Accept terms?")
        with patch.object(ui, "_wait", return_value="false"):
            self.assertFalse(ui.confirm("Accept terms?"))

    def test_current_field_correction_and_protected_fields(self):
        from jobbot.apply.engine import Session
        from unittest.mock import Mock
        session = Session.__new__(Session)
        session._fields = Mock(return_value=[{"id": "email", "kind": "text", "label": "Email"}])
        session.ui = Mock()
        session._manual_records, session._mine, session._broken = {}, set(), set()
        page = Mock()
        session._correct_field(page, {"field": "email", "value": "asha@example.com"})
        page.locator.return_value.fill.assert_called_once_with("asha@example.com")
        self.assertEqual(session._manual_records["email"]["expected"], "asha@example.com")
        page.reset_mock()
        session._fields.return_value = [{"id": "sex", "kind": "select", "label": "Gender"}]
        session._correct_field(page, {"field": "sex", "value": "Female"})
        page.locator.assert_not_called()
