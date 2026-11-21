"""Regression checks for extracted pure helpers and public compatibility imports."""
import re
import unittest
from unittest.mock import patch

from jobbot import answer_options, answers, cli, cli_format, scan, scan_filters, scan_registry
from jobbot.apply import engine, text_length
from jobbot.ui import docs_routes, job_queries, job_views, server, summary, tasks, workspace


class ExtractionTests(unittest.TestCase):
    def test_answer_public_api_is_preserved(self):
        self.assertIs(answers.Answer, answer_options.Answer)
        self.assertIs(answers.pick, answer_options.pick)
        self.assertIs(answers.bucket, answer_options.bucket)
        self.assertIs(answers.yes_no, answer_options.yes_no)
        self.assertEqual(answers.bucket(2, ['0-1 years', '2-3 years']), 1)
        self.assertEqual(answers.pick("No", ["Yes", "No"]), 1)

    def test_engine_text_length_api_is_preserved(self):
        self.assertIs(engine.fit_length, text_length.fit_length)
        self.assertIs(engine.refit_if_cut, text_length.refit_if_cut)
        self.assertEqual(text_length._trim("hello world goodbye", 11), "hello")

    def test_cli_formatting_api_is_preserved(self):
        self.assertTrue(callable(cli.expand_job_keys))
        self.assertEqual(cli.expand_job_keys(['3-1', '7,9', 'https://example.org/a,b']),
                         ['1', '2', '3', '7', '9', 'https://example.org/a,b'])
        self.assertIs(cli._short, cli_format._short)

    def test_dashboard_summary_excludes_unverified_submissions(self):
        counts = {"applied": 2, "interview": 1, "submission_unverified": 3, "shortlisted": 4}
        with patch.object(summary.tracker, "stats", return_value=counts):
            payload = summary.summary_payload(None, open_jobs=7)
        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["response_rate"], 33)
        self.assertEqual(payload["interview_rate"], 33)
        self.assertEqual(payload["open_jobs"], 7)

    def test_scanner_classification_filter(self):
        india = re.compile("India", re.I)
        role = {"title": "Software Engineer", "location": "India", "text": "2 years experience"}
        self.assertEqual(scan.classify(role, india, 3), scan_filters.classify(role, india, 3))
        self.assertIsNone(scan_filters.classify({**role, "title": "Sales Engineer"}, india, 3))
        self.assertIsNone(scan_filters.classify({**role, "location": "Canada"}, india, 3))

    def test_scanner_registry_helpers_preserve_public_behavior(self):
        registry = {"Acme": {}, "Example": {}}
        self.assertEqual(scan.resolve_names(registry, ["acme", "missing"]), (["Acme"], ["missing"]))
        self.assertEqual(scan_registry.resolve_names(registry), (["Acme", "Example"], []))
        self.assertEqual(scan.load_history(None), set())
        self.assertEqual(scan.REGISTRY, scan_registry.REGISTRY)

    def test_dashboard_job_query_api_is_preserved(self):
        self.assertTrue(callable(job_queries.jobs_payload))
        self.assertTrue(callable(job_queries._new_jobs))
        self.assertTrue(callable(server.jobs_payload))
        self.assertTrue(callable(server._new_jobs))

    def test_dashboard_workspace_api_is_preserved(self):
        self.assertTrue(callable(workspace.workspace_payload))
        self.assertTrue(callable(server.workspace_payload))

    def test_dashboard_tasks_are_shared_with_server(self):
        self.assertIs(server.TASKS, tasks.TASKS)
        with self.assertRaisesRegex(ValueError, "unknown task"):
            server.start_task("not-a-task")

    def test_dashboard_view_api_is_preserved(self):
        self.assertIs(server.jobs_page, job_views.jobs_page)
        self.assertIs(server.table_page, job_views.table_page)
        rows = [{"n": 2}, {"n": 1}]
        self.assertEqual(job_views.table_page(rows, {"sort": "n", "direction": "asc"}, {"n"}, "n")["rows"],
                         [{"n": 1}, {"n": 2}])

    def test_dashboard_docs_api_is_preserved(self):
        self.assertIs(server.docs_index, docs_routes.docs_index)
        self.assertIs(server.doc_page, docs_routes.doc_page)
        self.assertIsNone(docs_routes.doc_page("../secrets"))


if __name__ == "__main__":
    unittest.main()
