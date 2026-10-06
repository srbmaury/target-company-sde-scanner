"""Open an application in a real browser, fill it, verify it, and stop for your review.

Before every Next and Submit, jobbot reads back each value it set and checks the
page for empty required fields, validation errors, and CAPTCHAs (verify.py).

With `auto_next` (the default) jobbot moves through multi-page forms on its own
whenever a page passes the check, re-filling once if it does not. It never
submits on its own: on the final page you choose submit, refill, done, or quit.
Sign-in pages, verification links, and CAPTCHAs are always left to you.
"""

import os
import re
import time
import urllib.parse

from .. import paths, tracker
from ..answers import Resolver, real_options
from . import sites
from .fields import BUTTONS_JS, SCAN_JS
from .sites import detect_ats, start_url
from .unattended import NeedsYou, UnattendedUI
from .verify import check_page, matches

MAX_ROUNDS = 5           # review rounds per page before asking you
TRUSTED = ("profile", "rule", "remembered")   # sources allowed to overwrite a value the site pre-filled

MAX_PAGES = 15

SUBMIT_RE = r"^(submit( (my )?application)?|send application|apply|finish|complete application)$"
WORKDAY_SUBMIT_RE = r"^submit$"   # Workday keeps "Apply" buttons around; only Review has "Submit"
APPLY_RE = r"^(apply( now| online| here)?|apply (for|to) (this|the) (job|position|role)|start (your )?application|i.?m interested|submit (your )?(resume|cv))$"
NEXT_RE = r"^(next|continue|save and continue|save & continue|proceed)$"
CONFIRM_RE = re.compile(
    r"thank(s| you) for (applying|your (application|interest))|application (has been |was )?(submitted|received)|"
    r"successfully (submitted|applied)|we.ve received your application|congratulations", re.I)
# Honeypot fields exist to catch bots; filling one gets the application flagged.
TRAP_RE = re.compile(r"robots? only|for robots|do not (fill|enter)|leave (this )?(field )?(blank|empty)|honeypot", re.I)
ACCOUNT_STEP_RE = re.compile(r"current step \d+ of \d+\s*\|?\s*create account\s*/\s*sign in", re.I)
CODE_RE = re.compile(r"verification code|security code|one.?time (pass)?code|\botp\b|enter the \d*.?character code|"
                     r"code (was )?sent to|confirmation code", re.I)
CONSENT_RE = re.compile(r"consent|privacy|acknowledge|agree|terms|certify|^i confirm|confirm the statement|declare", re.I)


def browser_profile_holder():
    """PID of a live Chrome holding jobbot's browser profile, or None.

    Chrome's SingletonLock is a symlink to "<hostname>-<pid>"; a stale lock from a crash
    points at a PID that no longer exists and is ignored.
    """
    import os

    lock = paths.BROWSER_PROFILE / "SingletonLock"
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


class Session:
    def __init__(self, profile, llm, ui, dry_run=False, upload=True, auto_next=True, unattended=False):
        self.profile = profile
        self.llm = llm
        self.unattended = unattended
        self.ui = UnattendedUI(ui) if unattended else ui
        self.ready = {}   # url -> (page, ats): unattended applications filled, checked and waiting for your Submit
        self.dry_run = dry_run
        self.upload = upload
        self.auto_next = auto_next
        self._ats = None
        self._consent_approved = False   # one yes covers every consent box in the current application
        from ..memory import Memory

        self.memory = Memory.for_profile(profile)
        self._pw = None
        self.ctx = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        paths.ensure_home()
        holder = browser_profile_holder()
        if holder:
            raise SystemExit(
                f"jobbot's browser is already open from another run (process {holder}). "
                f"Finish or quit that run (press q there), or stop it with: kill {holder}")
        self._pw = sync_playwright().start()
        # Sign-in pages (Microsoft, Google) refuse browsers that announce automation, which blocks you from
        # signing in or creating an account yourself in this window. Launch it like a normal Chrome instead.
        # JOBBOT_HEADLESS=1 runs without a window (tests and CI); you normally watch the window.
        opts = dict(user_data_dir=str(paths.BROWSER_PROFILE), headless=os.environ.get("JOBBOT_HEADLESS") == "1",
                    viewport=None,
                    args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
                    ignore_default_args=["--enable-automation"])
        try:
            self.ctx = self._pw.chromium.launch_persistent_context(channel="chrome", **opts)
        except Exception:
            self.ctx = self._pw.chromium.launch_persistent_context(**opts)  # needs `playwright install chromium`
        # A field that is hidden or covered (e.g. a follow-up shown only after "Yes") would otherwise make each
        # click or fill wait Playwright's default 30 s, in every review round.
        self.ctx.set_default_timeout(10000)
        self.ctx.set_default_navigation_timeout(45000)
        return self

    def __exit__(self, *exc):
        try:
            self.ctx.close()
        finally:
            self._pw.stop()

    # --- one application ---------------------------------------------------------

    def apply(self, job, resume_key):
        if not self.unattended:
            return self._apply(job, resume_key)
        self.ui.unanswered = []
        self._page = None
        try:
            status, note = self._apply(job, resume_key)
        except Exception:
            self._close(self._page)
            raise
        if status == "ready":
            self.ready[job["url"]] = (self._page, self._ats)
            return status, note
        self._close(self._page)
        if self.ui.unanswered:
            raise NeedsYou("unanswered: " + "; ".join(dict.fromkeys(self.ui.unanswered)))
        return status, note

    @staticmethod
    def _close(page):
        try:
            if page and not page.is_closed():
                page.close()
        except Exception:
            pass

    def submit_ready(self, url):
        """Submit an application held open by an unattended run. Returns (status, note)."""
        page, ats = self.ready.pop(url)
        page.bring_to_front()
        self._click(page, WORKDAY_SUBMIT_RE if ats == "workday" else SUBMIT_RE)
        page.wait_for_timeout(6000)
        confirmed = self._confirmation(page)
        if confirmed:
            self._close(page)
            return "applied", confirmed
        after = check_page(page, [], [], [])
        if after.errors or after.captcha:
            self.ready[url] = (page, ats)   # still open: fix it in the tab and try again, or submit it yourself
            return None, "the site did not accept it: " + "; ".join(after.lines()[:2])
        return "applied", "submitted; no confirmation text seen, check the tab"

    def discard_ready(self, url):
        page, _ = self.ready.pop(url, (None, None))
        self._close(page)

    def _apply(self, job, resume_key):
        url = job["url"]
        self._started = time.time()   # verification emails older than this application are ignored
        ats = detect_ats(url, job)
        self._ats = ats
        resume = self.profile.resumes().get(resume_key)
        if self.unattended:   # each application in its own tab, so finished ones can wait for your Submit
            blank = [p for p in self.ctx.pages if p.url == "about:blank" and p not in [r[0] for r in self.ready.values()]]
            page = blank[0] if blank else self.ctx.new_page()
            self._page = page
        else:
            page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        page.bring_to_front()
        page.goto(start_url(url, ats, job), wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        self.ui.info(f"{job['company']} — {job['title']}  [{ats}]  resume: {resume_key}")

        entered = self._enter_form(page, ats) or page
        if self.unattended and entered is not page:
            self._close(page)   # Apply opened the form in a new tab: don't leave the posting behind
        page = entered
        if self.unattended:
            self._page = page
        if resume and self.upload:
            self._upload_resume(page, resume["path"], ats)

        resolver = Resolver(self.profile, self.llm, job=job, resume_key=resume_key, ask=self.ui.ask,
                            memory=self.memory,
                            auto_drafts=bool(self.profile.get("automation.auto_accept_drafts", True)))
        self._consent_approved = bool(self.profile.get("automation.auto_consent", False))
        self._mine = set()   # labels jobbot has filled or confirmed during this application
        self._broken = set()  # labels whose field could not be filled; not retried in later review rounds
        self._log(f"=== {job['company']} — {job['title']} [{ats}] {url} resume={resume_key}")
        for step in range(1, MAX_PAGES + 1):
            signed_in = self._ensure_signed_in(page, attempts=1) if ats == "workday" else True
            report, check, rounds = self.review_page(page, resolver, step) if signed_in else \
                ({"filled": [], "skipped": [], "records": []}, self.verify(page, {}), 0)
            self.ui.report(report, check, step)
            if rounds:
                self.ui.info(f"Reviewed page {step} in {rounds} round(s); "
                             + ("the last round changed nothing." if check.ok else "problems remain."))

            submit_re = WORKDAY_SUBMIT_RE if ats == "workday" else SUBMIT_RE
            can_next = bool(self._buttons(page, NEXT_RE))
            # A page with Next / Save and Continue is never the final step, whatever else it shows.
            can_submit = not can_next and bool(self._buttons(page, submit_re))
            if self.auto_next and check.ok and can_next:
                self.ui.info("All checks passed; moving to the next step.")
                choice = "next"
            else:
                choice = self.ui.next_action(can_submit=can_submit and not self.dry_run, can_next=can_next,
                                             dry_run=self.dry_run, check_ok=check.ok, final_page=can_submit)
            if choice == "submit" and not check.ok and not self.ui.confirm(
                    "The check still shows problems. Submit anyway?"):
                continue

            if choice == "refill":
                continue
            if choice == "next":
                before = page.url, self._step_marker(page)
                self._click(page, NEXT_RE)
                page.wait_for_timeout(3500)
                if ats == "workday":
                    self._workday_settle(page)
                if (page.url, self._step_marker(page)) == before:
                    after = check_page(page, [], [], [])
                    if after.errors:
                        self.ui.warn("The site kept us on the same step: " + "; ".join(after.lines()[:3]))
                continue
            if choice == "submit":
                self._click(page, submit_re)
                page.wait_for_timeout(6000)
                confirmed = self._confirmation(page)
                if confirmed:
                    self.ui.info(f"Confirmation seen: “{confirmed}”")
                    return "applied", confirmed
                after = check_page(page, [], [], [])
                if after.errors or after.captcha:
                    self.ui.warn("The site did not accept the submission: " + "; ".join(after.lines()[:3]))
                    continue
                if self.ui.confirm("No confirmation text detected. Did the application go through?"):
                    return "applied", "submitted; confirmed by you"
                continue
            if choice == "done":
                return "applied", "you submitted it in the browser"
            if choice == "hold":
                if self.dry_run:
                    return None, "dry run: ready to submit"
                return "ready", "filled and checked; waiting for your Submit"
            if self.unattended and not check.ok:
                self.ui.unanswered.extend(check.lines()[:3])
            return None, "stopped without submitting"
        return None, f"stopped after {MAX_PAGES} pages"

    def review_page(self, page, resolver, step):
        """Fill, verify and correct until a whole round changes nothing and the check passes.

        Each round re-reads the page. Values the site pre-filled (e.g. Workday's resume autofill)
        are overwritten when your profile says otherwise; values jobbot set are re-filled only if
        the check shows they did not stick. Stops after MAX_ROUNDS rounds.
        """
        total = {"filled": [], "skipped": [], "records": []}
        force, check = set(), None
        for rnd in range(1, MAX_ROUNDS + 1):
            rep = self.fill_page(page, resolver, force=force)
            total = self._merge(total, rep)
            page.wait_for_timeout(500)
            check = self.verify(page, total)
            changes = len(rep["filled"])
            self._log(f"page {step} round {rnd}: {changes} change(s)", *[f"  set {l} = {a}" for l, a in rep["filled"]],
                      *[f"  ! {line}" for line in check.lines()])
            force = {m[0] for m in check.mismatches}
            for label in force:
                self._mine.discard(label)
            if changes == 0 and check.ok:
                return total, check, rnd
            if changes == 0 and not force:
                return total, check, rnd   # nothing left that jobbot can change by itself
        return total, check, MAX_ROUNDS

    def _log(self, *lines):
        try:
            import datetime as _dt

            logdir = paths.HOME / "logs"
            logdir.mkdir(parents=True, exist_ok=True)
            stamp = _dt.datetime.now().strftime("%H:%M:%S")
            with open(logdir / f"{_dt.date.today().isoformat()}.log", "a", encoding="utf-8") as fh:
                for line in lines:
                    fh.write(f"{stamp} {line}\n")
        except OSError:
            pass

    def _trusted(self, resolver, label, kind, options=None):
        """Your profile's answer for a field, from your own answers and rules only (no model, no asking)."""
        ans = resolver.resolve(label, kind, options=options, required=False, quick=True)
        return ans if ans is not None and ans.source in TRUSTED else None

    def verify(self, page, report):
        return check_page(page, report.get("records", []), report.get("skipped", []), self._fields(page))

    @staticmethod
    def _merge(first, second):
        records = {r["id"]: r for r in first.get("records", []) + second.get("records", [])}
        return {"filled": first["filled"] + second["filled"], "skipped": second["skipped"],
                "records": list(records.values())}

    @staticmethod
    def _step_marker(page):
        try:
            m = re.search(r"current step \d+ of \d+", page.inner_text("body")[:4000], re.I)
            return m.group(0) if m else ""
        except Exception:
            return ""

    # --- steps ---------------------------------------------------------------------

    def _enter_form(self, page, ats):
        if ats == "greenhouse" and not self._fields(page):
            # Company careers pages embed the Greenhouse form in an iframe; open the form itself.
            frame = next((f for f in page.frames if "greenhouse.io/embed/job_app" in f.url), None)
            if frame:
                page.goto(frame.url, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
        if ats == "smartrecruiters":
            self._click(page, r"^i.?m interested$|^apply now$", wait=4000)
        elif ats == "workday":
            # Workday draws the posting late: wait for its Apply button, then for the start-application choice.
            if self._wait_for_button(page, r"^apply$", 20000):
                self._click(page, r"^apply$")
                choice = self._wait_for_button(page, r"^(autofill with resume|apply manually)$", 10000)
                if choice:
                    pick = r"^autofill with resume$" if any(re.match(r"autofill", c["text"], re.I) for c in choice) \
                        else r"^apply manually$"
                    self._click(page, pick, wait=2000)
            self._workday_settle(page)
            self._ensure_signed_in(page)
        elif ats == "generic" and not self._form_fields(page):
            page = self._open_application(page)
            if self._signin_page(page):
                self.ui.wait_for_user("This site needs you to sign in (or create an account) in the browser "
                                      "window; jobbot never handles passwords. When the application form "
                                      "appears, press Enter here.")
            elif not self._form_fields(page):
                self.ui.wait_for_user("Open the application form in the browser window, then press Enter here.")
            return page

    def _form_fields(self, page):
        """Fields that belong to an application, not to a job page's search box or language picker."""
        return [f for f in self._fields(page) if f["kind"] not in ("listbutton", "file")
                and not re.search(r"search|keyword|language|locale|subscribe|newsletter", f["label"] or "", re.I)]

    def _open_application(self, page):
        """On a job posting, click its Apply control; follow it into a new tab if it opens one."""
        hits = page.evaluate(BUTTONS_JS, [APPLY_RE, True])
        if not hits:
            return page
        target = page.locator(f'[data-jobbot-btn="{hits[0]["id"]}"]')
        try:
            with self.ctx.expect_page(timeout=4000) as popup:
                target.click(timeout=8000)
            page = popup.value
            page.bring_to_front()
        except Exception:
            pass   # same tab (or nothing opened)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(3000)
        return page

    _signin_page = staticmethod(sites.signin_page)

    def _wait_for_button(self, page, pattern, timeout_ms):
        """Poll for a button matching pattern; returns the matches ([] after timeout_ms)."""
        waited = 0
        while True:
            hits = self._buttons(page, pattern)
            if hits or waited >= timeout_ms:
                return hits
            page.wait_for_timeout(500)
            waited += 500

    _workday_settle = staticmethod(sites.workday_settle)

    def _needs_account(self, page):
        try:
            text = re.sub(r"\s+", " ", page.inner_text("body")[:4000])
        except Exception:
            return False
        return bool(ACCOUNT_STEP_RE.search(text) or page.locator("input[type=password]:visible").count())

    def _ensure_signed_in(self, page, attempts=2):
        """Pause for the user to sign in. Returns True once the account step is gone."""
        for _ in range(attempts):
            if not self._needs_account(page):
                return True
            self.ui.wait_for_user(
                "This employer's Workday needs an account. In the browser window, sign in (or create an account "
                "with your own password; jobbot never handles passwords). When the application form appears, "
                "press Enter here.")
            page.wait_for_timeout(1500)
            self._workday_settle(page)
        if self._needs_account(page):
            self.ui.warn("Still on the sign-in step, so jobbot is not filling anything there. "
                         "Sign in, then choose [r]efill.")
            return False
        return True

    def _upload_resume(self, page, path, ats):
        inputs = [f for f in self._fields(page) if f["kind"] == "file"]
        if not inputs:
            self.ui.warn("No file upload field found; attach your resume in the browser if the form needs one.")
            return
        target = next((f for f in inputs if re.search(r"resume|cv", f["label"] + " " + f.get("name", ""), re.I)), inputs[0])
        page.locator(f'[data-jobbot-id="{target["id"]}"]').set_input_files(str(path))
        # Greenhouse and Workday parse the resume and rewrite fields; fill only after they finish.
        page.wait_for_timeout(8000 if ats in ("greenhouse", "workday") else 3000)
        if ats == "workday" and self._buttons(page, NEXT_RE):
            self._click(page, NEXT_RE, wait=4000)
        self.ui.info(f"Attached {path.name}")

    def fill_page(self, page, resolver, force=()):
        filled, skipped, consents, records = [], [], [], []
        mine = getattr(self, "_mine", set())

        def note(f, label, ans, expected=None, target_id=None, kind=None, was=None):
            mine.add(label)
            filled.append((f"{label} (was “{was[:30]}”)" if was else label, ans))
            records.append({"id": target_id or f["id"], "kind": kind or f["kind"], "label": label,
                            "expected": str(expected if expected is not None else getattr(ans, "display", "") or ans)})

        fields = self._fields(page)
        code_boxes = [f for f in fields if f["kind"] == "text" and CODE_RE.search(f["label"] or "")]
        if code_boxes and not all(f["value"] for f in code_boxes):
            code = self._code_from_email(page) or self.ui.ask_code(code_boxes[0]["label"])
            if code:
                code = re.sub(r"\s+", "", code)
                single = len(code_boxes) > 1 and all(f.get("maxlength") == 1 for f in code_boxes)
                if single:
                    for f, ch in zip(code_boxes, code):
                        page.locator(f'[data-jobbot-id="{f["id"]}"]').fill(ch)
                else:
                    page.locator(f'[data-jobbot-id="{code_boxes[0]["id"]}"]').fill(code)
                filled.append(("verification code", "entered (you)"))
            else:
                skipped.append("verification code from your email")
        code_ids = {f["id"] for f in code_boxes}
        fields = [f for f in fields if f["id"] not in code_ids]
        has_dial_picker = any(re.search(r"country|dial|code", x["label"], re.I) and x["kind"] in ("combo", "select", "listbutton")
                              for x in fields)
        for f in fields:
            kind, label = f["kind"], f["label"] or "(unlabelled field)"
            if kind == "file" or TRAP_RE.search(label):
                continue
            if kind == "listbutton" and not f["label"]:
                continue  # Workday's language picker and similar chrome
            if label in getattr(self, "_broken", ()):
                if f["required"]:
                    skipped.append(f"{label} (could not be filled; please check it)")
                continue
            try:
                if kind in ("text", "textarea"):
                    was = None
                    if f["value"] and label not in force:
                        if label in mine:
                            continue
                        ans = self._trusted(resolver, label, kind)
                        if ans is None or matches(self._text_value(f, label, ans, has_dial_picker), f["value"], "text"):
                            mine.add(label)
                            continue
                        was = f["value"]  # pre-filled by the site and wrong: correct it
                    else:
                        ans = resolver.resolve(label, kind, required=f["required"])
                    if ans:
                        loc = page.locator(f'[data-jobbot-id="{f["id"]}"]')
                        value = self._text_value(f, label, ans, has_dial_picker)
                        loc.fill(value)
                        note(f, label, ans, expected=value, was=was)
                    elif f["required"]:
                        skipped.append(label)
                elif kind == "select":
                    opts = f["options"]
                    was = None
                    current = f.get("text") or ""
                    if current and real_options([current]) and label not in force:
                        if label in mine:
                            continue
                        ans = self._trusted(resolver, label, "choice", opts)
                        if ans is None or ans.display == current:
                            mine.add(label)
                            continue
                        was = current
                    else:
                        ans = resolver.resolve(label, "choice", options=opts, required=f["required"])
                    if ans:
                        page.locator(f'[data-jobbot-id="{f["id"]}"]').select_option(label=ans.display)
                        note(f, label, ans, was=was)
                    elif f["required"]:
                        skipped.append(label)
                elif kind in ("combo", "listbutton"):
                    if kind == "listbutton" and real_options([f["value"]]) and f["value"].lower() not in ("select one",) \
                            and label not in force:
                        if label in mine:
                            continue
                        want = self._trusted(resolver, label, "text")
                        if want is None or matches(str(want.value), f["value"], "combo"):
                            mine.add(label)
                            continue
                        # pre-filled with something your profile disagrees with: choose again below
                    elif kind == "combo" and (f["value"] or f.get("shown") or label in mine) and label not in force:
                        # Already set (react-select shows its choice outside the input, so the value can
                        # read empty): choose again only when the check says it did not stick.
                        continue
                    if CONSENT_RE.search(label):
                        consents.append(f)
                        continue
                    if self._fill_dropdown(page, f, resolver, note):
                        continue
                    if f["required"]:
                        skipped.append(label)
                elif kind in ("radio", "checkgroup", "yesno"):
                    if any(f["value"]) and label not in force:
                        if label in mine or kind == "checkgroup":
                            continue
                        want = self._trusted(resolver, label, "choice", f["options"])
                        if want is None or f["value"][want.value]:
                            mine.add(label)
                            continue
                        ids = f["id"].split(",")
                        self._tick(page, ids[want.value])
                        was = next((o for o, v in zip(f["options"], f["value"]) if v), "")
                        note(f, label, want, target_id=ids[want.value], was=was)
                        continue
                    if kind == "checkgroup" and len(f["options"]) <= 2 and all(CONSENT_RE.search(o) for o in f["options"]):
                        consents.append({**f, "id": f["id"].split(",")[0], "label": f"{label} [{f['options'][0]}]"})
                        continue
                    ans = resolver.resolve(label, "choice", options=f["options"], required=f["required"])
                    if ans:
                        ids = f["id"].split(",")
                        self._tick(page, ids[ans.value])
                        note(f, label, ans, target_id=ids[ans.value])
                    elif f["required"]:
                        skipped.append(label)
                elif kind == "checkbox":
                    if f["value"] and f["value"][0]:
                        continue
                    if CONSENT_RE.search(label):
                        consents.append(f)
                    else:
                        ans = resolver.resolve(label, "choice", options=["Yes", "No"], required=f["required"])
                        if ans and ans.display == "Yes":
                            self._tick(page, f["id"])
                            note(f, label, ans)
            except Exception as e:  # keep going; the review step lists what is left
                skipped.append(f"{label} (error: {type(e).__name__})")
                getattr(self, "_broken", set()).add(label)
                try:
                    page.keyboard.press("Escape")   # close a menu the failed attempt may have opened
                except Exception:
                    pass

        if consents and not self._consent_approved:
            self._consent_approved = self.ui.confirm(
                "Tick consent boxes for this application? (applies to every page of it)\n  - "
                + "\n  - ".join(c["label"][:160] for c in consents))
        if consents and self._consent_approved:
            for c in consents:
                self._tick(page, c["id"])
                if c["kind"] in ("combo", "listbutton"):
                    page.wait_for_timeout(500)
                    opts = page.locator('[role="option"]:visible')
                    texts = opts.all_inner_texts()
                    idx = next((i for i, t in enumerate(texts) if CONSENT_RE.search(t) or re.match(r"\s*(yes|accept)", t, re.I)), None)
                    if idx is None:
                        page.keyboard.press("Escape")
                        skipped.append(c["label"][:110])
                        continue
                    opts.nth(idx).click()
                    note(c, c["label"][:80], "confirmed (you approved)", expected=texts[idx].strip())
                else:
                    note(c, c["label"][:80], "ticked (you approved)", expected="checked", kind="consent")
        return {"filled": filled, "skipped": skipped, "records": records}

    def _code_from_email(self, page):
        """Read a verification code from your latest email (Gmail, read-only), if Gmail is connected."""
        if not self.profile.get("automation.read_codes_from_email", True):
            return None
        try:
            from .. import gmail
            if not gmail.is_connected():
                return None
            host = urllib.parse.urlparse(page.url).netloc.split(".")
            hint = next((p for p in host if p not in ("www", "careers", "jobs", "apply", "com", "in", "co", "io",
                                                        "myworkdayjobs") and not re.fullmatch(r"wd\d+", p)), "")
            self.ui.info("Waiting for the verification email (up to 90 s)…")
            code = gmail.latest_code(getattr(self, "_started", 0) - 120, hint=hint, wait=90)
        except Exception as e:   # Gmail unreachable or token revoked: fall back to asking
            self.ui.warn(f"Could not read the code from email ({type(e).__name__}); please enter it.")
            return None
        if code:
            self.ui.info(f"Verification code {code} read from your latest email.")
        return code

    @staticmethod
    def _tick(page, field_id):
        """Click a checkbox or radio. Many sites hide the real input off-screen behind a styled label
        (Oracle, for one), where even a forced click fails: try the label, then the input, then a click
        from inside the page."""
        loc = page.locator(f'[data-jobbot-id="{field_id}"]')
        label = loc.evaluate("""el => { const l = (el.labels && el.labels[0])
            || document.getElementById((el.getAttribute('aria-labelledby') || '').split(' ')[0]);
            if (!l || !l.getClientRects().length) return null;
            const id = 'l' + Math.random().toString(36).slice(2, 9); l.setAttribute('data-jobbot-label', id); return id; }""")
        attempts = ([lambda: page.locator(f'[data-jobbot-label="{label}"]').click(timeout=3000)] if label else []) + [
            lambda: loc.click(force=True, timeout=3000), lambda: loc.evaluate("el => el.click()")]
        before = loc.is_checked()
        for attempt in attempts:
            try:
                attempt()
            except Exception:
                continue
            if loc.is_checked() != before:
                return
        raise RuntimeError("could not tick this box")

    def _text_value(self, f, label, ans, has_dial_picker):
        if f.get("type") == "number":
            return re.sub(r"[^\d.]", "", str(ans.value)) or "0"
        if re.search(r"phone|mobile", label, re.I) and not has_dial_picker and re.fullmatch(r"[\d\s-]{6,}", str(ans.value)):
            return f"{self.profile.get('personal.phone_country_code', '')} {ans.value}".strip()
        return str(ans.value)

    def _fill_dropdown(self, page, f, resolver, note):
        """React-select comboboxes, autocomplete boxes, Workday listbox buttons and Workday's
        searchable, nested "prompt" lists (category -> sub-option)."""
        label = f["label"]
        loc = page.locator(f'[data-jobbot-id="{f["id"]}"]')
        self._open_dropdown(loc)
        page.wait_for_timeout(700)
        options = self._visible_options(page)
        if not options:
            loc.press("ArrowDown")  # some menus open only on a key press
            page.wait_for_timeout(600)
            options = self._visible_options(page)
        typed, path, ans = False, [], None
        for _ in range(3):  # Workday nests up to a couple of levels
            if not options and f["kind"] == "combo" and not typed:
                options, typed = self._search_options(page, loc, resolver, label), True
            if not options:
                break
            ans = resolver.resolve(label, "choice", options=options, required=f["required"], quick=True)
            if ans is None and f["kind"] == "combo" and not typed:
                # The answer may just not be visible yet (long lists): search for it first.
                found = self._search_options(page, loc, resolver, label)
                typed = True
                options = found or self._reopen(page, loc) or options
            if ans is None and typed and getattr(self, "_typed", ""):
                # an autocomplete answered our own search ("Hyderabad" -> "Hyderabad, Telangana, India")
                hit = next((i for i, o in enumerate(options) if self._typed.lower() in o.lower()), None)
                if hit is not None:
                    from ..answers import Answer
                    ans = Answer(hit, "rule", options[hit])
            if ans is None:
                ans = resolver.resolve(label, "choice", options=options, required=f["required"])
            if ans is None:
                break
            chosen = options[ans.value]
            self._click_option(page, chosen, ans.value)
            path.append(chosen)
            page.wait_for_timeout(900)
            after = self._visible_options(page)
            if not after or after == options or chosen in after:
                break  # a leaf was selected (the list closed or stayed the same)
            options = after  # a category opened a sub-list; choose again inside it
        if self._visible_options(page):
            page.keyboard.press("Escape")
        if not path:
            return False
        note(f, label, ans if len(path) == 1 and ans is not None else " › ".join(path), expected=path[-1])
        return True

    @staticmethod
    def _open_dropdown(loc):
        """Open a dropdown whose input may be covered by the widget's own overlay (react-select and
        similar): a normal click, then a forced one, then focus and the keyboard."""
        for attempt in (lambda: loc.click(timeout=3000), lambda: loc.click(force=True, timeout=3000),
                        lambda: (loc.focus(), loc.press("ArrowDown"))):
            try:
                attempt()
                return
            except Exception:
                continue
        raise RuntimeError("could not open this dropdown")

    def _search_options(self, page, loc, resolver, label):
        """Type the answer we would give into the box and return the matching options."""
        guess = resolver.resolve(label, "text", required=False)
        if not guess:
            return []
        self._typed = str(guess.value).split(",")[0].split("(")[0].strip()
        loc.fill(self._typed)
        if self._ats == "workday":
            loc.press("Enter")  # Workday searches on Enter; react-select would pick the first hit
        page.wait_for_timeout(1800)
        return self._visible_options(page)

    def _reopen(self, page, loc):
        """Clear a search that found nothing and bring back the full list."""
        try:
            loc.fill("")
            if self._ats == "workday":
                loc.press("Enter")
            loc.click()
            page.wait_for_timeout(900)
        except Exception:
            return []
        return self._visible_options(page)

    @staticmethod
    def _click_option(page, text, index):
        try:
            page.get_by_role("option", name=text, exact=True).first.click(timeout=4000)
        except Exception:
            page.locator('[role="option"]:visible').nth(index).click(timeout=4000)

    @staticmethod
    def _visible_options(page):
        return [t.strip() for t in page.locator('[role="option"]:visible').all_inner_texts()]

    @staticmethod
    def _fields(page):
        return page.evaluate(SCAN_JS)

    @staticmethod
    def _buttons(page, pattern):
        return page.evaluate(BUTTONS_JS, pattern)

    def _click(self, page, pattern, wait=0):
        hits = self._buttons(page, pattern)
        if not hits:
            return False
        page.locator(f'[data-jobbot-btn="{hits[-1]["id"]}"]').click()
        if wait:
            page.wait_for_timeout(wait)
        return True

    @staticmethod
    def _confirmation(page):
        try:
            text = page.inner_text("body")[:6000]
        except Exception:
            return None
        m = CONFIRM_RE.search(text)
        return m.group(0) if m else None


def record(conn, job, status, note, resume_key):
    return tracker.add_application(conn, job["company"], job["title"], url=job["url"], location=job.get("location"),
                                   status=status, resume=resume_key, source="jobbot", notes=note)
