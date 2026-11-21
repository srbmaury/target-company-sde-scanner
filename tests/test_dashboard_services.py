"""Tests for dashboard services."""

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from jobbot import tracker

from core_fixtures import set_up_workspace


def setUpModule():
    set_up_workspace()


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


class DashboardServicesRegressionTests(unittest.TestCase):
    def test_finished_run_deletion_keeps_active_run_and_other_history(self):
        from unittest.mock import patch
        from jobbot.accounts import AccountError
        from jobbot.ui import bridge

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(bridge, "RUNS_FILE", return_value=Path(directory) / "runs.json"), \
                patch.dict(bridge.CURRENT):
            run = bridge.ApplyRun()
            bridge.CURRENT["run"] = run
            bridge._write_local_runs([{"id": "older", "status": "done"}, run.snapshot()])
            with self.assertRaises(AccountError):
                bridge.delete_run(run.id)
            self.assertTrue(bridge.delete_run("older"))
            self.assertFalse(bridge.delete_run("older"))
            run.status, run.ended = "done", run.started
            run.save()
            self.assertTrue(bridge.delete_run(run.id))
            self.assertIsNone(bridge.current())
            self.assertEqual(bridge.history(), [])

    def test_saved_runs_leave_out_screenshots(self):
        import json
        from unittest.mock import patch
        from jobbot.ui import bridge
        run = bridge.ApplyRun()
        run.preview = "x" * 1000
        out = Path(tempfile.mkdtemp()) / "runs.json"
        with patch.object(bridge, "RUNS_FILE", return_value=out), patch.object(bridge, "_load_runs", return_value=[]):
            run.save()
        self.assertIsNone(json.loads(out.read_text())[0]["preview"])
