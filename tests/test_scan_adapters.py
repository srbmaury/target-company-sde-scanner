"""Normalization contracts for ATS job-board responses."""

import unittest
from unittest.mock import patch

from jobbot import scan


class ATSAdapterTests(unittest.TestCase):
    def test_greenhouse_normalizes_content_location_and_date(self):
        payload = {"jobs": [{
            "title": "Backend Engineer",
            "location": {"name": "Bengaluru"},
            "absolute_url": "https://example.com/greenhouse",
            "content": "<p>Python &amp; SQL</p>",
            "updated_at": "2026-11-20T09:00:00Z",
        }]}
        with patch.object(scan, "http_json", return_value=payload) as fetch:
            jobs = list(scan.greenhouse({"id": "example"}))

        fetch.assert_called_once_with("https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true")
        self.assertEqual(jobs, [{
            "title": "Backend Engineer", "location": "Bengaluru",
            "url": "https://example.com/greenhouse", "text": " Python & SQL ", "posted": "2026-11-20",
        }])

    def test_lever_uses_regional_host_and_location_fallback(self):
        payload = [{
            "text": "Software Engineer",
            "categories": {"allLocations": ["Pune", "Remote"]},
            "hostedUrl": "https://example.com/lever",
            "descriptionPlain": "Backend team",
            "lists": [{"content": "<li>Python</li>"}],
        }]
        with patch.object(scan, "http_json", return_value=payload) as fetch:
            jobs = list(scan.lever({"id": "example"}, host="api.eu.lever.co"))

        fetch.assert_called_once_with("https://api.eu.lever.co/v0/postings/example?mode=json")
        self.assertEqual(jobs, [{
            "title": "Software Engineer", "location": "Pune, Remote",
            "url": "https://example.com/lever", "text": "Backend team  Python ", "posted": "",
        }])

    def test_ashby_normalizes_secondary_locations_and_department_suffix(self):
        payload = {"jobs": [{
            "title": "Software Engineer",
            "location": "Bengaluru – Engineering",
            "secondaryLocations": [{"location": "Pune"}, {}],
            "department": "Engineering",
            "jobUrl": "https://example.com/ashby",
            "descriptionPlain": "Platform team",
            "publishedAt": "2026-11-19T09:00:00Z",
        }]}
        with patch.object(scan, "http_json", return_value=payload) as fetch:
            jobs = list(scan.ashby({"id": "example"}))

        fetch.assert_called_once_with("https://api.ashbyhq.com/posting-api/job-board/example")
        self.assertEqual(jobs, [{
            "title": "Software Engineer", "location": "Bengaluru; Pune",
            "url": "https://example.com/ashby", "text": "Platform team", "posted": "2026-11-19",
        }])
