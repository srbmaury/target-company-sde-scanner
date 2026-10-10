"""Pick up fixed form-filling code between applications, without restarting the dashboard or a run.

Before each application, `refresh(session)` reloads the apply modules whose files changed (dependencies
first) and moves the browser session onto the new code. The browser, sign-ins and run state stay.
Exception classes (unattended.py) are never reloaded: a NeedsYou raised by new code must still be the
class the run catches.
"""
import importlib
import pathlib
import sys
import threading

# In dependency order: a module is reloaded after everything it imports names from.
MODULES = (
    "jobbot.resumes", "jobbot.answers",
    "jobbot.apply.fields", "jobbot.apply.values", "jobbot.apply.verify", "jobbot.apply.sites",
    "jobbot.apply.dropdowns", "jobbot.apply.email_verification", "jobbot.apply.auth",
    "jobbot.apply.consistency", "jobbot.apply.review", "jobbot.apply.browser", "jobbot.apply.engine",
)
_LOCK = threading.Lock()
_seen = {}


def _file(name):
    module = sys.modules.get(name)
    path = getattr(module, "__file__", None)
    return pathlib.Path(path) if path else None


def files():
    """The source files this module keeps fresh (the dashboard need not restart for them)."""
    return {p.resolve() for p in (_file(n) for n in MODULES) if p}


def _stamp(name):
    path = _file(name)
    try:
        return path.stat().st_mtime if path else 0
    except OSError:
        return 0


def changed():
    """Names of loaded apply modules whose files changed since they were (re)loaded."""
    for name in MODULES:
        if name in sys.modules:
            _seen.setdefault(name, _stamp(name))
    return [n for n in MODULES if n in sys.modules and _stamp(n) > _seen[n]]


def refresh(session=None, log=None):
    """Reload changed apply code; move `session` onto the new Session class. True when anything changed."""
    with _LOCK:
        stale = changed()
        if not stale:
            return False
        first = min(MODULES.index(n) for n in stale)
        reloaded = []
        for name in MODULES[first:]:   # everything after the first change may hold names from it
            if name in sys.modules:
                importlib.reload(sys.modules[name])
                _seen[name] = _stamp(name)
                reloaded.append(name.rsplit(".", 1)[-1])
        if session is not None:
            session.__class__ = sys.modules["jobbot.apply.engine"].Session
        if log:
            log(f"Picked up updated code ({', '.join(reloaded)}) for the next application.")
        return True
