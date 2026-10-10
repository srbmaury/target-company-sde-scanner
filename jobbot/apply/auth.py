"""Job-site accounts: sign in first, sign up when there is no account, then email verification.

Credentials go directly from Keychain to password inputs; never through the field scanner, model,
dashboard, or logs. Sign-up runs only with automation.create_accounts on and a password you stored
with `jobbot password`; CAPTCHAs and rejected passwords are handed to you, never retried.
"""
import re
import urllib.parse

from .. import credentials
from . import sites
from .unattended import NeedsYou
from .verify import check_page

PROVIDERS = ("myworkdayjobs.com", "oraclecloud.com", "eightfold.ai", "qualcomm.com",
             "greenhouse.io", "lever.co", "ashbyhq.com", "smartrecruiters.com", "keka.com", "zoho.com")
CREATE_RE = r"^(create (an? )?account|register|sign up)$"
LOGIN_RE = r"^(sign in|log in|login)$"
NO_ACCOUNT_RE = re.compile(r"account (does not exist|not found|doesn.t exist)|no account (exists|found)|"
                           r"(e-?mail|user).{0,25}(not (found|registered|recogni[sz]ed)|does not exist)|"
                           r"couldn.t find (an|your) account|don.t have an account", re.I)
SIGNUP_BUTTON_RE = r"^(create (an? |my )?account|register|sign up|submit)$"
VERIFY_RE = re.compile(r"check your (e-?mail|inbox)|verify your (e-?mail|account)|activation (link|email)", re.I)


# Identity providers: your job-site password is not your password there, so it is never typed on them.
IDENTITY_PROVIDERS = ("accounts.google.com", "google.com", "login.microsoftonline.com", "login.live.com",
                      "microsoft.com", "linkedin.com", "appleid.apple.com", "apple.com", "github.com", "facebook.com")


def site(host):
    """The registrable part of a host: careers.qualcomm.com -> qualcomm.com, jobs.example.co.in -> example.co.in."""
    parts = (host or "").lower().split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "ac", "gov") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def host_allowed(url, profile, job_url=None):
    """May jobbot type your job-site password on this page? Only over https, never on an identity provider,
    and only on a known job platform or on a site of the company whose posting you are applying to."""
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or any(host == h or host.endswith("." + h) for h in IDENTITY_PROVIDERS):
        return False
    extras = profile.get("automation.sign_in_hosts", []) or []   # optional: rarely needed now
    if any(host == h or host.endswith("." + h) for h in (*PROVIDERS, *extras)):
        return True
    job_host = (urllib.parse.urlparse(job_url or "").hostname or "").lower()
    return bool(job_host) and site(host) == site(job_host)


def needs_account(page):
    return sites.signin_page(page) or bool(VERIFY_RE.search(page.inner_text("body")[:4000]))


def workday_sign_in(self, page):
    """Try an existing account before offering creation; create_accounts is not a login switch."""
    if "myworkdayjobs.com" not in (urllib.parse.urlparse(page.url).hostname or ""):
        return False
    by = lambda aid: page.locator(f'[data-automation-id="{aid}"]:visible')
    if not by("signInSubmitButton").count() and by("signInLink").count():
        by("signInLink").first.click()
        page.wait_for_timeout(1500)
    if not by("signInSubmitButton").count():
        return False
    cover = page.locator('[data-automation-id="click_filter"]:visible', has_text="Sign In")
    target = cover.first if cover.count() else by("signInSubmitButton").first
    return password_sign_in(self, page, target, by("email").first, by("password").first)


def password_sign_in(self, page, button=None, email_input=None, password_input=None):
    if not self.profile.get("automation.sign_in", True) or not host_allowed(page.url, self.profile, getattr(self, "_job_url", None)):
        return False
    passwords = page.locator('input[type="password"]:visible')
    headings = " ".join(page.locator('h1,h2').all_inner_texts())
    if passwords.count() != 1 or button is None and re.match(CREATE_RE, headings, re.I):
        return False  # never type a stored password into a new-credential form
    if button is None:
        button = page.get_by_role("button", name=re.compile(LOGIN_RE, re.I))
        if not button.count():
            return False
        button = button.first
    email = self.profile.get("personal.email", "")
    key = (urllib.parse.urlparse(page.url).hostname, email)
    attempted = getattr(self, "_auth_attempted", set())
    if key in attempted:
        return False  # avoid repeated rejected attempts and account lockouts
    password = credentials.get(email, host=key[0])
    if not password:
        self._auth_failure = "No existing password is stored in Keychain; store it with jobbot password."
        return False
    if email_input is None:
        emails = page.locator('input[type="email"]:visible, input[autocomplete="username"]:visible, input[name*="email" i]:visible')
        if not emails.count():
            return False
        email_input = emails.first
    self._auth_attempted = attempted | {key}
    email_input.fill(email)
    (password_input or passwords.first).fill(password)
    button.click(timeout=5000)
    password = None
    page.wait_for_timeout(2000)
    sites.wait_rendered(page)
    body = page.inner_text("body")
    if NO_ACCOUNT_RE.search(body):
        self._no_account = True   # sign up next
        return False
    if re.search(r"incorrect password|invalid (credentials|password)|wrong (e-?mail|password)|unable to sign in", body, re.I):
        self._auth_failure = ("Your Keychain password was rejected here (the account may use another password). "
                              "No reset or repeated attempt was made.")
        return False
    self.ui.info("Submitted stored credentials to the existing-account sign-in form.")
    return not needs_account(page)


def sign_up(self, page):
    """Create the account on the site's own sign-up form with your Keychain password, after sign-in found
    no account. Fills only the sign-up form (email, password, confirm password, name), ticks only that
    form's terms box, and leaves CAPTCHAs to you. Returns True once the form was submitted."""
    if not self.profile.get("automation.create_accounts", False) or not host_allowed(page.url, self.profile, getattr(self, "_job_url", None)):
        return False
    email = self.profile.get("personal.email", "")
    host = urllib.parse.urlparse(page.url).hostname
    if (host, email) in getattr(self, "_signed_up", set()):
        return False   # one attempt per site and run: never loop on a rejected sign-up
    if check_page(page, [], [], []).captcha:
        raise NeedsYou("The sign-up form shows a CAPTCHA; complete it in the browser, then retry.")
    password = credentials.get(email, host=host)
    if not password:
        self._auth_failure = "No password is stored for job-site accounts: run `jobbot password` once."
        return False
    passwords = page.locator('input[type="password"]:visible')
    if passwords.count() == 1 and not re.search(CREATE_RE[1:-1], " ".join(page.locator("h1,h2,h3,button").all_inner_texts()), re.I):
        return False   # a single password box with no sign-up wording is a sign-in form
    if not passwords.count():
        return False
    self._signed_up = getattr(self, "_signed_up", set()) | {(host, email)}
    workday = "myworkdayjobs.com" in (host or "")
    emails = page.locator('[data-automation-id="email"]:visible' if workday else
                          'input[type="email"]:visible, input[autocomplete="username"]:visible, input[name*="email" i]:visible')
    if emails.count():
        emails.first.fill(email)
    for i in range(passwords.count()):   # password and "confirm / verify password"
        passwords.nth(i).fill(password)
    password = None
    for sel, key in (('input[autocomplete="given-name"]:visible, input[name*="first" i]:visible', "personal.first_name"),
                     ('input[autocomplete="family-name"]:visible, input[name*="last" i]:visible', "personal.last_name")):
        box = page.locator(sel)
        if box.count() and not box.first.input_value():
            box.first.fill(str(self.profile.get(key, "")))
    _tick_signup_terms(page, workday)
    self.ui.info(f"Creating your {host} account with your Keychain password.")
    if workday:
        cover = page.locator('[data-automation-id="click_filter"]:visible', has_text="Create Account")
        (cover.first if cover.count() else page.locator('[data-automation-id="createAccountSubmitButton"]:visible').first).click(timeout=5000)
    else:
        button = page.get_by_role("button", name=re.compile(SIGNUP_BUTTON_RE, re.I))
        if not button.count():
            return False
        button.first.click(timeout=5000)
    page.wait_for_timeout(3000)
    sites.wait_rendered(page)
    if re.search(r"already (exists|in use|registered)|account .{0,40}exists", page.inner_text("body"), re.I):
        self._auth_failure = "An account already exists here with a different password; sign in once yourself, then retry."
        return False
    self._auth_started = getattr(self, "_auth_started", None) or getattr(self, "_started", 0)
    return True


def _tick_signup_terms(page, workday):
    """The sign-up form's own terms/privacy box (needed to create the account); nothing else."""
    if workday:
        box = page.locator('[data-automation-id="createAccountCheckbox"]:visible')
        if box.count() and not box.first.is_checked():
            box.first.check(force=True)
        return
    boxes = page.locator('input[type="checkbox"]:visible')
    for i in range(boxes.count()):
        box = boxes.nth(i)
        label = box.evaluate("el => (el.labels && el.labels[0] ? el.labels[0].innerText : el.closest('label, div')?.innerText || '')")
        if re.search(r"terms|privacy|agree|consent", label or "", re.I) and not re.search(r"marketing|newsletter|sms|whatsapp", label or "", re.I):
            if not box.is_checked():
                box.check(force=True)


def _codes_filled(self, page):
    from .email_verification import CODE_RE
    codes = [f for f in self._fields(page) if f["kind"] == "text" and CODE_RE.search(f["label"] or "")]
    return bool(codes) and all(f.get("value") for f in codes)


def go_to_sign_up(page):
    """From a sign-in page, open the site's create-account form."""
    for role in ("button", "link"):
        target = page.get_by_role(role, name=re.compile(CREATE_RE, re.I))
        if target.count():
            target.first.click(timeout=5000)
            page.wait_for_timeout(1500)
            return True
    return False


def ensure_signed_in(self, page, attempts=4):
    """Sign in first; if the site has no account for you, sign up; then verify by email and continue."""
    self._auth_failure, self._no_account = None, False
    for _ in range(attempts):
        if not needs_account(page):
            return True
        if check_page(page, [], [], []).captcha:
            raise NeedsYou("Sign-in CAPTCHA requires your action; credentials were not retried.")
        if self._email_login_step(page):
            page.wait_for_timeout(1500)
            if not page.locator('input[type="password"]:visible').count() and _codes_filled(self, page):
                return True   # the code is in; this page's own button (Submit or Next) follows the normal flow
            continue
        if VERIFY_RE.search(page.inner_text("body")[:4000]):
            from .email_verification import follow_activation_link
            if follow_activation_link(self, page):
                continue
        if self._workday_account(page) or password_sign_in(self, page):
            continue
        # Login may have advanced to a verification step without yet completing.
        if not needs_account(page):
            return True
        if VERIFY_RE.search(page.inner_text("body")[:4000]) or self._fields(page) and any(
                re.search(r"verification code|one.?time|\botp\b", f.get("label", ""), re.I)
                for f in self._fields(page)):
            continue
        # No account here (or sign-in was not possible): create one, then verify by email and sign in.
        if self.profile.get("automation.create_accounts", False) and (getattr(self, "_no_account", False) or not self._auth_failure):
            if sign_up(self, page) or (go_to_sign_up(page) and sign_up(self, page)):
                self._no_account = False
                continue
        reason = self._auth_failure or "The site requires an account or sign-in method jobbot cannot complete."
        self._wait_for_user(page, reason + " Sign in or create the account in the browser; "
                            "jobbot then handles the verification email and resumes the application.")
    if needs_account(page):
        raise NeedsYou("Sign-in did not complete after credential/email verification attempts.")
    return True
