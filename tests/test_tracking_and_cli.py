"""Tests for tracking and CLI."""

import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from jobbot import tracker
from jobbot.answers import Resolver
from jobbot.profile import Profile

from core_fixtures import PROFILE, set_up_workspace


def setUpModule():
    set_up_workspace()


class AnswerLogAndCapTest(unittest.TestCase):
    def test_model_answers_logged_and_reviewed(self):
        from jobbot import paths
        from jobbot._answering import log as answerlog
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
        from jobbot.ui import job_queries, server
        with tempfile.TemporaryDirectory() as d:
            conn = tracker.connect(os.path.join(d, "t.db"))
            tracker.upsert_jobs(conn, [{"url": u, "company": c, "title": "SDE II", "location": "", "experience": "", "evidence": ""}
                                       for u, c in (("u1", "Amazon"), ("u2", "Socure"))])
            with patch.object(job_queries, "_excluded_companies", return_value=["amazon"]):
                flags = {j["company"]: j["excluded"] for j in server.jobs_payload(conn, {})}
                self.assertEqual(flags, {"Amazon": True, "Socure": False})
                self.assertEqual(server._new_jobs(conn), 1)

    def test_roles_missing_from_a_good_scan_are_gone(self):
        # Acme's board was read twice and no longer lists u1; Beta's board errored, so u3 is kept.
        with tempfile.TemporaryDirectory() as d:
            conn = tracker.connect(os.path.join(d, "t.db"))
            job = lambda u, c: {"url": u, "company": c, "title": "SDE II", "location": "", "experience": "", "evidence": ""}
            tracker.upsert_jobs(conn, [job("u1", "Acme"), job("u2", "Acme"), job("u3", "Beta")])
            self.assertEqual(tracker.mark_gone(conn, ["u2"], ["Acme"]), 0)   # one miss is not enough
            self.assertEqual(tracker.mark_gone(conn, ["u2"], ["Acme"]), 1)
            self.assertEqual({r["url"] for r in tracker.list_jobs(conn)}, {"u2", "u3"})
            self.assertEqual(len(tracker.list_jobs(conn, include_gone=True)), 3)
            tracker.upsert_jobs(conn, [job("u1", "Acme")])   # listed again
            self.assertEqual({r["url"] for r in tracker.list_jobs(conn)}, {"u1", "u2", "u3"})


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


class TrackingAndCliRegressionTests(unittest.TestCase):
    def test_duplicate_check_uses_same_company(self):
        conn = tracker.connect(Path(tempfile.mkdtemp()) / "t.db")
        tracker.add_application(conn, "Cisco Systems", "Software Engineer II")
        level, _ = tracker.applied_match(conn, url="https://cisco.example/2", company="Cisco", title="Software Engineer II")
        self.assertEqual(level, "likely")

    def test_title_shorthand_whole_words_only(self):
        self.assertIn("development", tracker.title_tokens("SDE-2 Backend"))
        self.assertNotIn("development", tracker.title_tokens("Insider Threat Analyst"))

    def test_status_never_moves_back_to_applied(self):
        conn = tracker.connect(Path(tempfile.mkdtemp()) / "t.db")
        tracker.add_application(conn, "Acme", "Engineer", url="https://acme.example/1", status="rejected")
        row = tracker.add_application(conn, "Acme", "Engineer", url="https://acme.example/1", status="applied")
        self.assertEqual(row["status"], "rejected")
