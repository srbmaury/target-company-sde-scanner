"""Open an application in a real browser, fill it, verify it, and stop for your review.

Before every Next and Submit, jobbot reads back each value it set and checks the
page for empty required fields, validation errors, and CAPTCHAs (verify.py).

With `auto_next` (the default) jobbot moves through multi-page forms on its own
whenever a page passes the check, re-filling once if it does not. It never
submits on its own: on the final page you choose submit, refill, done, or quit.
Sign-in pages, verification links, and CAPTCHAs are always left to you.
"""

import re
import urllib.parse

from .. import paths, tracker
from ..answers import Resolver, real_options
from .fields import BUTTONS_JS, SCAN_JS
from .verify import check_page

MAX_PAGES = 15

SUBMIT_RE = r"^(submit( (my )?application)?|send application|apply|finish|complete application)$"
WORKDAY_SUBMIT_RE = r"^submit$"   # Workday keeps "Apply" buttons around; only Review has "Submit"
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


# --- where to start for each applicant-tracking system --------------------------------

def detect_ats(url, job=None):
    if job and job.get("ats"):
        return job["ats"]
    host = urllib.parse.urlparse(url).netloc
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    if "greenhouse.io" in host or "gh_jid" in query:
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    if "ashbyhq.com" in host:
        return "ashby"
    if "smartrecruiters.com" in host:
        return "smartrecruiters"
    if "myworkdayjobs.com" in host:
        return "workday"
    return "generic"


def start_url(url, ats, job=None):
    parsed = urllib.parse.urlparse(url)
    if ats == "greenhouse":
        if "/embed/job_app" in parsed.path:
            return url
        query = urllib.parse.parse_qs(parsed.query)
        job_id = (query.get("gh_jid") or query.get("token") or [None])[0]
        m = re.search(r"/([^/]+)/jobs/(\d+)", parsed.path)
        board = (job or {}).get("board") or (m.group(1) if m and "greenhouse.io" in parsed.netloc else None)
        job_id = job_id or (m.group(2) if m else None)
        if board and job_id:
            return f"https://job-boards.greenhouse.io/embed/job_app?for={board}&token={job_id}"
        return url
    if ats in ("lever", "lever-eu"):
        return url if url.rstrip("/").endswith("/apply") else url.rstrip("/") + "/apply"
    if ats == "ashby":
        return url if url.rstrip("/").endswith("/application") else url.rstrip("/") + "/application"
    if ats == "workday":
        return re.sub(r"/apply(/.*)?$", "", url)
    return url


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
    def __init__(self, profile, llm, ui, dry_run=False, upload=True, auto_next=True):
        self.profile = profile
        self.llm = llm
        self.ui = ui
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
        opts = dict(user_data_dir=str(paths.BROWSER_PROFILE), headless=False, viewport=None,
                    args=["--start-maximized"])
        try:
            self.ctx = self._pw.chromium.launch_persistent_context(channel="chrome", **opts)
        except Exception:
            self.ctx = self._pw.chromium.launch_persistent_context(**opts)  # needs `playwright install chromium`
        return self

    def __exit__(self, *exc):
        try:
            self.ctx.close()
        finally:
            self._pw.stop()

    # --- one application ---------------------------------------------------------

    def apply(self, job, resume_key):
        url = job["url"]
        ats = detect_ats(url, job)
        self._ats = ats
        resume = self.profile.resumes().get(resume_key)
        page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        page.bring_to_front()
        page.goto(start_url(url, ats, job), wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        self.ui.info(f"{job['company']} — {job['title']}  [{ats}]  resume: {resume_key}")

        self._enter_form(page, ats)
        if resume and self.upload:
            self._upload_resume(page, resume["path"], ats)

        resolver = Resolver(self.profile, self.llm, job=job, resume_key=resume_key, ask=self.ui.ask,
                            memory=self.memory,
                            auto_drafts=bool(self.profile.get("automation.auto_accept_drafts", True)))
        self._consent_approved = bool(self.profile.get("automation.auto_consent", False))
        for step in range(1, MAX_PAGES + 1):
            signed_in = self._ensure_signed_in(page, attempts=1) if ats == "workday" else True
            report = self.fill_page(page, resolver) if signed_in else {"filled": [], "skipped": [], "records": []}
            check = self.verify(page, report)
            if not check.ok and signed_in:
                self.ui.info("Check found problems; re-filling once.")
                report = self._merge(report, self.fill_page(page, resolver))
                check = self.verify(page, report)
            self.ui.report(report, check, step)

            submit_re = WORKDAY_SUBMIT_RE if ats == "workday" else SUBMIT_RE
            can_next = bool(self._buttons(page, NEXT_RE))
            # A page with Next / Save and Continue is never the final step, whatever else it shows.
            can_submit = not can_next and bool(self._buttons(page, submit_re))
            if self.auto_next and check.ok and can_next:
                self.ui.info("All checks passed; moving to the next step.")
                choice = "next"
            else:
                choice = self.ui.next_action(can_submit=can_submit and not self.dry_run, can_next=can_next,
                                             dry_run=self.dry_run, check_ok=check.ok)
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
            return None, "stopped without submitting"
        return None, f"stopped after {MAX_PAGES} pages"

    def verify(self, page, report):
        return check_page(page, report.get("records", []), report.get("skipped", []), self._fields(page))

    @staticmethod
    def _merge(first, second):
        return {"filled": first["filled"] + second["filled"], "skipped": second["skipped"],
                "records": first.get("records", []) + second.get("records", [])}

    @staticmethod
    def _step_marker(page):
        try:
            m = re.search(r"current step \d+ of \d+", page.inner_text("body")[:4000], re.I)
            return m.group(0) if m else ""
        except Exception:
            return ""

    # --- steps ---------------------------------------------------------------------

    def _enter_form(self, page, ats):
        if ats == "smartrecruiters":
            self._click(page, r"^i.?m interested$|^apply now$", wait=4000)
        elif ats == "workday":
            self._click(page, r"^apply$", wait=3000)
            if self._buttons(page, r"^autofill with resume$"):
                self._click(page, r"^autofill with resume$", wait=3000)
            elif self._buttons(page, r"^apply manually$"):
                self._click(page, r"^apply manually$", wait=3000)
            self._workday_settle(page)
            self._ensure_signed_in(page)
        elif ats == "generic" and not [f for f in self._fields(page) if f["kind"] not in ("listbutton", "file")]:
            self.ui.wait_for_user("Open the application form in the browser window, then press Enter here.")

    @staticmethod
    def _workday_settle(page, timeout_ms=15000):
        """Workday renders each step after a 'Loading' placeholder; wait for real content."""
        waited = 0
        while waited < timeout_ms:
            try:
                text = page.inner_text("body")
            except Exception:
                text = ""
            if "Loading" not in text[:3000] and page.locator("input, button[aria-haspopup='listbox']").count() > 1:
                return
            page.wait_for_timeout(1000)
            waited += 1000

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

    def fill_page(self, page, resolver):
        filled, skipped, consents, records = [], [], [], []

        def note(f, label, ans, expected=None, target_id=None, kind=None):
            filled.append((label, ans))
            records.append({"id": target_id or f["id"], "kind": kind or f["kind"], "label": label,
                            "expected": str(expected if expected is not None else getattr(ans, "display", "") or ans)})

        fields = self._fields(page)
        code_boxes = [f for f in fields if f["kind"] == "text" and CODE_RE.search(f["label"] or "")]
        if code_boxes and not all(f["value"] for f in code_boxes):
            code = self.ui.ask_code(code_boxes[0]["label"])
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
            try:
                if kind in ("text", "textarea"):
                    if f["value"]:
                        continue
                    ans = resolver.resolve(label, kind, required=f["required"])
                    if ans:
                        loc = page.locator(f'[data-jobbot-id="{f["id"]}"]')
                        if f["type"] in ("number",):
                            value = re.sub(r"[^\d.]", "", str(ans.value)) or "0"
                        elif re.search(r"phone|mobile", label, re.I) and not has_dial_picker:
                            value = f"{self.profile.get('personal.phone_country_code', '')} {ans.value}".strip()
                        else:
                            value = str(ans.value)
                        loc.fill(value)
                        note(f, label, ans, expected=value)
                    elif f["required"]:
                        skipped.append(label)
                elif kind == "select":
                    opts = f["options"]
                    if f["value"] and not re.match(r"^(|0|-1)$", f["value"]) and real_options([f["value"]]):
                        continue
                    ans = resolver.resolve(label, "choice", options=opts, required=f["required"])
                    if ans:
                        page.locator(f'[data-jobbot-id="{f["id"]}"]').select_option(label=ans.display)
                        note(f, label, ans)
                    elif f["required"]:
                        skipped.append(label)
                elif kind in ("combo", "listbutton"):
                    if kind == "listbutton" and real_options([f["value"]]) and f["value"].lower() not in ("select one",):
                        continue
                    if kind == "combo" and f["value"]:
                        continue
                    if CONSENT_RE.search(label):
                        consents.append(f)
                        continue
                    if self._fill_dropdown(page, f, resolver, note):
                        continue
                    if f["required"]:
                        skipped.append(label)
                elif kind in ("radio", "checkgroup", "yesno"):
                    if any(f["value"]):
                        continue
                    if kind == "checkgroup" and len(f["options"]) <= 2 and all(CONSENT_RE.search(o) for o in f["options"]):
                        consents.append({**f, "id": f["id"].split(",")[0], "label": f"{label} [{f['options'][0]}]"})
                        continue
                    ans = resolver.resolve(label, "choice", options=f["options"], required=f["required"])
                    if ans:
                        ids = f["id"].split(",")
                        page.locator(f'[data-jobbot-id="{ids[ans.value]}"]').click(force=True)
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
                            page.locator(f'[data-jobbot-id="{f["id"]}"]').click(force=True)
                            note(f, label, ans)
            except Exception as e:  # keep going; the review step lists what is left
                skipped.append(f"{label} (error: {type(e).__name__})")

        if consents and not self._consent_approved:
            self._consent_approved = self.ui.confirm(
                "Tick consent boxes for this application? (applies to every page of it)\n  - "
                + "\n  - ".join(c["label"][:160] for c in consents))
        if consents and self._consent_approved:
            for c in consents:
                page.locator(f'[data-jobbot-id="{c["id"]}"]').click(force=True)
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

    def _fill_dropdown(self, page, f, resolver, note):
        """React-select comboboxes, autocomplete boxes, Workday listbox buttons and Workday's
        searchable, nested "prompt" lists (category -> sub-option)."""
        label = f["label"]
        loc = page.locator(f'[data-jobbot-id="{f["id"]}"]')
        loc.click()
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
        note(f, label, ans if len(path) == 1 else " › ".join(path), expected=path[-1])
        return True

    def _search_options(self, page, loc, resolver, label):
        """Type the answer we would give into the box and return the matching options."""
        guess = resolver.resolve(label, "text", required=False)
        if not guess:
            return []
        loc.fill(str(guess.value).split(",")[0].split("(")[0].strip())
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
