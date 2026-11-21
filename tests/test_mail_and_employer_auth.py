"""Tests for mail and employer auth."""

import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from jobbot import tracker
from jobbot.profile import Profile

from core_fixtures import set_up_workspace


def setUpModule():
    set_up_workspace()


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


class StaleCodeTest(unittest.TestCase):
    def test_run_refused_after_code_changes(self):
        # A dashboard started before a code update would mix old and new modules mid-run.
        from unittest.mock import patch
        from jobbot.ui import bridge
        with patch.object(bridge, "LOADED_AT", 0):
            with self.assertRaisesRegex(ValueError, "Restart it"):
                bridge.start(["1"])
        self.assertFalse(bridge.code_changed())


class MailAndEmployerAuthRegressionTests(unittest.TestCase):
    def test_gmail_token_written_atomically(self):
        import json
        from unittest.mock import patch
        from jobbot import gmail
        home = Path(tempfile.mkdtemp())
        with patch.object(gmail, "token_path", return_value=home / "gmail_token.json"), \
                patch.object(gmail.paths, "ensure_home"):
            gmail._save_token({"access_token": "a", "expires_at": 9e12})
            self.assertEqual(json.loads((home / "gmail_token.json").read_text())["access_token"], "a")
            self.assertFalse((home / "gmail_token.tmp").exists())
            self.assertEqual(gmail.access_token(), "a")

    def test_parallel_workers_never_share_a_code(self):
        from jobbot import gmail
        from unittest.mock import patch
        msg = {"internalDate": "9999999999000", "snippet": "Your verification code is 482913",
               "payload": {"headers": [{"name": "From", "value": "no-reply@greenhouse-mail.io"}]}}
        gmail._USED_CODES.clear()
        with patch.object(gmail, "_get", side_effect=lambda path, params=None: {"messages": [{"id": "m"}]} if path == "messages" else msg):
            self.assertEqual(gmail.latest_code(0, hint=["greenhouse"], wait=0), "482913")
            self.assertIsNone(gmail.latest_code(0, hint=["greenhouse"], wait=0))   # the next application waits for its own
        gmail._USED_CODES.clear()

    def test_identity_challenge_detects_unlabelled_split_code_fields(self):
        from unittest.mock import Mock
        from jobbot.apply.email_verification import challenge_fields, fill_code

        page = Mock()
        slots = [{"id": str(i), "kind": "text", "maxlength": 1} for i in range(6)]
        page.locator.return_value.inner_text.return_value = "Confirm Your Identity. The verification code was sent by email."
        self.assertEqual(challenge_fields(page, slots), slots)
        page.locator.return_value.input_value.return_value = ""
        self.assertTrue(fill_code(page, slots, "012345"))
        self.assertEqual([call.args[0] for call in page.locator.return_value.fill.call_args_list], list("012345"))
        page.locator.return_value.inner_text.return_value = "Enter your contact information"
        self.assertEqual(challenge_fields(page, slots), [])

    def test_post_submit_code_accepts_manual_input_in_hosted_unattended_run(self):
        from unittest.mock import Mock, patch
        from jobbot.apply.engine import Session, UnattendedUI

        session = Session.__new__(Session)
        session.hosted = True
        session.ui = UnattendedUI(Mock())
        session.ui.inner.ask_code.return_value = "012345"
        session._code_from_email = Mock(return_value=None)
        session._confirmation = Mock(side_effect=[None, "Thank you for applying"])
        boxes = [{"kind": "text", "autocomplete": "one-time-code", "id": "otp"}]
        session._fields = Mock(return_value=boxes)
        session._click = Mock(return_value=True)
        page = Mock()
        with patch("jobbot.apply.email_verification.fill_code", return_value=True) as fill:
            self.assertEqual(session._complete_email_submission(page, boxes, 100, "workday", "^submit$"),
                             ("applied", "Thank you for applying"))
        session._code_from_email.assert_called_once_with(page, since=100, provider="workday")
        session.ui.inner.ask_code.assert_called_once()
        fill.assert_called_once_with(page, boxes, "012345")
        session._click.assert_called_once()

    def test_hosted_auth_attempts_signup_before_password_login(self):
        from unittest.mock import Mock, patch
        from jobbot.apply import auth

        session = Mock()
        session.hosted = True
        session.profile = Profile({"automation": {"create_accounts": True}}, "test")
        session._signup_checked = set()
        session._fields.return_value = []
        session._email_login_step.return_value = False
        session._workday_account.return_value = False
        page = Mock(url="https://jobs.example.test/login")
        page.inner_text.return_value = "Sign in"
        page.locator.return_value.count.return_value = 1
        order = []
        with patch.object(auth, "needs_account", side_effect=[True, False]), \
                patch.object(auth, "hosted_auth_allowed", return_value=True), \
                patch.object(auth, "check_page", return_value=Mock(captcha=False)), \
                patch.object(auth, "sign_up", side_effect=lambda *_: order.append("signup") or False), \
                patch.object(auth, "go_to_sign_up", return_value=False), \
                patch.object(auth, "password_sign_in", side_effect=lambda *_: order.append("login") or True):
            self.assertTrue(auth.ensure_signed_in(session, page))
        self.assertEqual(order, ["signup", "login"])

    def test_hosted_employer_password_requires_https_and_live_run(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from jobbot.apply.auth import password_candidates

        host = "employer.wd5.myworkdayjobs.com"
        url = f"https://{host}/login"
        profile = Profile({"personal": {"email": "candidate@example.test"},
                           "automation": {}}, "test")
        session = SimpleNamespace(hosted=True, dry_run=False, profile=profile)
        with patch.dict(os.environ, {"JOBBOT_EMPLOYER_PASSWORD": "fixture-only"}):
            self.assertEqual(password_candidates(session, url, "candidate@example.test"), ["fixture-only"])
            for denied in ("http://" + host, "https://unrelated.example.test",
                           "https://accounts.google.com"):
                self.assertEqual(password_candidates(session, denied, "candidate@example.test"), [])
            session.dry_run = True
            self.assertEqual(password_candidates(session, url, "candidate@example.test"), [])

    def test_password_only_on_job_platforms_and_the_postings_own_site(self):
        from jobbot.apply.auth import host_allowed
        p = Profile({}, "x")
        job = "https://careers.qualcomm.com/careers/job/1"
        self.assertTrue(host_allowed("https://careers.qualcomm.com/careers/login", p, job))
        self.assertTrue(host_allowed("https://factset.wd108.myworkdayjobs.com/x", p))
        self.assertFalse(host_allowed("https://accounts.google.com/signin", p, "https://careers.google.com/jobs/1"))
        self.assertFalse(host_allowed("https://login.example.net/", p, job))
        self.assertFalse(host_allowed("http://careers.qualcomm.com/login", p, job))

    def test_greenhouse_security_code(self):
        from jobbot.gmail import extract_code
        text = ("Security code for your application to Point72 . Copy and paste this code into the security "
                "code field on your application: XMnd6oJx After you enter the code, resubmit your application.")
        self.assertEqual(extract_code(text), "XMnd6oJx")

    def test_email_code_never_uses_another_sites_code(self):
        from jobbot import gmail
        from unittest.mock import patch
        unrelated = {"internalDate": "200000", "snippet": "Verification code 123456",
                     "payload": {"headers": [{"name": "From", "value": "auth@unrelated.example"}]}}
        with patch.object(gmail, "_get", side_effect=[{"messages": [{"id": "one"}]}, unrelated]):
            self.assertIsNone(gmail.latest_code(0, hint=["workday", "socure"], wait=0))

    def test_email_login_fills_code_without_prompting(self):
        from jobbot.apply.engine import Session
        from unittest.mock import Mock
        session = Session.__new__(Session)
        session._fields = Mock(return_value=[{"id": "otp", "kind": "text", "label": "Verification code", "value": ""}])
        session._code_from_email = Mock(return_value="123456")
        session._buttons = Mock(return_value=[{"text": "Verify"}])
        session._click, session.ui = Mock(), Mock()
        page = Mock()
        self.assertTrue(session._email_login_step(page))
        page.locator.return_value.fill.assert_called_once_with("123456")
        session._click.assert_called_once()
