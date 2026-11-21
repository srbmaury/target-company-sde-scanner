"""Regression checks for extracted pure helpers and public compatibility imports."""
import unittest

from jobbot import answer_options, answers
from jobbot.apply import engine, text_length
from jobbot.ui import docs_routes, job_views, server


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
