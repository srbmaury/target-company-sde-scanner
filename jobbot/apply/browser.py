"""jobbot's own Chrome window: launching it with your browser profile, and noticing when another run
already holds that profile (Chrome can open a profile only once)."""
import os
import re

from .. import paths


def launch(profile_dir=None):
    """Start Chrome with jobbot's profile (or a parallel worker's copy). Returns (playwright, context)."""
    from playwright.sync_api import sync_playwright

    profile_dir = profile_dir or paths.BROWSER_PROFILE
    paths.ensure_home()
    holder = browser_profile_holder(profile_dir)
    if holder:
        raise SystemExit(
            f"jobbot's browser is already open from another run (process {holder}). "
            f"Finish or quit that run (press q there), or stop it with: kill {holder}")
    pw = sync_playwright().start()
    # Sign-in pages (Microsoft, Google) refuse browsers that announce automation, which blocks signing in
    # or creating an account in this window. Launch it like a normal Chrome instead.
    # JOBBOT_HEADLESS=1 runs without a window (tests and CI); you normally watch the window.
    opts = dict(user_data_dir=str(profile_dir), headless=os.environ.get("JOBBOT_HEADLESS") == "1",
                viewport=None,
                args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"])
    try:
        ctx = pw.chromium.launch_persistent_context(channel="chrome", **opts)
    except Exception:
        ctx = pw.chromium.launch_persistent_context(**opts)  # needs `playwright install chromium`
    # A field that is hidden or covered (e.g. a follow-up shown only after "Yes") would otherwise make each
    # click or fill wait Playwright's default 30 s, in every review round.
    ctx.set_default_timeout(10000)
    ctx.set_default_navigation_timeout(45000)
    return pw, ctx


def browser_profile_holder(profile_dir=None):
    """PID of a live Chrome holding jobbot's browser profile, or None.

    Chrome's SingletonLock is a symlink to "<hostname>-<pid>"; a stale lock from a crash
    points at a PID that no longer exists and is ignored.
    """
    import os

    lock = (profile_dir or paths.BROWSER_PROFILE) / "SingletonLock"
    try:
        target = os.readlink(lock)
    except OSError:
        return None
    m = re.search(r"-(\d+)$", target)
    if not m:
        return None
    pid = int(m.group(1))
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass
    return _owning_jobbot(pid) or pid


def _owning_jobbot(chrome_pid):
    """Walk up from Chrome to the `python -m jobbot ...` process that launched it, if any."""
    import subprocess

    pid = chrome_pid
    for _ in range(4):
        out = subprocess.run(["ps", "-o", "ppid=,command=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        if not out:
            return None
        ppid, _, command = out.partition(" ")
        if "-m jobbot" in command:
            return pid
        pid = int(ppid.strip() or 0)
        if pid <= 1:
            return None
    return None
