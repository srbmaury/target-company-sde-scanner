"""The password jobbot uses for job-site accounts (Workday and similar), kept in the macOS Keychain.

It is never written to profile.yaml, logs, run history or the dashboard. `jobbot password` stores it:
`security` prompts for it itself, so it never appears on a command line either.
"""

import subprocess
import sys

SERVICE = "jobbot job sites"


def available():
    return sys.platform == "darwin"


MAX_ALTERNATES = 4   # extra passwords to try ("jobbot password --add"): SERVICE#2 .. SERVICE#5


def _read(service, account):
    r = subprocess.run(["security", "find-generic-password", "-s", service, "-a", account, "-w"],
                       capture_output=True, text=True)
    return (r.stdout.rstrip("\n") or None) if r.returncode == 0 else None


def candidates(account, host=None):
    """Every stored password for `account`, in the order to try them: this site's own, the main one, then the
    alternates. Duplicates are dropped. Never printed or logged."""
    if not available() or not account:
        return []
    services = ([f"{SERVICE}:{host}"] if host else []) + [SERVICE] + \
        [f"{SERVICE}#{i}" for i in range(2, MAX_ALTERNATES + 2)]
    out = []
    for service in services:
        pw = _read(service, account)
        if pw and pw not in out:
            out.append(pw)
    return out


def get(account, host=None):
    """The first password to use for `account` (your email) on `host`, or None."""
    found = candidates(account, host)
    return found[0] if found else None


def _service(slot=None, site=None):
    if site:
        return f"{SERVICE}:{site}"
    return SERVICE if not slot or slot == 1 else f"{SERVICE}#{slot}"


def next_free_slot(account):
    for i in range(2, MAX_ALTERNATES + 2):
        if not _read(_service(i), account):
            return i
    return None


def set_interactive(account, slot=None, site=None):
    """Ask for a password at a hidden prompt and store it (the main one, an alternate slot, or one site's).
    True on success."""
    label = f"jobbot: {site}" if site else "jobbot: job-site accounts" + (f" (alternate {slot})" if slot and slot > 1 else "")
    # With -w last and no value, `security` prompts (twice) instead of taking the password as an argument.
    return subprocess.run(["security", "add-generic-password", "-U", "-s", _service(slot, site), "-a", account,
                           "-l", label, "-w"]).returncode == 0


def delete(account, slot=None, site=None):
    return subprocess.run(["security", "delete-generic-password", "-s", _service(slot, site), "-a", account],
                          capture_output=True).returncode == 0


def count(account):
    """How many passwords are stored (main + alternates), never their values."""
    return sum(1 for i in range(1, MAX_ALTERNATES + 2) if _read(_service(i), account))
