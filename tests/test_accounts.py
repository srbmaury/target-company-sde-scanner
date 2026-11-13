"""Hosted account tests with an in-process MongoDB substitute and mocked Google."""

import base64
import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import mongomock
from cryptography.fernet import Fernet

from jobbot import accounts, gmail, paths, profile, tracker
from jobbot.ui import server


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().jobbot
        self.key = Fernet.generate_key()
        self.account = self.new_account()
        self.account.initialize()
        for mock in (patch.dict(os.environ, {"JOBBOT_MONGODB_URI": "mongodb://unused"}),
                     patch.object(accounts, "current", return_value=self.account)):
            mock.start()
            self.addCleanup(mock.stop)

    def new_account(self, email="owner@example.com"):
        return accounts.Account(self.db, self.key, email, "https://jobbot.example.com",
                                {"client_id": "client", "client_secret": "secret"})

    @staticmethod
    def state(url):
        return parse_qs(urlsplit(url).query)["state"][0]

    def test_login_verifies_owner_and_binds_callback_to_browser(self):
        url, browser = self.account.begin("login")
        state = self.state(url)
        self.assertEqual(parse_qs(urlsplit(url).query)["scope"], ["openid email"])
        with patch.object(gmail, "exchange", return_value={"access_token": "access"}) as exchange, patch.object(
                gmail, "google_identity", return_value={"email_verified": True, "email": self.account.email}):
            with self.assertRaises(accounts.AccountError):
                self.account.finish(state, "different browser", "code", "")
            exchange.assert_not_called()
            token = self.account.finish(state, browser, "code", "")
            self.assertTrue(self.new_account().session(token))
            self.assertFalse(self.new_account("other@example.com").session(token))
            with self.assertRaises(accounts.AccountError):
                self.account.finish(state, browser, "code", "")
        self.new_account().logout(token)
        self.assertFalse(self.account.session(token))

    def test_unverified_or_unlisted_email_cannot_sign_in(self):
        for identity in ({"email_verified": False, "email": self.account.email},
                         {"email_verified": True, "email": "other@example.com"}):
            url, browser = self.account.begin("login")
            with patch.object(gmail, "exchange", return_value={"access_token": "access"}), patch.object(
                    gmail, "google_identity", return_value=identity), self.assertRaises(accounts.AccountError):
                self.account.finish(self.state(url), browser, "code", "")
        self.assertEqual(self.db.sessions.count_documents({}), 0)

    def test_gmail_grant_is_read_only_encrypted_and_revocable(self):
        session = self.account.new_session()
        url, browser = self.account.begin("gmail", session)
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params["scope"], ["openid email " + gmail.READ_SCOPE])
        self.assertEqual(params["access_type"], ["offline"])
        token = {"access_token": "access", "refresh_token": "refresh-secret", "scope": gmail.READ_SCOPE, "expires_at": 0}
        with patch.object(gmail, "exchange", return_value=token), patch.object(
                gmail, "google_identity", return_value={"email_verified": True, "email": self.account.email}):
            self.assertIsNone(self.account.finish(self.state(url), browser, "code", session))
        self.assertTrue(gmail.is_connected())
        self.assertFalse(gmail.can_modify())
        self.assertNotIn(b"refresh-secret", self.db.account_data.find_one()["value"])
        self.assertEqual(self.new_account().get_json("gmail"), token)
        with patch.object(gmail, "_post", return_value={}) as revoke:
            self.assertTrue(gmail.logout())
            revoke.assert_called_once_with(gmail.REVOKE_URL, {"token": "refresh-secret"})
        self.assertFalse(gmail.is_connected())

    def test_expired_gmail_grant_is_cleared(self):
        self.account.put_json("gmail", {"access_token": "old", "refresh_token": "expired", "expires_at": 0})
        with patch.object(gmail, "_post", side_effect=gmail.GmailError('Google returned 400: {"error":"invalid_grant"}')):
            with self.assertRaisesRegex(gmail.GmailError, "Reconnect Gmail"):
                gmail.access_token()
        self.assertFalse(gmail.is_connected())

    def test_disconnected_gmail_is_not_restored_by_inflight_refresh(self):
        self.account.put_json("gmail", {"access_token": "old", "refresh_token": "refresh", "expires_at": 0})

        def refresh(*_):
            self.account.remove("gmail")
            return {"access_token": "new", "expires_in": 3600}

        with patch.object(gmail, "_post", side_effect=refresh), self.assertRaises(gmail.GmailError):
            gmail.access_token()
        self.assertFalse(gmail.is_connected())

    def test_tracker_survives_connections_and_rejects_stale_writes(self):
        first, second = tracker.connect(), tracker.connect()
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        app = tracker.add_application(first, "Acme", "Engineer")
        with self.assertRaises(accounts.AccountError):
            tracker.add_application(second, "Different", "Engineer")
        reopened = tracker.connect()
        self.addCleanup(reopened.close)
        self.assertEqual([row["company"] for row in tracker.list_applications(reopened)], ["Acme"])
        self.assertEqual(len(tracker.events_for(reopened, app["id"])), 1)

    def test_fresh_account_starts_empty_and_uses_uploaded_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local_profile = root / "profile.yaml"
            local_profile.write_text("personal: {first_name: LocalOnly}\n")
            with patch.object(paths, "HOME", root), patch.object(paths, "CACHE", root / "cache"), patch.object(
                    paths, "PROFILE", local_profile):
                fresh = profile.load()
                self.assertEqual(fresh.get("personal"), {})
                self.assertEqual(fresh.resumes(), {})
                self.assertIsNone(self.account.get_json("gmail"))
                self.account.write("profile", b"personal: {first_name: Owner}\nresumes: {backend: {focus: Java}}\n")
                pdf = b"%PDF-1.4\nfixture"
                self.account.write("resume:backend", pdf)
                updated = profile.load()
                self.assertEqual(updated.full_name, "Owner")
                self.assertEqual(updated.resumes()["backend"]["path"].read_bytes(), pdf)
                self.assertEqual(local_profile.read_text(), "personal: {first_name: LocalOnly}\n")

    def test_http_session_host_origin_and_resume_upload(self):
        httpd = server.make_server(0, self.account)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        session = self.account.new_session()

        def request(path, body=None, cookie=None, origin="https://jobbot.example.com", host="jobbot.example.com"):
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
            headers = {"Host": host, "Origin": origin, "X-Jobbot-Token": httpd.RequestHandlerClass.token}
            if isinstance(cookie, str):
                headers["Cookie"] = server.Handler.session_cookie + "=" + cookie
            elif cookie:
                headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in cookie.items())
            conn.request("GET" if body is None else "POST", path,
                         body=None if body is None else json.dumps(body), headers=headers)
            response = conn.getresponse()
            result = response.status, response.read(), response.headers
            conn.close()
            return result

        self.assertIn(b"Continue with Google", request("/")[1])
        self.assertEqual(request("/api/profile")[0], 401)
        self.assertEqual(request("/api/profile", cookie=session, host="wrong.example.com")[0], 403)
        self.assertEqual(request("/api/profile", {}, cookie=session, origin="https://wrong.example.com")[0], 403)
        status, body, _ = request("/api/profile", cookie=session)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["text"], profile.ACCOUNT_PROFILE.decode())
        self.assertEqual(request("/api/profile", {"text": "personal: {}\n", "mtime": ""}, cookie=session)[0], 200)
        self.assertEqual(request("/api/profile", {"text": "personal: {}\n", "mtime": ""}, cookie=session)[0], 409)
        pdf = base64.b64encode(b"%PDF-1.4\nfixture").decode()
        self.assertEqual(request("/api/account/resume", {"key": "../bad", "pdf": pdf}, cookie=session)[0], 400)
        self.assertEqual(request("/api/account/resume", {"key": "backend", "pdf": pdf}, cookie=session)[0], 200)
        self.assertEqual(self.new_account().read("resume:backend")[0], base64.b64decode(pdf))
        self.assertEqual(request("/api/apply", {"jobs": ["1"]}, cookie=session)[0], 400)
        redirect = request("/auth/google")
        self.assertEqual(redirect[0], 303)
        self.assertIn("Secure; HttpOnly; SameSite=Lax", redirect[2]["Set-Cookie"])
        flow = redirect[2]["Set-Cookie"].split(";", 1)[0].split("=", 1)[1]
        callback = "/auth/google/callback?state=" + self.state(redirect[2]["Location"]) + "&code=fake"
        with patch.object(gmail, "exchange", return_value={"access_token": "access"}), patch.object(
                gmail, "google_identity", return_value={"email_verified": True, "email": self.account.email}):
            approved = request(callback, cookie={server.Handler.flow_cookie: flow})
        self.assertEqual(approved[0], 303)
        self.assertEqual(approved[2]["Location"], "/")
        saved = next(value for value in approved[2].get_all("Set-Cookie") if value.startswith(server.Handler.session_cookie))
        self.assertIn("Secure; HttpOnly; SameSite=Lax", saved)
        self.assertTrue(self.account.session(saved.split(";", 1)[0].split("=", 1)[1]))
        self.assertEqual(request("/api/account/logout", {}, cookie=session)[0], 200)
        self.assertEqual(request("/api/profile", cookie=session)[0], 401)


if __name__ == "__main__":
    unittest.main()
