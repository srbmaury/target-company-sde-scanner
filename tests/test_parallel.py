"""Regression checks for unattended multi-browser batches."""
import io
import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from jobbot.answers import Resolver
from jobbot.profile import Profile


class ParallelRegressionTest(unittest.TestCase):
    def test_no_default_daily_cap(self):
        from jobbot.apply.runner import run_jobs
        profile = Profile({}, "fixture")
        profile.resumes = Mock(return_value={"backend": {}})
        session = Mock()
        session.apply.return_value = (None, "fixture")
        targets = [{"url": f"fixture-{i}", "company": "Fixture", "title": "Engineer"} for i in range(30)]
        with patch("jobbot.resumes.parse_all"), patch("jobbot.tracker.submitted_today", side_effect=AssertionError("unexpected daily cap")):
            results = run_jobs(session, Mock(), profile, targets, Mock())
        self.assertEqual(len(results), 30)
        self.assertEqual(session.apply.call_count, 30)

    def test_wrong_university_cannot_fall_back_to_model(self):
        profile = Profile({"education": {"school": ["Indian Institute of Technology", "IIT (BHU)", "Varanasi"]}}, "fixture")
        model = Mock(enabled=True)
        resolver = Resolver(profile, llm=model)
        self.assertIsNone(resolver.resolve("University/College", "choice", ["IIT Bombay", "IIT Delhi"]))
        model.answer.assert_not_called()
        self.assertEqual(resolver.resolve("University/College", "choice", ["IIT Bombay", "IIT (BHU), Varanasi"]).display, "IIT (BHU), Varanasi")

    def test_smartrecruiters_follows_application_link(self):
        from jobbot.apply.engine import Session
        session = Session.__new__(Session)
        session._decline_cookies = Mock()
        application = Mock()
        session._open_application = Mock(return_value=application)
        posting = Mock()
        self.assertIs(session._enter_form(posting, "smartrecruiters"), application)
        session._open_application.assert_called_once_with(posting)

    def test_failed_workers_report_all_jobs(self):
        from jobbot.ui.bridge import ApplyRun, _parallel
        run = ApplyRun()
        jobs = [{"url": f"fixture-{i}", "company": "Fixture", "title": "Engineer"} for i in range(10)]
        run.jobs = jobs
        connections = []
        def connect():
            conn = Mock()
            connections.append(conn)
            return conn
        def result(job, status, note, application):
            run.results[job["url"]] = {"status": status}
        with patch("jobbot.ui.bridge.worker_browser_dir", side_effect=lambda i: f"fixture-{i}"), patch("jobbot.ui.bridge.tracker.connect", side_effect=connect), patch("jobbot.apply.engine.Session", side_effect=SystemExit("fixture startup failure")):
            _parallel(run, Mock(), Mock(), Mock(), jobs, 4, None, result)
        self.assertEqual(len(run.results), 10)
        self.assertTrue(all(r["status"] == "not submitted" for r in run.results.values()))
        self.assertEqual(len(connections), 4)
        for conn in connections:
            conn.close.assert_called_once()

    def test_model_requests_share_two_slots(self):
        from jobbot.llm import LLM
        lock = threading.Lock()
        active = peak = 0
        def response(*args, **kwargs):
            class Response(io.BytesIO):
                def __enter__(self):
                    nonlocal active, peak
                    with lock:
                        active += 1
                        peak = max(peak, active)
                    time.sleep(.04)
                    return self
                def __exit__(self, *args):
                    nonlocal active
                    with lock:
                        active -= 1
                    self.close()
            return Response(json.dumps({"message": {"content": "ok"}}).encode())
        model = LLM.__new__(LLM)
        model.enabled, model.model = True, "fixture"
        with patch("jobbot.llm.urllib.request.urlopen", side_effect=response), ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(list(pool.map(lambda _: model.chat("fixture", "fixture"), range(4))), ["ok"] * 4)
        self.assertEqual(peak, 2)

    def test_snapshot_results_are_detached(self):
        from jobbot.ui.bridge import ApplyRun
        run = ApplyRun()
        snap = run.snapshot()
        run.results["fixture"] = {"status": "not submitted"}
        self.assertEqual(snap["results"], {})
