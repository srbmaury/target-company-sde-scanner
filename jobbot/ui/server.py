"""Local dashboard for jobbot: `jobbot ui`.

Serves a single page on 127.0.0.1 that reads and updates the same tracker, profile
and logs as the command line. Every API call must carry the random token that is
embedded in the page at startup, and the Host header must be the local address, so
other websites open in your browser cannot use it.

Long tasks (scan, rank, Gmail sync) run as `python -m jobbot ...` subprocesses; the
page polls their output.
"""

import base64
import binascii
import datetime as dt
import errno
import json
import logging
import mimetypes
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import urllib.parse
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from .. import accounts, gmail, paths, profile as profile_mod, tracker
from pymongo import timeout as mongo_timeout
from pymongo.errors import PyMongoError
from . import bridge

LOGGER = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / "static"
TASKS = {}            # id -> {"cmd", "status", "lines", "started", "ended"}
TASK_LOCK = threading.Lock()
ALLOWED_TASKS = {     # name -> commands run one after another; a failure stops the rest
    "scan": [["scan", "--show-all"]],
    "rank": [["rank"]],
    "refresh": [["track", "sync-gmail", "--if-connected"], ["scan"], ["rank"]],
    "resumes": [["resumes"]],
    "sync-gmail": [["track", "sync-gmail"]],
    "gmail-login": [["gmail", "login"]],
}
JOB_TASKS = {"scan", "rank", "refresh"}   # these write the jobs table, so only one runs at a time


# --- data helpers ---------------------------------------------------------------

def _row(r):
    return {k: r[k] for k in r.keys()}


def _excluded_companies(conn):
    """preferences.exclude_companies, so the page can show which roles apply will skip."""
    try:
        return list(profile_mod.load(account=getattr(conn, "account", None)).get("preferences.exclude_companies") or [])
    except Exception:   # missing or invalid profile: nothing is excluded
        return []


def jobs_payload(conn, params):
    from ..apply.runner import excluded
    exclude = _excluded_companies(conn)
    include_applied = params.get("include_applied") == "1"
    include_dismissed = params.get("include_dismissed") == "1"
    rows = tracker.list_jobs(conn, include_applied=True, include_dismissed=include_dismissed, include_gone=True)
    match = tracker.job_matcher(conn)
    q = (params.get("q") or "").lower()
    min_fit = int(params["min_fit"]) if params.get("min_fit", "").isdigit() else None
    out = []
    for r in rows:
        if q and q not in f"{r['company']} {r['title']} {r['location']} {r['ats'] or ''}".lower():
            continue
        if min_fit is not None and (r["fit_score"] or 0) < min_fit:
            continue
        level, app = match(r)
        if level in ("exact", "likely") and not include_applied:
            continue
        item = {k: r[k] for k in ("n", "url", "company", "title", "location", "ats", "experience", "evidence",
                                  "posted", "first_seen", "fit_score", "fit_resume", "fit_reason", "dismissed",
                                  "not_duplicate")}
        item["applied"] = level
        item["excluded"] = excluded(r["company"], exclude)
        item["gone"] = bool(r["gone"])
        item["applied_note"] = (f"#{app['id']} {app['title']} ({app['status']}, {app['applied_on'] or 'date unknown'})"
                                if app else "")
        out.append(item)
    return out


def table_page(rows, params, columns, default_sort):
    """Bound the response after sorting the full filtered result."""
    column = params.get("sort", default_sort)
    if column not in columns:
        raise ValueError("Invalid sort column.")
    descending = params.get("direction", "desc") == "desc"
    def sort_key(row):
        value = row[column]
        return (value is not None, value or 0) if column in ("n", "id", "fit_score") else str(value or "").casefold()
    rows.sort(key=sort_key, reverse=descending)
    offset = max(0, int(params.get("offset", "0")))
    end = offset + 50
    return {"rows": rows[offset:end], "total": len(rows),
            "next_offset": end if end < len(rows) else None}


def jobs_page(rows, params):
    def view(job):
        if job["dismissed"]:
            return "dismissed"
        if job["applied"] in ("exact", "likely"):
            return "applied"
        if job["excluded"] and not job["gone"]:
            return "excluded"
        if job["applied"] == "possible":
            return "possible" if not job["gone"] else None
        return "gone" if job["gone"] else "new"

    counts = {"all": len(rows)}
    selected = params["view"]
    matching = []
    for job in rows:
        bucket = view(job)
        if bucket:
            counts[bucket] = counts.get(bucket, 0) + 1
        if selected == "all" or selected == bucket:
            matching.append(job)
    return {**table_page(matching, params, {"n", "fit_score", "company", "title", "location", "experience"},
                         "fit_score"), "counts": counts}


def _new_jobs(conn):
    """Roles you can apply to: not dismissed, not applied, not possibly applied, not at an excluded company."""
    from ..apply.runner import excluded
    match, exclude = tracker.job_matcher(conn), _excluded_companies(conn)
    return sum(1 for r in tracker.list_jobs(conn, include_applied=True)
               if not excluded(r["company"], exclude) and match(r)[0] is None)


def summary_payload(conn):
    stats = tracker.stats(conn)
    total = sum(stats.values())
    responded = sum(stats.get(k, 0) for k in ("assessment", "interview", "offer", "rejected"))
    return {
        "applications": stats, "total": total,
        "response_rate": round(100 * responded / total) if total else 0,
        "interview_rate": round(100 * (stats.get("interview", 0) + stats.get("offer", 0)) / total) if total else 0,
        "open_jobs": _new_jobs(conn),
    }


def workspace_payload(account):
    from .. import llm

    try:
        gmail_connected = account.get_json("gmail") is not None if account else gmail.is_connected()
    except (PyMongoError, accounts.AccountError, ValueError):
        gmail_connected = None
    return {
        "gmail": gmail_connected,
        "account": account is not None,
        "employer_password_configured": bool(os.getenv("JOBBOT_EMPLOYER_PASSWORD")),
        "llm_provider": llm.DEFAULT_PROVIDER,
        "llm_model": llm.OPENAI_MODEL if llm.DEFAULT_PROVIDER == "openai" else llm.DEFAULT_MODEL,
        "llm_available": llm.LLM.available(),
        "profile": str(paths.PROFILE),
        "statuses": list(tracker.STATUSES),
    }


DOCS = paths.REPO / "docs"


def docs_index():
    """Pages in docs/, in the order the docs index lists them."""
    order = re.findall(r"\]\(([\w-]+)\.md\)", (DOCS / "README.md").read_text(encoding="utf-8")) if (DOCS / "README.md").exists() else []
    names = order + sorted(p.stem for p in DOCS.glob("*.md") if p.stem not in order and p.stem != "README")
    pages = []
    for name in ["README"] + names:
        f = DOCS / f"{name}.md"
        if f.exists():
            title = re.search(r"^# (.+)$", f.read_text(encoding="utf-8"), re.M)
            text = title.group(1).replace("`", "") if title else name
            pages.append({"name": name, "title": "Overview" if name == "README" else text})
    return pages


def doc_page(name):
    """One docs page's Markdown. Only plain names of files directly in docs/ (no paths)."""
    if not re.fullmatch(r"[\w-]{1,40}", name or ""):
        return None
    f = (DOCS / f"{name}.md").resolve()
    if f.parent != DOCS.resolve() or not f.is_file():
        return None
    return {"name": name, "text": f.read_text(encoding="utf-8")}


def log_dates():
    logdir = paths.HOME / "logs"
    if not logdir.exists():
        return []
    return sorted((p.stem for p in logdir.glob("*.log")), reverse=True)


def start_task(name):
    if name not in ALLOWED_TASKS:
        raise ValueError("unknown task")
    with TASK_LOCK:
        for t in TASKS.values():
            if t["status"] == "running" and (t["name"] == name or {t["name"], name} <= JOB_TASKS
                                             or {t["name"], name} == {"refresh", "sync-gmail"}):
                raise ValueError(f"{t['name']} is already running")
        task_id = secrets.token_hex(4)
        TASKS[task_id] = {"id": task_id, "activity": {}, "name": name, "status": "running", "lines": [],
                          "step": None, "started": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "ended": None}

    def run():
        task = TASKS[task_id]
        try:
            for args in ALLOWED_TASKS[name]:
                task["step"] = args[0]
                task["lines"].append(f"$ jobbot {' '.join(args)}")
                proc = subprocess.Popen([sys.executable, "-m", "jobbot", *args], cwd=paths.REPO,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                        text=True, bufsize=1, env={**os.environ, "PYTHONUNBUFFERED": "1", "JOBBOT_ACTIVITY": "1"})
                for line in proc.stdout:
                    if line.startswith("JOBBOT_ACTIVITY "):
                        task["activity"] = {**task["activity"], args[0]: json.loads(line.removeprefix("JOBBOT_ACTIVITY "))}
                        continue
                    task["lines"].append(line.rstrip("\n"))
                    del task["lines"][:-500]
                if proc.wait() != 0:
                    task["status"] = "failed"
                    break
            else:
                task["status"] = "done"
        except Exception as e:  # report instead of dying silently
            task["lines"].append(f"error: {e}")
            task["status"] = "failed"
        task["ended"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    threading.Thread(target=run, daemon=True).start()
    return TASKS[task_id]


# --- HTTP -------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    token = ""
    port = 0
    account = None
    session_cookie = "__Host-jobbot-session"
    flow_cookie = "__Host-jobbot-flow"

    def log_message(self, *args):
        pass

    def _loopback_hosts(self):
        return (f"127.0.0.1:{self.port}", f"localhost:{self.port}")

    def _codespaces_proxy(self):
        return bool(self.account and os.getenv("CODESPACES") == "true"
                    and not os.getenv("RENDER_EXTERNAL_URL", "").strip())

    def _allowed_host(self):
        host = (self.headers.get("Host") or "").lower()
        if not self.account:
            return host in self._loopback_hosts()
        if host == urllib.parse.urlsplit(self.account.origin).netloc:
            return True
        # The Codespaces forwarder can replace Host with the loopback target.
        return self._codespaces_proxy() and host in (*self._loopback_hosts(), "localhost", "127.0.0.1")

    def _allowed_origin(self):
        origin = self.headers.get("Origin")
        if origin == self.account.origin:
            return True
        # Same-origin browser requests can arrive with a rewritten Origin.
        # The session cookie and custom CSRF header are still checked separately.
        return self._codespaces_proxy() and origin in {
            f"{scheme}://{host}" for scheme in ("http", "https") for host in self._loopback_hosts()
        }

    def _cookie(self, name):
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except CookieError:
            return ""
        return jar[name].value if name in jar else ""

    @staticmethod
    def _set_cookie(name, value, age):
        return ("Set-Cookie", f"{name}={value}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age={age}")

    def _session(self):
        return self._cookie(self.session_cookie)

    def _valid_token(self):
        return secrets.compare_digest(self.headers.get("X-Jobbot-Token", ""), self.token)

    def _auth_get(self, url):
        if url.path == "/auth/google":
            if self.account.session(self._session()):
                return self._redirect("/")
            target, browser = self.account.begin("login", self._session())
            return self._redirect(target, self._set_cookie(self.flow_cookie, browser, 600))
        if url.path == "/auth/google/callback":
            query = urllib.parse.parse_qs(url.query)
            get = lambda name: query.get(name, [""])[0]
            try:
                token = self.account.finish(get("state"), self._cookie(self.flow_cookie), get("code"), self._session())
            except (accounts.AccountError, gmail.GmailError, OSError, ValueError, KeyError):
                return self._static("/auth-error.html", status=400,
                                    headers=[self._set_cookie(self.flow_cookie, "", 0)])
            headers = [self._set_cookie(self.flow_cookie, "", 0)]
            if token:
                headers.append(self._set_cookie(self.session_cookie, token, 7 * 86400))
            return self._redirect("/", *headers)
        return self._send(404, {"error": "not found"})

    def _redirect(self, url, *headers):
        return self._send(303, b"", "text/plain", [("Location", url), *headers])

    def _account_post(self, parts, body):
        if parts == ["account", "logout"]:
            self.account.logout(self._session())
            return self._send(200, {"ok": True}, headers=[self._set_cookie(self.session_cookie, "", 0)])
        if parts == ["account", "gmail", "connect"]:
            target, browser = self.account.begin("gmail", self._session())
            return self._send(200, {"url": target}, headers=[self._set_cookie(self.flow_cookie, browser, 600)])
        if parts == ["account", "gmail", "disconnect"]:
            try:
                gmail.logout()
            except gmail.GmailError as exc:
                return self._send(409, {"error": str(exc)})
            return self._send(200, {"ok": True})
        if parts == ["account", "resume", "copy"]:
            source, key = body.get("source"), body.get("key")
            if not all(profile_mod.valid_resume_key(value) for value in (source, key)):
                return self._send(400, {"error": "Use a resume key of 1–48 letters, numbers, underscores or dashes."})
            data, _ = self.account.read("resume:" + source)
            if data is None:
                return self._send(404, {"error": "That uploaded PDF was not found."})
            self.account.write("resume:" + key, data, expected="", label=self._resume_name(body))
            return self._send(200, {"ok": True})
        if parts == ["account", "resume", "delete"]:
            return self._delete_resume(body)
        if parts == ["account", "resume", "profile"]:
            if body.get("action") == "delete":
                return self._send(400, {"error": "Use the confirmed PDF deletion action."})
            return self._edit_resume_profile(body)
        if parts == ["account", "resume"]:
            key = body.get("key")
            if not profile_mod.valid_resume_key(key):
                return self._send(400, {"error": "Use a resume key of 1–48 letters, numbers, underscores or dashes."})
            try:
                data = base64.b64decode(body.get("pdf", ""), validate=True)
            except (ValueError, TypeError, binascii.Error):
                return self._send(400, {"error": "Invalid PDF upload."})
            if not data.startswith(b"%PDF-") or len(data) > accounts.MAX_PDF:
                return self._send(400, {"error": "Select a PDF no larger than 5 MiB."})
            name = self._resume_name(body)
            version = body.get("replace_version", "")
            if not isinstance(version, str):
                raise ValueError("Refresh the resume library before replacing a PDF.")
            existing = next((row for row in self.account.resume_entries() if row["key"] == key), None)
            if existing and existing["version"] != version:
                return self._send(409, {"error": "That key already has a PDF. Refresh the library before replacing it."})
            self.account.write("resume:" + key, data, expected=version, label=name)
            if body.get("use_for_ranking") is True:
                raw, current_version = self.account.read("profile")
                if current_version != body.get("mtime"):
                    return self._send(200, {"warning": "PDF uploaded. Profile changed, so reload before enabling ranking."})
                config = yaml.safe_load(profile_mod.ACCOUNT_PROFILE if raw is None else raw)
                if isinstance(config, dict) and isinstance(config.get("resumes"), dict) and key in config["resumes"]:
                    return self._send(200, {"ok": True})
                return self._edit_resume_profile({"key": key, "action": "add", "mtime": current_version}, uploaded=True)
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})


    @staticmethod
    def _resume_name(body):
        value = body.get("name", "")
        if not isinstance(value, str) or len(value.strip()) > 80 or any(ord(c) < 32 for c in value):
            raise ValueError("Use a display name up to 80 characters.")
        return value.strip()

    def _edit_resume_profile(self, body, uploaded=False):
        from io import StringIO

        from ruamel.yaml import YAML
        from ruamel.yaml.error import YAMLError

        key, action, expected = body.get("key"), body.get("action"), body.get("mtime")
        target = body.get("target")
        if (not profile_mod.valid_resume_key(key) or action not in ("add", "remove", "rename", "delete")
                or not isinstance(expected, str) or (action == "rename" and (
                    not profile_mod.valid_resume_key(target)))):
            return self._send(400, {"error": "Invalid resume profile change."})
        name = self._resume_name(body)
        if action == "rename" and target == key:
            pdf, pdf_version = self.account.read("resume:" + key)
            if pdf is None:
                return self._send(404, {"error": "That uploaded PDF was not found."})
            self.account.write("resume:" + key, pdf, expected=pdf_version, label=name)
            return self._send(200, {"ok": True})
        raw, version = self.account.read("profile")
        if expected != version:
            return self._send(409, {"error": "Profile changed. Reload it before editing resume keys."})
        editor = YAML()
        editor.preserve_quotes = True
        try:
            data = editor.load((profile_mod.ACCOUNT_PROFILE if raw is None else raw).decode())
            if not isinstance(data, dict) or "personal" not in data:
                raise ValueError()
            resumes = data.get("resumes")
            if resumes is None:
                resumes = data["resumes"] = {}
            if not isinstance(resumes, dict):
                raise ValueError()
            if action == "rename":
                if target in resumes:
                    return self._send(409, {"error": "That key is already in the profile."})
                pdf, pdf_version = self.account.read("resume:" + key)
                if pdf is None:
                    return self._send(404, {"error": "That uploaded PDF was not found."})
                if key in resumes:
                    # Retain the existing focus, comments, and position of the YAML entry.
                    position = list(resumes).index(key)
                    entry = resumes.pop(key)
                    comment = resumes.ca.items.pop(key, None)
                    resumes.insert(position, target, entry)
                    if comment is not None:
                        resumes.ca.items[target] = comment
            elif action == "add" and key not in resumes:
                if key not in self.account.resume_keys():
                    return self._send(404, {"error": "Upload a PDF under that key first."})
                resumes[key] = {"focus": ""}
            elif action in ("remove", "delete") and key in resumes:
                del resumes[key]
            elif action == "delete":
                pass
            else:
                return self._send(409, {"error": "That key is already in the requested state. Reload Profile."})
            out = StringIO()
            editor.dump(data, out)
            text = out.getvalue()
            if len(text.encode()) > 2_000_000:
                raise ValueError()
        except (YAMLError, ValueError):
            if uploaded:
                return self._send(200, {"warning": "PDF uploaded. Save a valid profile before enabling ranking."})
            return self._send(400, {"error": "Edit and save a valid profile with a resumes mapping first."})
        if action == "rename":
            # Copy first so a failed profile write never loses the original. If the final
            # cleanup fails, leave both uploads intact instead of removing a newer PDF.
            if "name" not in body:
                name = next((row["name"] for row in self.account.resume_entries() if row["key"] == key), "")
            try:
                self.account.write("resume:" + target, pdf, expected="", label=name)
            except accounts.AccountError:
                return self._send(409, {"error": "That key already has an uploaded PDF."})
            try:
                version = self.account.write("profile", text.encode(), expected=version)
            except accounts.AccountError:
                return self._send(409, {"error": "Profile changed. Both PDFs were kept. Reload Profile."})
            warning = None
            try:
                if not self.account.remove("resume:" + key, expected=pdf_version):
                    warning = "The original upload changed and was kept."
            except PyMongoError:
                warning = "Could not confirm removal of the original upload. Refresh the list."
        else:
            try:
                version = self.account.write("profile", text.encode(), expected=version)
            except accounts.AccountError:
                if not uploaded:
                    raise
                return self._send(200, {"warning": "PDF uploaded. Reload Profile before enabling ranking."})
            warning = None
        if action == "delete":
            try:
                if not self.account.remove("resume:" + key, expected=body["pdf_version"]):
                    warning = "Removed from ranking, but the upload changed and was kept."
            except PyMongoError:
                warning = "Removed from ranking. Could not confirm PDF deletion. Refresh the list."
        return self._send(200, {"text": text, "mtime": version, "warning": warning,
                                "resume_keys": [key for key in resumes if profile_mod.valid_resume_key(key)]})

    def _delete_resume(self, body):
        key = body.get("key")
        if not profile_mod.valid_resume_key(key) or body.get("confirm") is not True:
            return self._send(400, {"error": "Confirm deletion of a valid resume key."})
        raw, version = self.account.read("profile")
        if body.get("mtime") != version:
            return self._send(409, {"error": "Profile changed. Reload it before deleting an upload."})
        data = yaml.safe_load(profile_mod.ACCOUNT_PROFILE if raw is None else raw)
        resumes = data.get("resumes") if isinstance(data, dict) else None
        if resumes is not None and not isinstance(resumes, dict):
            return self._send(400, {"error": "Save a valid resumes mapping before deleting uploads."})
        linked = bool(resumes and key in resumes)
        if linked and body.get("remove_from_ranking") is not True:
            return self._send(409, {"error": "Confirm removing this resume from ranking as well."})
        _, pdf_version = self.account.read("resume:" + key)
        if not pdf_version:
            return self._send(404, {"error": "That uploaded PDF was not found."})
        if body.get("version", pdf_version) != pdf_version:
            return self._send(409, {"error": "The upload changed. Reload Profile and try again."})
        if linked:
            return self._edit_resume_profile({"key": key, "action": "delete", "mtime": version,
                                              "pdf_version": pdf_version})
        if not self.account.remove("resume:" + key, expected=pdf_version):
            return self._send(409, {"error": "The upload changed. Reload Profile and try again."})
        return self._send(200, {"ok": True})

    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=(), frameable=False):
        data = body if isinstance(body, bytes) else (json.dumps(body, default=str) if ctype.startswith("application/json")
                                                    else body).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for name, value in headers:
                self.send_header(name, value)
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
                             + ("frame-ancestors 'self'; script-src 'none'; " if frameable else "frame-ancestors 'none'; ")
                             + "base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            # The browser or forwarding proxy closed the response while we were writing it.
            self.close_connection = True

    def _json_body(self, limit=2_000_000):
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 <= length <= limit:
            raise ValueError("request too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def _storage_error(self, stage, exc):
        LOGGER.warning("Dashboard storage failure during %s (%s)", stage, type(exc).__name__)
        if isinstance(exc, accounts.AccountError):
            message = str(exc)
        elif isinstance(exc, PyMongoError) and exc.timeout:
            message = f"MongoDB timed out during {stage}."
        elif isinstance(exc, sqlite3.DatabaseError):
            message = "The stored tracker could not be opened as a SQLite database."
        else:
            message = f"MongoDB failed during {stage} ({type(exc).__name__})."
        return self._send(503, {"error": message})

    def do_GET(self):
        try:
            return self._get()
        except (PyMongoError, accounts.AccountError) as exc:
            return self._storage_error("dashboard read", exc)
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})

    def _get(self):
        if not self._allowed_host():
            return self._send(403, {"error": "forbidden host"})
        url = urllib.parse.urlparse(self.path)
        if self.account and url.path.startswith("/auth/"):
            with mongo_timeout(8):
                return self._auth_get(url)
        try:
            with mongo_timeout(5):
                signed_in = not self.account or self.account.session(self._session())
        except (PyMongoError, accounts.AccountError) as exc:
            return self._storage_error("session lookup", exc)
        if not signed_in:
            if url.path in ("/", "/index.html"):
                expired = urllib.parse.parse_qs(url.query).get("session") == ["expired"]
                return self._static("/login.html", expired=expired)
            if url.path in ("/style.css", "/favicon.svg"):
                return self._static(url.path)
            return self._send(401, {"error": "Sign in to Jobbot."})
        tracker_read = url.path in ("/api/jobs", "/api/applications", "/api/summary") or url.path.startswith(
            "/api/applications/")
        with mongo_timeout(20 if tracker_read else 8):
            return self._get_authenticated(url)

    def _get_authenticated(self, url):
        if self.account and url.path.startswith("/resume-file/"):
            key = url.path.removeprefix("/resume-file/")
            if not profile_mod.valid_resume_key(key):
                return self._send(404, {"error": "Resume not found."})
            data, _ = self.account.read("resume:" + key)
            if data is None:
                return self._send(404, {"error": "Resume not found."})
            mode = "attachment" if url.query == "download=1" else "inline"
            return self._send(200, data, "application/pdf",
                              [("Content-Disposition", f'{mode}; filename="{key}.pdf"')], frameable=True)
        if not url.path.startswith("/api/"):
            return self._static(url.path)
        if not self._valid_token():
            return self._send(403, {"error": "missing or wrong token"})
        params = {k: v[0] for k, v in urllib.parse.parse_qs(url.query, keep_blank_values=True).items()}
        parts = url.path.strip("/").split("/")[1:]
        if self.account and len(parts) == 4 and parts[:3] == ["account", "resume", "pdf"]:
            key = parts[3]
            if not profile_mod.valid_resume_key(key):
                return self._send(404, {"error": "Resume not found."})
            data, _ = self.account.read("resume:" + key)
            if data is None:
                return self._send(404, {"error": "Resume not found."})
            return self._send(200, data, "application/pdf", [("Content-Disposition", f'inline; filename="{key}.pdf"')])
        if self.account and parts == ["account", "resumes"]:
            return self._send(200, {"keys": self.account.resume_keys(), "resumes": self.account.resume_entries()})
        if self.account and parts == ["profile"]:
            raw, version = self.account.read("profile")
            if raw is None:
                raw = profile_mod.ACCOUNT_PROFILE
            data = yaml.safe_load(raw)
            resumes = data.get("resumes") if isinstance(data, dict) else None
            return self._send(200, {"path": "MongoDB account profile", "text": raw.decode(), "mtime": version,
                                    "resume_keys": [key for key in resumes if profile_mod.valid_resume_key(key)]
                                    if isinstance(resumes, dict) else []})
        if self.account and parts == ["logs"]:
            return self._send(200, {"dates": [], "date": "", "lines": []})
        if parts == ["docs"]:
            return self._send(200, docs_index())
        if len(parts) == 2 and parts[0] == "docs":
            page = doc_page(parts[1])
            return self._send(200, page) if page else self._send(404, {"error": "no such page"})
        if parts == ["logs"]:
            dates = log_dates()
            day = params.get("date") or (dates[0] if dates else "")
            path = paths.HOME / "logs" / f"{day}.log"
            text = path.read_text(encoding="utf-8") if day and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) \
                and path.exists() else ""
            return self._send(200, {"dates": dates, "date": day, "lines": text.splitlines()[-2000:]})
        if parts == ["profile"]:
            path = paths.PROFILE
            return self._send(200, {"path": str(path), "text": path.read_text(encoding="utf-8") if path.exists() else "",
                                    "mtime": str(path.stat().st_mtime_ns) if path.exists() else ""})
        if parts == ["tasks"]:
            return self._send(200, sorted(TASKS.copy().values(), key=lambda t: (t["status"] == "running", t["started"]), reverse=True)[:20])
        if parts == ["workspace"]:
            return self._send(200, workspace_payload(self.account))
        if parts == ["apply"]:
            run = bridge.current(self.account)
            if run:
                return self._send(200, run.snapshot())
            if params.get("live") == "1":
                return self._send(200, {"status": "idle"})
            last = bridge.latest_saved_run(self.account)
            return self._send(200, {**last, "history": True} if last else {"status": "idle"})
        if parts == ["runs"]:
            return self._send(200, bridge.history(self.account))
        if len(parts) == 2 and parts[0] == "runs":
            saved = bridge.saved_run(parts[1], self.account)
            return self._send(200, {**saved, "history": True}) if saved else self._send(404, {"error": "no such run"})
        if len(parts) == 2 and parts[0] == "tasks":
            task = TASKS.get(parts[1])
            return self._send(200, task) if task else self._send(404, {"error": "no such task"})
        if parts not in (["summary"], ["jobs"], ["applications"]) and not (
            len(parts) == 2 and parts[0] == "applications" and parts[1].isdigit()
        ):
            return self._send(404, {"error": "not found"})
        try:
            conn = tracker.connect(account=self.account, cached_snapshot=True,
                                   allow_stale=(parts == ["jobs"] and "view" in params)
                                   or (parts == ["applications"] and params.get("page") == "1"))
        except (PyMongoError, accounts.AccountError, sqlite3.DatabaseError) as exc:
            return self._storage_error("tracker read", exc)
        try:
            stale = getattr(conn, "stale", False)
            version = getattr(conn, "version", None)
            if "version" in params and params["version"] != version:
                return self._send(409, {"error": "The tracker changed. Refresh the list to continue."})
            if stale:
                LOGGER.warning("Dashboard is serving a cached tracker after a MongoDB timeout")
            if parts == ["summary"]:
                counts = summary_payload(conn)
                return self._send(200, counts if params.get("counts") == "1"
                                  else {**counts, **workspace_payload(self.account)})
            if parts == ["jobs"]:
                rows = jobs_payload(conn, params)
                if "view" in params:
                    rows = jobs_page(rows, params)
                    rows["version"] = version
                    if stale:
                        rows["stale"] = True
                return self._send(200, rows)
            if parts == ["applications"]:
                rows = tracker.list_applications(conn, status=params.get("status") or None,
                                                 company=params.get("q") or None)
                rows = [_row(r) for r in rows]
                if params.get("page") == "1":
                    rows = table_page(rows, params, {"id", "company", "title", "status", "resume", "applied_on",
                                                    "updated_on", "source"}, "applied_on")
                    rows["version"] = version
                    if stale:
                        rows["stale"] = True
                return self._send(200, rows)
            if len(parts) == 2 and parts[0] == "applications" and parts[1].isdigit():
                app = tracker.find_application(conn, parts[1])
                if not app:
                    return self._send(404, {"error": "no such application"})
                return self._send(200, {**_row(app), "events": [_row(e) for e in tracker.events_for(conn, app["id"])]})
            return self._send(404, {"error": "not found"})
        finally:
            conn.close()

    def do_POST(self):
        try:
            with mongo_timeout(8):
                return self._post()
        except accounts.AccountError as exc:
            return self._send(409, {"error": str(exc)})
        except PyMongoError:
            return self._send(503, {"error": "Account storage is unavailable. Try again shortly."})
        except (KeyError, ValueError, yaml.YAMLError) as exc:
            return self._send(400, {"error": str(exc)})

    def _post(self):
        if not self._allowed_host():
            return self._send(403, {"error": "forbidden host"})
        if self.account and not self.account.session(self._session()):
            return self._send(401, {"error": "Sign in to Jobbot."})
        if not self._valid_token() or (self.account and not self._allowed_origin()):
            return self._send(403, {"error": "missing or wrong token"})
        parts = urllib.parse.urlparse(self.path).path.strip("/").split("/")[1:]
        if self.account and parts[:1] == ["account"]:
            return self._account_post(parts, self._json_body(7_000_000 if parts == ["account", "resume"] else 2_000_000))
        if self.account and parts == ["tasks", "gmail-login"]:
            return self._send(400, {"error": "Connect Gmail from the Actions tab."})
        if len(parts) == 3 and parts[0] == "runs" and parts[2] == "delete":
            self._json_body()
            if bridge.delete_run(parts[1], self.account):
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "Run history entry not found."})
        if parts == ["apply", "preview"]:
            run = bridge.current(self.account) if self.account else None
            if not run:
                return self._send(404, {"error": "No hosted browser run."})
            return self._send(200, run.control(self._json_body(48_000)))
        body = self._json_body()
        if parts == ["profile"]:
            text = body.get("text", "")
            data = yaml.safe_load(text)   # refuse to save YAML that does not parse
            if not isinstance(data, dict) or "personal" not in data:
                return self._send(400, {"error": "The profile must be a YAML mapping with a `personal` section."})
            try:
                profile_mod.Profile(data, paths.PROFILE).scan_experience()
            except profile_mod.ProfileError as exc:
                return self._send(400, {"error": str(exc)})
            if self.account:
                if not isinstance(body.get("mtime"), str):
                    return self._send(400, {"error": "Reload the account profile before saving."})
                version = self.account.write("profile", text.encode(), expected=body["mtime"])
                resumes = data.get("resumes")
                return self._send(200, {"ok": True, "mtime": version,
                                        "resume_keys": [key for key in resumes if profile_mod.valid_resume_key(key)]
                                        if isinstance(resumes, dict) else []})
            if paths.PROFILE.exists() and body.get("mtime") and str(body["mtime"]) != str(paths.PROFILE.stat().st_mtime_ns):
                # e.g. an apply run saved a learned answer since you opened the page: don't overwrite it.
                # (sent as a string: nanosecond timestamps are too large for JavaScript numbers)
                return self._send(409, {"error": "profile.yaml changed on disk since you opened it (an apply run may "
                                                 "have saved a learned answer). Copy your edits, reload, and save again."})
            if paths.PROFILE.exists():
                shutil.copy(paths.PROFILE, paths.PROFILE.with_suffix(".yaml.bak"))
            paths.PROFILE.write_text(text, encoding="utf-8")
            os.chmod(paths.PROFILE, 0o600)
            return self._send(200, {"ok": True, "mtime": str(paths.PROFILE.stat().st_mtime_ns)})
        if len(parts) == 2 and parts[0] == "tasks":
            return self._send(200, start_task(parts[1]))
        if parts == ["apply"]:
            keys = [str(k) for k in body.get("jobs", []) if str(k).strip()]
            if not keys:
                return self._send(400, {"error": "Choose at least one role."})
            run = bridge.start(keys, dry_run=bool(body.get("dry_run")), auto_next=body.get("auto_next", True),
                               resume=body.get("resume") or None, use_llm=body.get("llm", True) is not False,
                               force=bool(body.get("force")), unattended=bool(body.get("unattended")),
                               validation=bool(body.get("validation")), auto_submit=bool(body.get("auto_submit")),
                               account=self.account)
            return self._send(200, run.snapshot())
        if parts == ["apply", "answer"]:
            run = bridge.current(self.account)
            if not run:
                return self._send(400, {"error": "No apply run."})
            run.answer(body.get("prompt_id"), body.get("value"))
            return self._send(200, {"ok": True})
        if parts == ["apply", "stop"]:
            run = bridge.current(self.account)
            if run:
                run.stop()
            return self._send(200, {"ok": True})
        if parts[:1] not in (["jobs"], ["applications"]):
            return self._send(404, {"error": "not found"})
        conn = tracker.connect(account=self.account)
        try:
            if len(parts) == 3 and parts[0] == "jobs" and parts[2] in ("not-duplicate", "maybe-duplicate"):
                job = tracker.set_not_duplicate(conn, parts[1], parts[2] == "not-duplicate")
                return self._send(200, {"ok": True}) if job else self._send(404, {"error": "no such job"})
            if len(parts) == 3 and parts[0] == "jobs" and parts[2] in ("dismiss", "restore"):
                job = tracker.get_job(conn, parts[1])
                if not job:
                    return self._send(404, {"error": "no such job"})
                conn.execute("UPDATE jobs SET dismissed = ? WHERE url = ?", (1 if parts[2] == "dismiss" else 0, job["url"]))
                conn.commit()
                return self._send(200, {"ok": True})
            if parts == ["applications"]:
                if not (body.get("company") or "").strip() or not (body.get("title") or "").strip():
                    return self._send(400, {"error": "Enter both the company and the role title."})
                app = tracker.add_application(conn, body["company"].strip(), body["title"].strip(),
                                              url=(body.get("url") or "").strip() or None,
                                              location=body.get("location") or None,
                                              status=body.get("status") or "applied", source="dashboard",
                                              applied_on=body.get("applied_on") or None, notes=body.get("note") or None)
                return self._send(200, _row(app))
            if len(parts) == 3 and parts[0] == "applications" and parts[2] == "status":
                app = tracker.update_status(conn, parts[1], body["status"], body.get("note") or None)
                return self._send(200, _row(app))
            if len(parts) == 3 and parts[0] == "applications" and parts[2] == "edit":
                app = tracker.edit_application(conn, parts[1], company=body.get("company"), title=body.get("title"),
                                               url=body.get("url"))
                return self._send(200, _row(app)) if app else self._send(404, {"error": "no such application"})
            if len(parts) == 3 and parts[0] == "applications" and parts[2] == "note":
                app = tracker.find_application(conn, parts[1])
                if not app:
                    return self._send(404, {"error": "no such application"})
                note = (body.get("note") or "").strip()
                conn.execute("UPDATE applications SET notes = ?, updated_on = ? WHERE id = ?",
                             (note, tracker.now(), app["id"]))
                conn.execute("INSERT INTO events (application_id, at, status, note) VALUES (?,?,?,?)",
                             (app["id"], tracker.now(), app["status"], f"note: {note[:200]}"))
                conn.commit()
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})
        finally:
            conn.close()

    def _static(self, path, *, status=200, headers=(), expired=False):
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        file = (STATIC / name).resolve()
        if STATIC not in file.parents or not file.is_file():
            return self._send(404, "not found", "text/plain; charset=utf-8")
        body = file.read_bytes()
        if name == "index.html":
            body = body.replace(b"__JOBBOT_TOKEN__", self.token.encode())
        if name == "login.html" and expired:
            body = body.replace(b"Sign in to Jobbot", b"Sign in to Jobbot again").replace(
                b"Use the Google account configured for this dashboard.",
                b"Your Jobbot session expired. Sign in to return to the dashboard.")
        ctype = mimetypes.guess_type(str(file))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        return self._send(status, body, ctype, headers)


def make_server(port=0, account=None, bind="127.0.0.1"):
    if not account and bind != "127.0.0.1":
        raise ValueError("Non-local dashboard binding requires hosted account mode.")
    handler = type("JobbotHandler", (Handler,), {"token": secrets.token_urlsafe(24), "account": account})
    server = ThreadingHTTPServer((bind, port), handler)
    handler.port = server.server_port
    return server


def serve(port=8765):
    if not accounts.enabled():
        raise accounts.AccountError(
            "The dashboard requires a hosted account. Set JOBBOT_MONGODB_URI and the account settings "
            "in .env or the deployment environment. See docs/accounts.md.")
    paths.ensure_home()
    account = accounts.current(port)
    account.initialize()
    try:
        server = make_server(port, account, os.getenv("JOBBOT_BIND", "127.0.0.1"))
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        raise accounts.AccountError(
            f"Port {port} is already in use. Stop the existing dashboard and try again.") from exc
    print(f"jobbot account dashboard: {account.origin} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
