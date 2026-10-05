"""Open an application in a real browser, fill it, and stop for your review.

jobbot never submits on its own. After filling a page it prints what it did and
waits for you to choose: submit, go to the next step, refill, mark done, or quit.
CAPTCHAs, logins, and anything it could not answer are left to you in the
browser window.
"""

import re
import urllib.parse

from .. import paths, tracker
from ..answers import Resolver, real_options
from .fields import BUTTONS_JS, SCAN_JS

SUBMIT_RE = r"^(submit( (my )?application)?|send application|apply|finish|complete application)$"
NEXT_RE = r"^(next|continue|save and continue|save & continue|proceed)$"
CONFIRM_RE = re.compile(
    r"thank(s| you) for (applying|your (application|interest))|application (has been |was )?(submitted|received)|"
    r"successfully (submitted|applied)|we.ve received your application|congratulations", re.I)
# Honeypot fields exist to catch bots; filling one gets the application flagged.
TRAP_RE = re.compile(r"robots? only|for robots|do not (fill|enter)|leave (this )?(field )?(blank|empty)|honeypot", re.I)
ACCOUNT_STEP_RE = re.compile(r"current step \d+ of \d+\s*\|?\s*create account\s*/\s*sign in", re.I)
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


class Session:
    def __init__(self, profile, llm, ui, dry_run=False, upload=True):
        self.profile = profile
        self.llm = llm
        self.ui = ui
        self.dry_run = dry_run
        self.upload = upload
        self._pw = None
        self.ctx = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        paths.ensure_home()
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
        resume = self.profile.resumes().get(resume_key)
        page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        page.bring_to_front()
        page.goto(start_url(url, ats, job), wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        self.ui.info(f"{job['company']} — {job['title']}  [{ats}]  resume: {resume_key}")

        self._enter_form(page, ats)
        if resume and self.upload:
            self._upload_resume(page, resume["path"], ats)

        resolver = Resolver(self.profile, self.llm, job=job, resume_key=resume_key, ask=self.ui.ask)
        while True:
            signed_in = self._ensure_signed_in(page, attempts=1) if ats == "workday" else True
            report = self.fill_page(page, resolver) if signed_in else {"filled": [], "skipped": []}
            self.ui.report(report)
            choice = self.ui.next_action(
                can_submit=bool(self._buttons(page, SUBMIT_RE)) and not self.dry_run,
                can_next=bool(self._buttons(page, NEXT_RE)),
                dry_run=self.dry_run,
            )
            if choice == "refill":
                continue
            if choice == "next":
                self._click(page, NEXT_RE)
                page.wait_for_timeout(3500)
                if ats == "workday":
                    self._workday_settle(page)
                continue
            if choice == "submit":
                self._click(page, SUBMIT_RE)
                page.wait_for_timeout(6000)
                confirmed = self._confirmation(page)
                if confirmed:
                    self.ui.info(f"Confirmation seen: “{confirmed}”")
                    return "applied", confirmed
                if self.ui.confirm("No confirmation text detected. Did the application go through?"):
                    return "applied", "submitted; confirmed by you"
                continue
            if choice == "done":
                return "applied", "you submitted it in the browser"
            return None, "stopped without submitting"

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
        elif ats == "generic":
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
        filled, skipped, consents = [], [], []
        fields = self._fields(page)
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
                            loc.fill(re.sub(r"[^\d.]", "", str(ans.value)) or "0")
                        elif re.search(r"phone|mobile", label, re.I) and not has_dial_picker:
                            code = self.profile.get("personal.phone_country_code", "")
                            loc.fill(f"{code} {ans.value}".strip())
                        else:
                            loc.fill(str(ans.value))
                        filled.append((label, ans))
                    elif f["required"]:
                        skipped.append(label)
                elif kind == "select":
                    opts = f["options"]
                    if f["value"] and not re.match(r"^(|0|-1)$", f["value"]) and real_options([f["value"]]):
                        continue
                    ans = resolver.resolve(label, "choice", options=opts, required=f["required"])
                    if ans:
                        page.locator(f'[data-jobbot-id="{f["id"]}"]').select_option(label=ans.display)
                        filled.append((label, ans))
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
                    if self._fill_dropdown(page, f, resolver, filled):
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
                        filled.append((label, ans))
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
                            filled.append((label, ans))
            except Exception as e:  # keep going; the review step lists what is left
                skipped.append(f"{label} (error: {type(e).__name__})")

        if consents and self.ui.confirm(
                "Tick these consent boxes?\n  - " + "\n  - ".join(c["label"][:160] for c in consents)):
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
                filled.append((c["label"][:80], "confirmed (you approved)"))
        return {"filled": filled, "skipped": skipped}

    def _fill_dropdown(self, page, f, resolver, filled):
        """React-select comboboxes, autocomplete boxes, and Workday listbox buttons."""
        label = f["label"]
        loc = page.locator(f'[data-jobbot-id="{f["id"]}"]')
        loc.click()
        page.wait_for_timeout(600)
        options = self._visible_options(page)
        typed = False
        if not options and f["kind"] == "combo":
            # Autocomplete: type first, then read suggestions.
            guess = resolver.resolve(label, "text", required=f["required"])
            if not guess:
                page.keyboard.press("Escape")
                return False
            loc.fill(str(guess.value).split(",")[0])
            typed = True
            page.wait_for_timeout(1800)
            options = self._visible_options(page)
        if not options:
            page.keyboard.press("Escape")
            return False
        ans = resolver.resolve(label, "choice", options=options, required=f["required"])
        if ans is None and not typed and f["kind"] == "combo":
            page.keyboard.press("Escape")
            return False
        if ans is None:
            page.keyboard.press("Escape")
            return False
        page.locator('[role="option"]:visible').nth(ans.value).click()
        page.wait_for_timeout(400)
        filled.append((label, ans))
        return True

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
