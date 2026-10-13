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
MAX_SIGN_IN_TRIES = 3   # stored passwords tried per site and run; more risks locking the account
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
    if not by("signInSubmitButton").count():
        # Workday often opens on Create Account with "Already have an account? Sign In" underneath:
        # try your existing account first, by the link's id or else its visible text.
        link = by("signInLink")
        if not link.count():
            link = page.locator('main button:visible, main a:visible, [role="main"] button:visible, form ~ * button:visible, button:visible',
                                has_text=re.compile(r"^\s*sign in\s*$", re.I))
        if link.count():
            try:
                link.last.click(timeout=5000)
            except Exception:
                link.last.click(force=True, timeout=5000)
            page.wait_for_timeout(2000)
    # Some tenants (eBay) first ask how to sign in: Google or email. Use email (your Keychain password).
    with_email = page.get_by_role("button", name=re.compile(r"^sign in with e-?mail$", re.I))
    if not by("signInSubmitButton").count() and with_email.count():
        press(with_email.first, with_email.first)
        page.wait_for_timeout(2000)
    if not by("signInSubmitButton").count():
        return False
    # Workday lays an invisible click_filter over its Sign In button; it carries the name in aria-label, not text.
    cover = page.locator('[data-automation-id="click_filter"][aria-label="Sign In" i]:visible')
    if not cover.count():
        cover = page.locator('[data-automation-id="click_filter"]:visible', has_text="Sign In")
    target = cover.first if cover.count() else by("signInSubmitButton").first
    return password_sign_in(self, page, target, by("email").first, by("password").first)


def _evidence(page):
    """What the page itself says, plus a screenshot in the logs folder, for a sign-in that did not complete."""
    note = ""
    try:
        errors = check_page(page, [], [], []).errors
        if errors:
            note += " The site says: " + "; ".join(e[:120] for e in errors[:3]) + "."
        import time
        from .. import paths
        shot = paths.HOME / "logs" / f"auth-{urllib.parse.urlparse(page.url).hostname}-{time.strftime('%H%M%S')}.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shot), full_page=True)
        note += f" Screenshot: {shot}"
    except Exception:
        pass
    return note


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
    passwords_to_try = credentials.candidates(email, host=key[0])[:MAX_SIGN_IN_TRIES]
    if not passwords_to_try:
        self._auth_failure = "No existing password is stored in Keychain; store it with jobbot password."
        return False
    if email_input is None:
        emails = page.locator('input[type="email"]:visible, input[autocomplete="username"]:visible, input[name*="email" i]:visible')
        if not emails.count():
            return False
        email_input = emails.first
    self._auth_attempted = attempted | {key}
    workday = "myworkdayjobs.com" in (key[0] or "")
    refused = False
    for password in passwords_to_try:   # this site's own password, the main one, then alternates (at most 3)
        email_input.fill(email)
        pw_box = password_input or page.locator('input[type="password"]:visible').first
        pw_box.fill(password)
        press(button, pw_box)
        page.wait_for_timeout(2500)
        sites.wait_rendered(page)
        # Judge the result by the site's own messages, never by static page text: Workday's sign-in form always
        # says "Don't have an account?", which used to make every refused sign-in look like "no account".
        said = " ".join(page.locator('[role="alert"]:visible, [data-automation-id*="error" i]:visible, '
                                     '[aria-live="assertive"]:visible, [class*="error" i]:visible').all_inner_texts())
        wrong = re.search(r"incorrect|invalid (credentials|password|e-?mail|login)|wrong (e-?mail|password)|"
                          r"unable to sign in|(does|did) not match|try again", said, re.I)
        # A clear "no account" anywhere on the page (some sites print it as plain text), but not the static
        # "Don't have an account?" line every sign-in form carries.
        body = re.sub(r"don.t have an account\??", "", page.inner_text("body"), flags=re.I)
        if NO_ACCOUNT_RE.search(said) or NO_ACCOUNT_RE.search(body):
            break   # definitely no account: other passwords cannot help
        if wrong or needs_account(page):
            refused = True
            if re.search(r"locked|too many", said, re.I):
                break   # never push a lockout further
            continue   # this password was refused: try the next one
        password = None
        self.ui.info("Signed in with your existing account.")
        return True
    password = None
    if refused and not workday:
        self._auth_failure = ("None of your stored passwords was accepted here (the account may use another one; "
                              "add it with `jobbot password --site HOST`). No reset was attempted.")
        return False
    self._no_account = True   # no account (Workday says "wrong email or password" for both): sign up next
    return False


def meets_rules(password, text):
    """Does `password` satisfy the rules a sign-up form lists ("A minimum of 12 characters", "A special character")?"""
    m = re.search(r"minimum of (\d+) characters|at least (\d+) characters|(\d+) or more characters", text, re.I)
    need = int(next(g for g in m.groups() if g)) if m else 8
    checks = [len(password) >= need]
    if re.search(r"uppercase", text, re.I):
        checks.append(bool(re.search(r"[A-Z]", password)))
    if re.search(r"lowercase", text, re.I):
        checks.append(bool(re.search(r"[a-z]", password)))
    if re.search(r"numeric|number|digit", text, re.I):
        checks.append(bool(re.search(r"\d", password)))
    if re.search(r"special character|symbol", text, re.I):
        checks.append(bool(re.search(r"[^A-Za-z0-9]", password)))
    return all(checks)


def press(button, field):
    """Click a submit button that an overlay may cover: normally, then forced, then Enter in the field."""
    for attempt in (lambda: button.click(timeout=5000), lambda: button.click(force=True, timeout=5000),
                    lambda: field.press("Enter")):
        try:
            attempt()
            return
        except Exception:
            continue


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
    stored = credentials.candidates(email, host=host)
    if not stored:
        self._auth_failure = "No password is stored for job-site accounts: run `jobbot password` once."
        return False
    workday = "myworkdayjobs.com" in (host or "")
    passwords = page.locator('input[type="password"]:visible')
    if workday and passwords.count() < 2:
        # After a refused sign-in Workday still shows its Sign In form; its "Create Account" link opens the
        # real sign-up form (password + Verify New Password). Never "create" an account on the sign-in form.
        link = page.locator('[data-automation-id="createAccountLink"]:visible')
        if link.count():
            press(link.first, link.first)
            page.wait_for_timeout(2000)
            sites.wait_rendered(page)
        passwords = page.locator('input[type="password"]:visible')
        if passwords.count() < 2:
            return False
    if passwords.count() == 1 and not re.search(CREATE_RE[1:-1], " ".join(page.locator("h1,h2,h3,button").all_inner_texts()), re.I):
        return False   # a single password box with no sign-up wording is a sign-in form
    if not passwords.count():
        return False
    password = next((pw for pw in stored if meets_rules(pw, page.inner_text("body"))), None)
    if not password:
        self._auth_failure = ("None of your stored passwords meets this site's password rules (shown on its sign-up "
                              "form, e.g. 12+ characters); add one with `jobbot password --add`.")
        return False
    self._signed_up = getattr(self, "_signed_up", set()) | {(host, email)}
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
        cover = page.locator('[data-automation-id="click_filter"][aria-label="Create Account" i]:visible')
        if not cover.count():
            cover = page.locator('[data-automation-id="click_filter"]:visible', has_text="Create Account")
        press(cover.first if cover.count() else page.locator('[data-automation-id="createAccountSubmitButton"]:visible').first,
              passwords.last)
    else:
        button = page.get_by_role("button", name=re.compile(SIGNUP_BUTTON_RE, re.I))
        if not button.count():
            return False
        press(button.first, passwords.last)
    page.wait_for_timeout(3000)
    sites.wait_rendered(page)
    body = page.inner_text("body")
    if re.search(r"already (exists|in use|registered)|account .{0,40}exists", body, re.I):
        self._auth_failure = "An account already exists here with a different password; sign in once yourself, then retry."
        return False
    errors = check_page(page, [], [], []).errors
    said = [t.strip() for t in page.locator('[data-automation-id*="error" i]:visible, [role="alert"]:visible, '
                                            '[id*="error" i]:visible').all_inner_texts() if t.strip()]
    if (errors or said) and page.locator('input[type="password"]:visible').count() >= 2:
        # still on the sign-up form: quote what the site objected to (e.g. "A minimum of 12 characters")
        self._auth_failure = "The site did not accept the new account: " + \
            "; ".join(re.sub(r"\s+", " ", e)[:160] for e in (said or errors)[:2])
        return False
    # The account exists now: the sign-in tried before it (and refused) must not block signing in to it.
    self._auth_attempted = getattr(self, "_auth_attempted", set()) - {(host, email)}
    import time
    self._auth_started = time.time() - 60   # this sign-up's verification email, never an older one
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
        reason += _evidence(page)
        self._wait_for_user(page, reason + " Sign in or create the account in the browser; "
                            "jobbot then handles the verification email and resumes the application.")
    if needs_account(page):
        raise NeedsYou("Sign-in did not complete after credential/email verification attempts.")
    return True
