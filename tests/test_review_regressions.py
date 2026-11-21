"""Regression tests for ambiguous application submissions and fallback ranking."""

import sqlite3
import unittest

from jobbot import tracker
from jobbot.rank import keyword_rank


class SubmissionStateTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(tracker.SCHEMA)

    def tearDown(self):
        self.conn.close()

    def test_unverified_is_not_counted_as_confirmed_application(self):
        app = tracker.add_application(self.conn, "Acme", "Engineer", url="https://example.com/1",
                                      status="submission_unverified", source="jobbot")
        self.assertIsNone(app["applied_on"])
        self.assertEqual(tracker.submitted_today(self.conn), 1)
        level, match = tracker.applied_match(self.conn, url="https://example.com/1")
        self.assertEqual(level, "exact")
        self.assertEqual(match["status"], "submission_unverified")

    def test_confirming_unverified_sets_application_date(self):
        app = tracker.add_application(self.conn, "Acme", "Engineer", url="https://example.com/2",
                                      status="submission_unverified")
        confirmed = tracker.update_status(self.conn, app["id"], "applied")
        self.assertEqual(confirmed["applied_on"], tracker.today())
        self.assertEqual(tracker.submitted_today(self.conn), 1)

    def test_unverified_does_not_overwrite_confirmed(self):
        original = tracker.add_application(self.conn, "Acme", "Engineer", url="https://example.com/3",
                                           status="applied")
        result = tracker.add_application(self.conn, "Acme", "Engineer", url="https://example.com/3",
                                         status="submission_unverified")
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["id"], original["id"])


class RankingRegressionTests(unittest.TestCase):
    def test_title_matches_are_weighted(self):
        job = {"title": "Backend Engineer", "description": "Python Kubernetes monitoring"}
        score, resume, _ = keyword_rank(job, {
            "backend": "Backend Engineer Java",
            "other": "Python Kubernetes monitoring",
        })
        self.assertEqual(resume, "backend")
        self.assertGreater(score, 0)

    def test_insufficient_experience_lowers_score(self):
        job = {"title": "Backend Engineer", "description": "Java Spring", "experience": "5+ years"}
        resumes = {"backend": "Backend Engineer Java Spring"}
        eligible = keyword_rank(job, resumes, experience_years=6)[0]
        ineligible = keyword_rank(job, resumes, experience_years=1)[0]
        self.assertGreater(eligible, ineligible)


if __name__ == "__main__":
    unittest.main()
