"""Run `apply` inside the dashboard.

The engine talks to a UI object (info, warn, ask, confirm, ask_code, wait_for_user,
report, next_action). WebUI implements the same interface, but each question becomes
a pending prompt that the page shows; the engine's thread waits until the page answers.
Only one apply run at a time, because jobbot's browser profile can be open only once.
"""

import datetime as dt
import json
import re
import pathlib
import secrets
import threading
import time
import traceback

from .. import llm as llm_mod
from .. import paths
from .. import profile as profile_mod
from .. import tracker

MAX_EVENTS = 1500
SAVE_LOCK = threading.Lock()
LOADED_AT = time.time()


def code_changed():
    """True when the dashboard's own code changed after this server loaded it. Form-filling code
    (apply/hot.py MODULES) is reloaded by the run itself, so it never needs a restart."""
    from ..apply import hot

    root = pathlib.Path(__file__).resolve().parents[1]
    hot_files = {(root.parent / (name.replace(".", "/") + ".py")).resolve() for name in hot.MODULES}
    return any(f.stat().st_mtime > LOADED_AT for f in root.rglob("*.py") if f.resolve() not in hot_files)


def _clip(text, n):
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


class ApplyRun:
    def __init__(self):
        self.id = secrets.token_hex(4)
        self.status = "starting"      # starting | running | waiting | done | stopped | failed
        self.started = dt.datetime.now().isoformat(timespec="seconds")
        self.ended = None
        self.validation = False
        self.auto_submit = False
        self.dry_run = False
        self.unattended = False
        self.jobs = []                # [{n, company, title, url, possible}]
        self.current = None           # index into jobs
        self.results = {}             # url -> {status, note, application}
        self.preview = None
        self.audits = {}              # latest read-back for every job/page, retained beyond activity truncation
        self.events = []
        self.prompt = None
        self.stop_requested = False
        self._answer = None
        self._event = threading.Event()
        self._lock = threading.Lock()

    def log(self, kind, text, **extra):
        with self._lock:
            self.events.append({"t": dt.datetime.now().strftime("%H:%M:%S"), "kind": kind, "text": text, **extra})
            del self.events[:-MAX_EVENTS]

    def snapshot(self):
        with self._lock:
            return self._snapshot()

    def _snapshot(self):
        return {
            "id": self.id, "status": self.status, "started": self.started, "ended": self.ended,
            "validation": self.validation, "auto_submit": self.auto_submit, "dry_run": self.dry_run, "unattended": self.unattended, "jobs": self.jobs, "current": self.current,
            "results": dict(self.results), "events": self.events[-400:], "prompt": self.prompt,
            "audits": list(self.audits.values()), "preview": self.preview,
        }

    def save(self):
        """Keep this run (results and the last of its activity) in ~/.jobbot/runs.json, newest 20 runs."""
        with SAVE_LOCK:   # parallel workers finish roles at the same time
            self._save()

    def _save(self):
        try:
            runs = [r for r in _load_runs() if r.get("id") != self.id]
            snap = {**self.snapshot(), "events": self.events[-150:], "prompt": None}
            runs.append(snap)
            paths.ensure_home()
            RUNS_FILE().write_text(json.dumps(runs[-20:]), encoding="utf-8")
        except OSError:
            pass


    # --- answering prompts from the page -------------------------------------------
    def answer(self, prompt_id, value):
        with self._lock:
            if not self.prompt or self.prompt["id"] != prompt_id:
                raise ValueError("That question is no longer waiting for an answer.")
            self._answer = value
            self._event.set()

    def stop(self):
        self.stop_requested = True
        self.log("warn", "Stop requested: finishing the current step without submitting.")
        self._event.set()


def RUNS_FILE():
    return paths.HOME / "runs.json"


def _load_runs():
    try:
        runs = json.loads(RUNS_FILE().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    live = CURRENT["run"].id if CURRENT["run"] else None
    for r in runs:
        if r.get("status") in ("starting", "running", "waiting") and r.get("id") != live:
            r["status"] = "interrupted"   # the dashboard stopped while it ran
    return runs


def history():
    """Earlier runs, newest first: when, how it ended, and how many roles ended which way."""
    out = []
    for r in reversed(_load_runs()):
        counts = {}
        for res in (r.get("results") or {}).values():
            counts[res.get("status") or "?"] = counts.get(res.get("status") or "?", 0) + 1
        out.append({"id": r["id"], "started": r.get("started"), "ended": r.get("ended"), "status": r.get("status"),
                    "dry_run": r.get("dry_run"), "unattended": r.get("unattended"), "total": len(r.get("jobs") or []),
                    "counts": counts})
    return out


def saved_run(run_id):
    return next((r for r in _load_runs() if r.get("id") == run_id), None)


class WebUI:
    """Same interface as apply.ui.TerminalUI, answered from the dashboard."""

    def __init__(self, run):
        self.run = run

    def _wait(self, kind, default, **data):
        run = self.run
        if run.stop_requested:
            return default
        with run._lock:
            run._event.clear()
            run._answer = None
            run.prompt = {"id": secrets.token_hex(4), "kind": kind, **data}
            run.status = "waiting"
        while not run._event.wait(0.5):
            pass
        with run._lock:
            value = default if run.stop_requested else run._answer
            run.prompt = None
            run.status = "running"
        return value

    # informational
    def info(self, msg):
        self.run.log("info", msg)

    def warn(self, msg):
        self.run.log("warn", msg)

    def report(self, report, check=None, step=None):
        filled = [{"label": label, "value": _clip(str(ans), 120), "source": getattr(ans, "source", "")}
                  for label, ans in report["filled"]]
        self.run.log("report", f"Page {step}" if step else "Page", filled=filled,
                     ok=None if check is None else check.ok,
                     problems=[] if check is None else check.lines(), skipped=report.get("skipped", []))

    def preview_page(self, data):
        self.run.preview = data

    def audit(self, step, round_, fields, check):
        job = getattr(self, "job", None) or (self.run.jobs[self.run.current] if self.run.current is not None else {})
        with self.run._lock:
            self.run.audits[f"{job.get('url', '')}|{step}"] = {"job": job, "step": step, "round": round_,
                                                            "fields": fields, "ok": check.ok, "problems": check.lines()}
        self.run.log("audit", f"Page {step}, revision {round_}", step=step, round=round_,
                     fields=fields, ok=check.ok, problems=check.lines())

    # questions
    def ask(self, question, options, required, suggestion, reason):
        value = self._wait("ask", None, question=question[:600], options=list(options or []), required=required,
                           suggestion=suggestion, reason=reason)
        if isinstance(value, int) and options and 0 <= value < len(options):
            return value
        return value if value not in ("",) else None

    def ask_code(self, prompt):
        value = self._wait("code", None, question=prompt[:600])
        return (value or "").strip() or None

    def confirm(self, msg):
        value = self._wait("confirm", False, question=msg[:1200])
        if value == "skip":
            from ..apply.engine import NeedsYou
            raise NeedsYou(msg)
        return value is True

    def wait_for_user(self, msg):
        value = self._wait("wait", None, question=msg.replace("press Enter here", "click Done, continue"))
        if value == "skip":
            from ..apply.engine import NeedsYou
            raise NeedsYou(msg)

    def next_action(self, can_submit, can_next, dry_run, check_ok=True, final_page=False):
        choices = (["submit"] if can_submit else []) + (["next"] if can_next else []) + ["refill", "done", "quit"]
        value = self._wait("action", "quit", choices=choices, check_ok=check_ok, dry_run=dry_run,
                           final=(can_submit or (dry_run and final_page)) and check_ok)
        if isinstance(value, dict) and value.get("action") == "correct":
            return value
        return value if value in choices else "quit"


CURRENT = {"run": None}
START_LOCK = threading.Lock()


def current():
    return CURRENT["run"]


def start(keys, dry_run=False, auto_next=True, resume=None, use_llm=True, force=False, unattended=False, validation=False, auto_submit=False):
    """Start an apply run in a background thread. Raises ValueError if one is active."""
    if code_changed():
        raise ValueError("jobbot was updated after the dashboard started. Restart it (Ctrl+C, then ./jobbot.sh ui) before applying.")
    if validation:
        dry_run, auto_next = True, bool(unattended)
    if auto_submit:
        dry_run, auto_next, unattended, validation = False, True, True, True
        if not use_llm:
            raise ValueError("Automatic submission requires Ollama review.")
    with START_LOCK:
        run = CURRENT["run"]
        if run and run.status in ("starting", "running", "waiting"):
            raise ValueError("An apply run is already in progress. Stop it first.")
        run = ApplyRun()
        run.validation = validation
        run.auto_submit = auto_submit
        run.dry_run, run.unattended = dry_run, unattended
        CURRENT["run"] = run
    threading.Thread(target=_work, args=(run, keys, dry_run, auto_next, resume, use_llm, force, unattended, validation, auto_submit),
                     daemon=True).start()
    return run


# Failures a second try can fix: the site was down or slow, a page got stuck, a tab closed. Not sign-ins,
# CAPTCHAs, unanswered questions or closed postings: those need you, or a fix, not another attempt.
TRANSIENT = re.compile(r"maintenance|gave up after|next step is blocked|tab was closed|timeout|timed out|"
                       r"target page, context or browser has been closed|no application fields|^error: ", re.I)


def retry_worthy(result):
    note = (result or {}).get("note") or ""
    return (result or {}).get("status") in ("needs you", "not submitted") and bool(TRANSIENT.search(note)) \
        and not re.search(r"captcha|sign in|account|password", note, re.I)


def worker_browser_dir(i):
    """Worker 0 uses jobbot's browser profile; the others a copy of it, made once, so sign-ins carry over."""
    import shutil

    if i == 0:
        return paths.BROWSER_PROFILE
    target = paths.HOME / f"browser-profile-w{i}"
    if not target.exists() and paths.BROWSER_PROFILE.exists():
        skip = shutil.ignore_patterns("Singleton*", "Cache", "Code Cache", "GPUCache", "CacheStorage", "*.lock")
        shutil.copytree(paths.BROWSER_PROFILE, target, ignore=skip, symlinks=True)
    return target


def _parallel(run, prof, model, ui, targets, workers, resume, on_result):
    """Auto-submit with several browsers at once: each worker takes the next role from a shared queue.
    Every page still gets the full review; Ollama serves the workers' reviews in parallel."""
    import queue

    from ..apply.engine import Session
    from ..apply.runner import run_jobs

    todo = queue.Queue()
    for n, job in enumerate(targets, 1):
        todo.put((n, job))
    run.log("info", f"Applying with {workers} browsers in parallel.")
    browser_dirs = [worker_browser_dir(i) for i in range(workers)]  # copy before worker 0 opens Chrome

    def work(i):
        conn = tracker.connect()   # one SQLite connection per thread
        try:
            worker_ui = WebUI(run)
            with Session(prof, model, worker_ui, upload=True, auto_next=True, unattended=True, browser_dir=browser_dirs[i]) as session:
                session.validation, session.auto_submit = True, True
                while not run.stop_requested:
                    try:
                        n, job = todo.get_nowait()
                    except queue.Empty:
                        return
                    run.current = n - 1
                    worker_ui.job = run.jobs[n - 1]
                    run.log("job", f"[{n}/{len(targets)}] {job['company']} — {job['title']} (browser {i + 1})", url=job["url"])
                    run_jobs(session, conn, prof, [job], session.ui, resume=resume, confirm_possible=True,
                             should_stop=lambda: run.stop_requested, on_result=on_result)
        except (Exception, SystemExit) as e:   # one worker's browser failing must not end the others
            run.log("warn", f"Browser {i + 1} stopped: {type(e).__name__}: {e}")
        finally:
            conn.close()

    def run_round():
        threads = [threading.Thread(target=work, args=(i,), daemon=True) for i in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    run_round()
    again = [(n, job) for n, job in enumerate(targets, 1) if retry_worthy(run.results.get(job["url"]))]
    if again and not run.stop_requested:
        run.log("info", f"Retrying {len(again)} role(s) that failed for a temporary reason (site down, timeout, stuck page).")
        for item in again:
            todo.put(item)
        run_round()
    for job in targets:
        if job["url"] not in run.results:
            on_result(job, "not submitted", "Stopped before this job or no browser worker could process it.", None)


def _work(run, keys, dry_run, auto_next, resume, use_llm, force, unattended=False, validation=False, auto_submit=False):
    from ..apply.engine import Session
    from ..apply.runner import review_ready, run_jobs, select_targets

    ui = WebUI(run)
    try:
        conn = tracker.connect()     # SQLite connections belong to the thread that made them
        prof = profile_mod.load()
        model = llm_mod.LLM(enabled=use_llm)
        if use_llm and model.enabled and not model.has_model():
            model.enabled = False
        if auto_submit and not model.enabled:
            raise ValueError("Automatic submission requires a running Ollama model; no applications were opened.")
        targets = select_targets(conn, keys, force=force, note=lambda m: run.log("info", m),
                                 exclude=prof.get("preferences.exclude_companies") or [])
        if auto_submit:
            cap = int(prof.get("automation.max_applications_per_day", 0) or 0)
            if cap:
                targets = targets[:max(0, cap - tracker.submitted_today(conn))]
        run.jobs = [{"n": t.get("n"), "company": t["company"], "title": t["title"], "url": t["url"],
                     "possible": t.get("_possible", "")} for t in targets]
        if not targets:
            run.log("warn", "Nothing to apply to: every selected role is already applied, dismissed, or unknown.")
            run.status = "done"
            return
        run.status = "running"
        run.log("info", f"Starting {len(targets)} application(s){' (dry run)' if dry_run else ''}. "
                        "Chrome opens in a separate window; keep an eye on it for sign-ins and CAPTCHAs.")

        def on_job(n, total, job):
            run.current = n - 1
            run.log("job", f"[{n}/{total}] {job['company']} — {job['title']}", url=job["url"])

        def on_result(job, status, note, app_id):
            with run._lock:
                run.results[job["url"]] = {"status": status, "note": note, "application": app_id}
            run.save()

        if validation and not auto_submit:   # a dry validation never consents; an approved auto-submit run keeps your auto_consent
            prof.data.setdefault("automation", {})["auto_consent"] = False
        workers = max(1, min(int(prof.get("automation.parallel_workers", 1) or 1), len(targets))) if auto_submit else 1
        if workers > 1:
            _parallel(run, prof, model, ui, targets, workers, resume, on_result)
        else:
            with Session(prof, model, ui, dry_run=dry_run, upload=True, auto_next=auto_next, unattended=unattended) as session:
                session.validation = validation
                session.auto_submit = auto_submit
                results = run_jobs(session, conn, prof, targets, session.ui, resume=resume, dry_run=dry_run,
                                   confirm_possible=not validation or auto_submit, should_stop=lambda: run.stop_requested, on_job=on_job,
                                   on_result=on_result)
                again = [job for job in targets if retry_worthy(run.results.get(job["url"]))]
                if again and unattended and not run.stop_requested:
                    run.log("info", f"Retrying {len(again)} role(s) that failed for a temporary reason (site down, timeout, stuck page).")
                    retried = run_jobs(session, conn, prof, again, session.ui, resume=resume, dry_run=dry_run,
                                       confirm_possible=not validation or auto_submit, should_stop=lambda: run.stop_requested,
                                       on_job=on_job, on_result=on_result)
                    redone = {r[0]["url"]: r for r in retried}
                    results = [redone.get(r[0]["url"], r) for r in results]
                if unattended and not auto_submit and not run.stop_requested:
                    run.current = None
                    review_ready(session, conn, results, ui, resume=resume, on_result=on_result)
        run.status = "stopped" if run.stop_requested else "done"
    except SystemExit as e:          # e.g. jobbot's browser is already open in another run
        run.log("warn", str(e))
        run.status = "failed"
    except Exception as e:
        run.log("warn", f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-2000:])
        run.status = "failed"
    finally:
        if 'conn' in locals():
            conn.close()
        run.prompt = None
        run.current = None
        run.ended = dt.datetime.now().isoformat(timespec="seconds")
        run.log("info", f"Run {run.status}.")
        run.save()
