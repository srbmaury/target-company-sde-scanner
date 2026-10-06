"""Unattended mode: a batch that never stops for you (see docs/apply.md#unattended-mode)."""


class NeedsYou(Exception):
    """Unattended mode: this application needs you (sign-in, an unanswerable question, a missing code)."""


class UnattendedUI:
    """Wraps a UI so a batch never stops: questions nothing answers are left blank and noted, waits for you
    become NeedsYou, and the final page is held open (in its own tab) for you to submit at the end."""

    def __init__(self, inner):
        self.inner = inner
        self.unanswered = []

    def __getattr__(self, name):          # info, warn, report go straight through
        return getattr(self.inner, name)

    def ask(self, question, options, required, suggestion, reason):
        if required:
            self.unanswered.append(question[:120])
        return None

    def ask_code(self, prompt):
        self.unanswered.append("verification code (none arrived by email)")
        return None

    def confirm(self, msg):
        return False                       # consent follows automation.auto_consent; never "submit anyway"

    def wait_for_user(self, msg):
        raise NeedsYou(msg)

    def next_action(self, can_submit, can_next, dry_run, check_ok=True, final_page=False):
        return "hold" if final_page and check_ok else "quit"
