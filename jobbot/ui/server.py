"""Local dashboard for jobbot: `jobbot ui`.

Serves a single page on 127.0.0.1 that reads and updates the same tracker, profile
and logs as the command line. Every API call must carry the random token that is
embedded in the page at startup, and the Host header must be the local address, so
other websites open in your browser cannot use it.

Long tasks (scan, rank, Gmail sync) run as `python -m jobbot ...` subprocesses; the
page polls their output.
"""

import datetime as dt
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from .. import paths, tracker
from . import bridge

STATIC = Path(__file__).resolve().parent / "static"
TASKS = {}            # id -> {"cmd", "status", "lines", "started", "ended"}
TASK_LOCK = threading.Lock()
ALLOWED_TASKS = {     # name -> commands run one after another; a failure stops the rest
    "scan": [["scan", "--show-all"]],
    "rank": [["rank"]],
    "refresh": [["scan"], ["rank"]],
    "sync-gmail": [["track", "sync-gmail"]],
    "gmail-login": [["gmail", "login"]],
}
JOB_TASKS = {"scan", "rank", "refresh"}   # these write the jobs table, so only one runs at a time


# --- data helpers ---------------------------------------------------------------

def _row(r):
    return {k: r[k] for k in r.keys()}


def jobs_payload(conn, params):
    include_applied = params.get("include_applied") == "1"
    include_dismissed = params.get("include_dismissed") == "1"
    rows = tracker.list_jobs(conn, include_applied=True, include_dismissed=include_dismissed)
    apps = conn.execute("SELECT * FROM applications").fetchall()
    q = (params.get("q") or "").lower()
    min_fit = int(params["min_fit"]) if params.get("min_fit", "").isdigit() else None
    out = []
    for r in rows:
        level, app = tracker.applied_match(conn, r["url"], r["company"], r["title"], _apps=apps,
                                           first_seen=r["first_seen"], posted=r["posted"])
        if level in ("exact", "likely") and not include_applied:
            continue
        if q and q not in f"{r['company']} {r['title']} {r['location']}".lower():
            continue
        if min_fit is not None and (r["fit_score"] or 0) < min_fit:
            continue
        item = {k: r[k] for k in ("n", "url", "company", "title", "location", "ats", "experience", "evidence",
                                  "posted", "first_seen", "fit_score", "fit_resume", "fit_reason", "dismissed")}
        item["applied"] = level
        item["applied_note"] = (f"#{app['id']} {app['title']} ({app['status']}, {app['applied_on'] or 'date unknown'})"
                                if app else "")
        out.append(item)
    return out


def summary_payload(conn):
    from .. import gmail, llm

    stats = tracker.stats(conn)
    total = sum(stats.values())
    responded = sum(stats.get(k, 0) for k in ("assessment", "interview", "offer", "rejected"))
    return {
        "applications": stats, "total": total,
        "response_rate": round(100 * responded / total) if total else 0,
        "interview_rate": round(100 * (stats.get("interview", 0) + stats.get("offer", 0)) / total) if total else 0,
        "open_jobs": len(tracker.list_jobs(conn)),
        "gmail": gmail.is_connected(),
        "ollama": llm.LLM.available(),
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
            if t["status"] == "running" and (t["name"] == name or {t["name"], name} <= JOB_TASKS):
                raise ValueError(f"{t['name']} is already running")
        task_id = secrets.token_hex(4)
        TASKS[task_id] = {"id": task_id, "name": name, "status": "running", "lines": [],
                          "step": None, "started": dt.datetime.now().isoformat(timespec="seconds"), "ended": None}

    def run():
        task = TASKS[task_id]
        try:
            for args in ALLOWED_TASKS[name]:
                task["step"] = args[0]
                task["lines"].append(f"$ jobbot {' '.join(args)}")
                proc = subprocess.Popen([sys.executable, "-m", "jobbot", *args], cwd=paths.REPO,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                        text=True, bufsize=1, env={**os.environ, "PYTHONUNBUFFERED": "1"})
                for line in proc.stdout:
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
        task["ended"] = dt.datetime.now().isoformat(timespec="seconds")

    threading.Thread(target=run, daemon=True).start()
    return TASKS[task_id]


# --- HTTP -------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    token = ""
    port = 0

    def log_message(self, *args):
        pass

    # security: only our page, only on localhost
    def _allowed_host(self):
        host = (self.headers.get("Host") or "").lower()
        return host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}")

    def _authorized(self):
        return self._allowed_host() and secrets.compare_digest(self.headers.get("X-Jobbot-Token", ""), self.token)

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else (json.dumps(body, default=str) if ctype.startswith("application/json")
                                                    else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'")
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > 2_000_000:
            raise ValueError("request too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if not self._allowed_host():
            return self._send(403, {"error": "forbidden host"})
        url = urllib.parse.urlparse(self.path)
        if not url.path.startswith("/api/"):
            return self._static(url.path)
        if not self._authorized():
            return self._send(403, {"error": "missing or wrong token"})
        params = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        conn = tracker.connect()
        try:
            parts = url.path.strip("/").split("/")[1:]
            if parts == ["summary"]:
                return self._send(200, summary_payload(conn))
            if parts == ["jobs"]:
                return self._send(200, jobs_payload(conn, params))
            if parts == ["applications"]:
                rows = tracker.list_applications(conn, status=params.get("status") or None,
                                                 company=params.get("q") or None)
                return self._send(200, [_row(r) for r in rows])
            if len(parts) == 2 and parts[0] == "applications" and parts[1].isdigit():
                app = tracker.find_application(conn, parts[1])
                if not app:
                    return self._send(404, {"error": "no such application"})
                return self._send(200, {**_row(app), "events": [_row(e) for e in tracker.events_for(conn, app["id"])]})
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
                return self._send(200, sorted(TASKS.values(), key=lambda t: t["started"], reverse=True)[:20])
            if parts == ["apply"]:
                run = bridge.current()
                if run:
                    return self._send(200, run.snapshot())
                last = bridge.history()
                return self._send(200, {**bridge.saved_run(last[0]["id"]), "history": True} if last else {"status": "idle"})
            if parts == ["runs"]:
                return self._send(200, bridge.history())
            if len(parts) == 2 and parts[0] == "runs":
                saved = bridge.saved_run(parts[1])
                return self._send(200, {**saved, "history": True}) if saved else self._send(404, {"error": "no such run"})
            if len(parts) == 2 and parts[0] == "tasks":
                task = TASKS.get(parts[1])
                return self._send(200, task) if task else self._send(404, {"error": "no such task"})
            return self._send(404, {"error": "not found"})
        finally:
            conn.close()

    def do_POST(self):
        if not self._authorized():
            return self._send(403, {"error": "missing or wrong token"})
        parts = urllib.parse.urlparse(self.path).path.strip("/").split("/")[1:]
        conn = tracker.connect()
        try:
            body = self._json_body()
            if len(parts) == 3 and parts[0] == "jobs" and parts[2] in ("dismiss", "restore"):
                job = tracker.get_job(conn, parts[1])
                if not job:
                    return self._send(404, {"error": "no such job"})
                conn.execute("UPDATE jobs SET dismissed = ? WHERE url = ?", (1 if parts[2] == "dismiss" else 0, job["url"]))
                conn.commit()
                return self._send(200, {"ok": True})
            if parts == ["applications"]:
                app = tracker.add_application(conn, body["company"].strip(), body["title"].strip(),
                                              url=(body.get("url") or "").strip() or None,
                                              location=body.get("location") or None,
                                              status=body.get("status") or "applied", source="dashboard",
                                              applied_on=body.get("applied_on") or None, notes=body.get("note") or None)
                return self._send(200, _row(app))
            if len(parts) == 3 and parts[0] == "applications" and parts[2] == "status":
                app = tracker.update_status(conn, parts[1], body["status"], body.get("note") or None)
                return self._send(200, _row(app))
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
            if parts == ["profile"]:
                text = body.get("text", "")
                data = yaml.safe_load(text)   # refuse to save YAML that does not parse
                if not isinstance(data, dict) or "personal" not in data:
                    return self._send(400, {"error": "The profile must be a YAML mapping with a `personal` section."})
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
                                   force=bool(body.get("force")), unattended=bool(body.get("unattended")))
                return self._send(200, run.snapshot())
            if parts == ["apply", "answer"]:
                run = bridge.current()
                if not run:
                    return self._send(400, {"error": "No apply run."})
                run.answer(body.get("prompt_id"), body.get("value"))
                return self._send(200, {"ok": True})
            if parts == ["apply", "stop"]:
                run = bridge.current()
                if run:
                    run.stop()
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})
        except (KeyError, ValueError, yaml.YAMLError) as e:
            return self._send(400, {"error": str(e)})
        finally:
            conn.close()

    def _static(self, path):
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        file = (STATIC / name).resolve()
        if STATIC not in file.parents or not file.is_file():
            return self._send(404, "not found", "text/plain; charset=utf-8")
        body = file.read_bytes()
        if name == "index.html":
            body = body.replace(b"__JOBBOT_TOKEN__", self.token.encode())
        ctype = mimetypes.guess_type(str(file))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        return self._send(200, body, ctype)


def make_server(port=0):
    handler = type("JobbotHandler", (Handler,), {"token": secrets.token_urlsafe(24)})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    handler.port = server.server_port
    return server


def serve(port=8765, open_browser=True):
    paths.ensure_home()
    try:
        server = make_server(port)
    except OSError:
        server = make_server(0)   # the preferred port is busy; take any free one
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"jobbot dashboard: {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
