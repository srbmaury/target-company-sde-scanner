"""Run `apply` inside the dashboard.

The engine talks to a UI object (info, warn, ask, confirm, ask_code, wait_for_user,
report, next_action). WebUI implements the same interface, but each question becomes
a pending prompt that the page shows; the engine's thread waits until the page answers.
Only one apply run at a time, because jobbot's browser profile can be open only once.
"""

import datetime as dt
import secrets
import threading
import traceback

from .. import llm as llm_mod
from .. import profile as profile_mod
from .. import tracker

MAX_EVENTS = 1500


def _clip(text, n):
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


class ApplyRun:
    def __init__(self):
        self.id = secrets.token_hex(4)
        self.status = "starting"      # starting | running | waiting | done | stopped | failed
        self.started = dt.datetime.now().isoformat(timespec="seconds")
        self.ended = None
        self.dry_run = False
        self.jobs = []                # [{n, company, title, url, possible}]
        self.current = None           # index into jobs
        self.results = {}             # url -> {status, note, application}
        self.events = []
        self.prompt = None
        self.stop_requested = False
        self._answer = None
        self._event = threading.Event()
        self._lock = threading.Lock()

    def log(self, kind, text, **extra):
        self.events.append({"t": dt.datetime.now().strftime("%H:%M:%S"), "kind": kind, "text": text, **extra})
        del self.events[:-MAX_EVENTS]

    def snapshot(self):
        return {
            "id": self.id, "status": self.status, "started": self.started, "ended": self.ended,
            "dry_run": self.dry_run, "jobs": self.jobs, "current": self.current,
            "results": self.results, "events": self.events[-400:], "prompt": self.prompt,
        }

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
        return bool(self._wait("confirm", False, question=msg[:1200]))

    def wait_for_user(self, msg):
        self._wait("wait", None, question=msg.replace("press Enter here", "click Done, continue"))

    def next_action(self, can_submit, can_next, dry_run, check_ok=True):
        choices = (["submit"] if can_submit else []) + (["next"] if can_next else []) + ["refill", "done", "quit"]
        value = self._wait("action", "quit", choices=choices, check_ok=check_ok, dry_run=dry_run,
                           final=can_submit and check_ok)
        return value if value in choices else "quit"


CURRENT = {"run": None}
START_LOCK = threading.Lock()


def current():
    return CURRENT["run"]


def start(keys, dry_run=False, auto_next=True, resume=None, use_llm=True, force=False):
    """Start an apply run in a background thread. Raises ValueError if one is active."""
    with START_LOCK:
        run = CURRENT["run"]
        if run and run.status in ("starting", "running", "waiting"):
            raise ValueError("An apply run is already in progress. Stop it first.")
        run = ApplyRun()
        run.dry_run = dry_run
        CURRENT["run"] = run
    threading.Thread(target=_work, args=(run, keys, dry_run, auto_next, resume, use_llm, force), daemon=True).start()
    return run


def _work(run, keys, dry_run, auto_next, resume, use_llm, force):
    from ..apply.engine import Session
    from ..apply.runner import run_jobs, select_targets

    ui = WebUI(run)
    try:
        conn = tracker.connect()     # SQLite connections belong to the thread that made them
        prof = profile_mod.load()
        model = llm_mod.LLM(enabled=use_llm)
        if use_llm and model.enabled and not model.has_model():
            model.enabled = False
        targets = select_targets(conn, keys, force=force, note=lambda m: run.log("info", m))
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
            run.results[job["url"]] = {"status": status, "note": note, "application": app_id}

        with Session(prof, model, ui, dry_run=dry_run, upload=True, auto_next=auto_next) as session:
            run_jobs(session, conn, prof, targets, ui, resume=resume, dry_run=dry_run, confirm_possible=True,
                     should_stop=lambda: run.stop_requested, on_job=on_job, on_result=on_result)
        run.status = "stopped" if run.stop_requested else "done"
    except SystemExit as e:          # e.g. jobbot's browser is already open in another run
        run.log("warn", str(e))
        run.status = "failed"
    except Exception as e:
        run.log("warn", f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-2000:])
        run.status = "failed"
    finally:
        run.prompt = None
        run.current = None
        run.ended = dt.datetime.now().isoformat(timespec="seconds")
        run.log("info", f"Run {run.status}.")
