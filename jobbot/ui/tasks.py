"""Background dashboard task execution and mutual-exclusion policy."""

import datetime as dt
import json
import os
import secrets
import subprocess
import sys
import threading

from .. import paths

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

