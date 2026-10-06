import os
import tempfile
import unittest
from pathlib import Path

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
