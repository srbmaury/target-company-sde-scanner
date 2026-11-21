"""Tests for scan and rank."""

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from jobbot import tracker
from jobbot.profile import Profile
from jobbot.rank import keyword_rank
from jobbot.careers_page import jobs_in_json
from jobbot.scan import _pick, classify, stated_years

from core_fixtures import set_up_workspace


def setUpModule():
    set_up_workspace()


class ScanParsingTest(unittest.TestCase):
    def test_source_location_metadata_is_removed(self):
        from unittest.mock import patch
        from jobbot import scan

        self.assertEqual(scan.clean_location("Remote Job | Posted on 11/04/2026"), "Remote Job")
        self.assertEqual(scan.clean_location("Bangalore | Hyderabad"), "Bangalore | Hyderabad")
        with patch.object(scan, "http_json", return_value={"jobs": [
            {"location": "Bangalore – Engineering", "department": "Engineering"},
            {"location": "Remote – India", "department": "Engineering"},
        ]}):
            self.assertEqual([job["location"] for job in scan.ashby({"id": "uipath"})],
                             ["Bangalore", "Remote – India"])

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
                         "1–4 yrs in title")

    def test_target_ranges_include_senior_and_graduate_roles(self):
        import re
        loc = re.compile("India")
        job = {"title": "Senior Software Engineer", "location": "India",
               "text": "Requires 4–7 years of software engineering experience."}
        self.assertEqual(classify(job, loc, 6, 5)[0], "4–7 yrs stated")
        self.assertIsNone(classify(job, loc, 10, 8))
        self.assertIsNone(classify(job, loc, 3, 1))
        grad = {**job, "title": "Graduate Software Engineer (0–1 years)"}
        self.assertEqual(classify(grad, loc, 0, 0)[0], "0–1 yrs in title")
        self.assertEqual(classify({**job, "title": "Software Engineer (0.5 to 2 years)"}, loc, 3)[0],
                         "0.5–2 yrs in title")

    def test_scan_profile_defaults_and_overrides(self):
        from jobbot.profile import ProfileError

        self.assertEqual(Profile({}, "test").scan_experience(), (1, 3))
        profile = Profile({"preferences": {"min_yoe": 4, "max_yoe": 7}}, "test")
        self.assertEqual(profile.scan_experience(), (4, 7))
        self.assertEqual(profile.scan_experience(max_yoe=9), (4, 9))
        for invalid in (-1, "5", True, 8):
            with self.subTest(invalid=invalid), self.assertRaises(ProfileError):
                profile.scan_experience(min_yoe=invalid)

    def test_scan_reports_presence_before_filtering(self):
        from unittest.mock import patch
        from jobbot import scan

        registry = {"Acme": {"ats": "greenhouse", "id": "acme"}}
        job = {"title": "Software Engineer II", "location": "India", "url": "https://example.test/1",
               "text": "2 to 3 years of experience", "posted": ""}
        seen = set()
        with patch.object(scan, "load_registry", return_value=registry), patch.object(scan, "fetch", return_value=[job]):
            results, coverage, _ = scan.run_scan(min_yoe=4, max_yoe=6, seen_urls=seen)
        self.assertEqual(results, [])
        self.assertEqual(seen, {job["url"]})
        self.assertNotIn("incomplete", coverage["Acme"])

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


class RankTest(unittest.TestCase):
    def test_keyword_rank_prefers_matching_resume(self):
        job = {"title": "Backend Engineer", "description": "java spring kafka microservices", "experience": "2+ yrs stated"}
        score, key, _ = keyword_rank(job, {"fe": "react css figma", "be": "java spring kafka microservices redis"})
        self.assertEqual(key, "be")
        self.assertGreater(score, 0)


class ScanAndRankRegressionTests(unittest.TestCase):
    def test_role_gone_only_after_two_complete_misses(self):
        conn = tracker.connect(Path(tempfile.mkdtemp()) / "t.db")
        job = {"url": "https://acme.example/1", "company": "Acme", "title": "Engineer", "location": "Pune",
               "experience": "", "evidence": ""}
        tracker.upsert_jobs(conn, [job])
        self.assertEqual(tracker.mark_gone(conn, [], ["Acme"]), 0)     # one missed scan: still listed
        self.assertEqual(conn.execute("SELECT gone FROM jobs").fetchone()[0], 0)
        tracker.mark_gone(conn, [job["url"]], ["Acme"])                # seen again even if filtered out
        tracker.mark_gone(conn, [], ["Acme"])
        self.assertEqual(conn.execute("SELECT gone FROM jobs").fetchone()[0], 0)
        self.assertEqual(tracker.mark_gone(conn, [], ["Acme"]), 1)     # two in a row: no longer listed
        tracker.mark_gone(conn, [job["url"]], [])                      # seen even on an incomplete board
        self.assertFalse(tracker.get_job(conn, job["url"])["gone"])
        conn.close()

    def test_incomplete_board_reads_are_flagged(self):
        from jobbot import scan
        from unittest.mock import patch
        def flaky(url, data=None, timeout=25):
            if "/jobs" in url and data is not None:
                return {"total": 1, "jobPostings": [{"externalPath": "/job/x", "title": "Software Engineer",
                                                     "locationsText": "Bengaluru, India"}]}
            raise OSError("detail fetch failed")
        with patch.object(scan, "http_json", side_effect=flaky):
            out = list(scan.workday({"host": "h", "tenant": "t", "site": "s"}, ["engineer"], __import__("re").compile("India")))
        self.assertEqual(out, [scan.INCOMPLETE])   # the posting exists but was not read: never "no longer listed"

    def test_required_experience_wins_over_preferred(self):
        from jobbot.scan import stated_years
        text = "5+ years of experience preferred in distributed systems. Minimum 2+ years of experience in Java required."
        self.assertEqual(stated_years(text)[0], 2)

    def test_careers_pages_never_mark_roles_gone(self):
        from jobbot import scan
        from unittest.mock import patch
        registry = {"Exotel": {"ats": "careers-page", "url": "https://exotel.example/careers"}}
        def fake_pages(pages, rules, on_done):
            on_done("Exotel", [{"title": "Software Engineer 2", "location": "Bengaluru", "url": "https://exotel.example/1",
                                "text": "2+ years of experience", "posted": ""}])
        with patch.object(scan, "load_registry", return_value=registry), \
                patch("jobbot.careers_page.scan_careers_pages", side_effect=fake_pages):
            _, coverage, _ = scan.run_scan(companies=["Exotel"])
        self.assertIn("incomplete", coverage["Exotel"])
