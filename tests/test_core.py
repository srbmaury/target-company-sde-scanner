import os
import tempfile
import unittest

from jobbot import tracker
from jobbot.answers import Resolver, pick
from jobbot.profile import Profile
from jobbot.rank import keyword_rank
from jobbot.scan import classify, stated_years

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
        self.assertTrue(matches("+91 7355069174", "73550 69174", "text"))       # sites reformat phones
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
