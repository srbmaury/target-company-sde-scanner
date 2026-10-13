"""Email codes and activation links, scoped to the current application site."""
import re
import urllib.parse
import time

CODE_RE = re.compile(r"verification code|security code|one.?time (pass)?code|\botp\b|enter the \d*.?character code|code (was )?sent to|confirmation code", re.I)


def follow_activation_link(self, page):
    """Open only a fresh verification link for this exact site and recipient."""
    from .. import gmail
    from .auth import host_allowed
    if not self.profile.get("automation.read_codes_from_email", True) or not gmail.is_connected():
        return False
    host = urllib.parse.urlparse(page.url).hostname or ""
    if not host_allowed(page.url, self.profile, getattr(self, "_job_url", None)):
        return False
    self.ui.info("Waiting for this site's account verification email.")
    link = gmail.latest_link(getattr(self, "_auth_started", getattr(self, "_started", time.time())), host,
                             recipient=self.profile.get("personal.email", ""))
    if not link:
        return False
    page.goto(link, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    self.ui.info("Opened this site's account verification link.")
    return True

def email_login_step(self, page):
    """Complete an existing email/code login step, without creating credentials or accepting terms."""
    fields = self._fields(page)
    codes = [f for f in fields if f["kind"] == "text" and CODE_RE.search(f["label"] or "")]
    if codes and not all(f.get("value") for f in codes):
        code = self._code_from_email(page)
        if not code:
            return False
        single = len(codes) > 1 and (all(f.get("maxlength") == 1 for f in codes) or len(codes) == len(code))
        for f, value in zip(codes, code if single else [code]):
            page.locator(f'[data-jobbot-id="{f["id"]}"]').fill(value)
        self.ui.info("Filled the email verification code for this login.")
        confirm = r"^verify(?: email| code)?$|^continue$|^sign in$"
        if self._buttons(page, confirm):
            self._click(page, confirm)
            page.wait_for_timeout(1500)
        return True
    emails = [f for f in fields if f["kind"] == "text" and (f.get("type") == "email" or re.search(r"email", f["label"], re.I))]
    if not emails or page.locator("input[type=password]:visible").count():
        return False
    # Never use generic Continue on an account-creation or agreement page.
    pattern = r"^(send|email)(?: me)? (?:a )?(?:verification |one.time |sign.in )?(?:code|link)$|^send verification code$"
    if not self._buttons(page, pattern):
        return False
    email = self.profile.get("personal.email", "")
    if not email:
        return False
    page.locator(f'[data-jobbot-id="{emails[0]["id"]}"]').fill(email)
    self._click(page, pattern)
    self.ui.info("Requested a login verification email.")
    return True


def code_from_email(self, page):
    """Read a verification code from your latest email (Gmail, read-only), if Gmail is connected."""
    if not self.profile.get("automation.read_codes_from_email", True):
        return None
    try:
        from .. import gmail
        if not gmail.is_connected():
            return None
        host = urllib.parse.urlparse(page.url).netloc.split(".")
        # every meaningful part of the host: job-boards.greenhouse.io mails from greenhouse-mail.io
        hints = [p for p in host if p not in ("www", "careers", "jobs", "job-boards", "boards", "apply", "com", "in",
                                               "co", "io", "us", "eu", "myworkdayjobs") and not re.fullmatch(r"wd\d+", p)]
        self.ui.info("Waiting for the verification email (up to 90 s)…")
        if "myworkdayjobs" in host:
            hints.append("workday")
        code = gmail.latest_code(getattr(self, "_started", 0) - 120, hint=hints, wait=90)
    except Exception as e:   # Gmail unreachable or token revoked: fall back to asking
        self.ui.warn(f"Could not read the code from email ({type(e).__name__}); please enter it.")
        return None
    if code:
        self.ui.info("Verification code read from the current site's email.")
    return code
