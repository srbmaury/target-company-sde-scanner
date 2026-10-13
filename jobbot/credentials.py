"""The password jobbot uses for job-site accounts (Workday and similar), kept in the macOS Keychain.

It is never written to profile.yaml, logs, run history or the dashboard. `jobbot password` stores it:
`security` prompts for it itself, so it never appears on a command line either.
"""

import subprocess
import sys

SERVICE = "jobbot job sites"


def available():
    return sys.platform == "darwin"


def get(account, host=None):
    """The stored password for `account` (your email), or None."""
    if not available() or not account:
        return None
    services = [f"{SERVICE}:{host}", SERVICE] if host else [SERVICE]
    for service in services:
        r = subprocess.run(["security", "find-generic-password", "-s", service, "-a", account, "-w"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout.rstrip("\n") or None
    return None


def set_interactive(account):
    """Ask for the password at a hidden prompt and store it. True on success."""
    # With -w last and no value, `security` prompts (twice) instead of taking the password as an argument.
    return subprocess.run(["security", "add-generic-password", "-U", "-s", SERVICE, "-a", account,
                           "-l", "jobbot: job-site accounts", "-w"]).returncode == 0


def delete(account):
    return subprocess.run(["security", "delete-generic-password", "-s", SERVICE, "-a", account],
                          capture_output=True).returncode == 0
