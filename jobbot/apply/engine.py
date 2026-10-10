"""Open an application in a real browser, fill it, verify it, and stop for your review.

Before every Next and Submit, jobbot reads back each value it set and checks the
page for empty required fields, validation errors, and CAPTCHAs (verify.py).

With `auto_next` (the default) jobbot moves through multi-page forms on its own
whenever a page passes the check. Automatic submission also requires explicit
Ollama approval covering every field. Interactive sessions offer submit, refill,
done, or quit. Unattended sessions skip applications with unresolved gates.
"""

import re
import time

from .. import paths, tracker
from ..answers import Resolver, real_options
from . import auth, browser, consistency, dropdowns, email_verification, review, sites, values
from .browser import browser_profile_holder  # compatibility for existing callers
from .dropdowns import matching_option as _matching_option  # compatibility for existing callers
from .review import REVIEW_BATCH  # public compatibility for existing callers
from .fields import BUTTONS_JS
from .sites import detect_ats, start_url
from .unattended import NeedsYou, UnattendedUI
from .verify import READBACK_JS, check_page, matches

MAX_ROUNDS = 5           # review rounds per page before asking you
TRUSTED = ("profile", "rule", "remembered")   # sources allowed to overwrite a value the site pre-filled

MAX_PAGES = 15
MAX_ATTEMPTS = 3           # unattended: tries at the same page before moving on to the next application
MAX_APPLY_SECONDS = 600    # unattended: time limit for one application

SUBMIT_RE = r"^(submit( (my )?application)?|send application|apply|finish|complete application)$"
WORKDAY_SUBMIT_RE = r"^submit$"   # Workday keeps "Apply" buttons around; only Review has "Submit"
APPLY_RE = r"^(apply( now| online| here)?|apply (for|to) (this|the) (job|position|role)|start (your )?application|i.?m interested|submit (your )?(resume|cv))$"
NEXT_RE = r"^(next|continue|save and continue|save & continue|proceed)$"
CONFIRM_RE = re.compile(
    r"thank(s| you) for (applying|your (application|interest))|application (has been |was )?(submitted|received)|"
    r"successfully (submitted|applied)|we.ve received your application|congratulations", re.I)
# Honeypot fields exist to catch bots; filling one gets the application flagged.
TRAP_RE = re.compile(r"robots? only|for robots|do not (fill|enter)|leave (this )?(field )?(blank|empty)|honeypot", re.I)
CODE_RE = email_verification.CODE_RE
CONSENT_RE = re.compile(r"consent|privacy|acknowledge|agree|terms|certify|^i confirm|confirm the statement|declare", re.I)


class Session:
    def __init__(self, profile, llm, ui, dry_run=False, upload=True, auto_next=True, unattended=False, browser_dir=None):
        self.profile = profile
        self.browser_dir = browser_dir or paths.BROWSER_PROFILE   # parallel workers each get their own copy
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
        self._pw, self.ctx = browser.launch(self.browser_dir)
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
        self._job_url = job.get("url")   # sign-in may use the posting's own sites (auth.host_allowed)
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
        sites.wait_rendered(page)
        self.ui.info(f"{job['company']} — {job['title']}  [{ats}]  resume: {resume_key}")
        if sites.maintenance(page):   # the site is down, not the posting: keep the role and retry later
            raise NeedsYou(f"{ats.title()} is down for maintenance; retry this role later.")
        self._preview_page(page)

        reason = sites.unavailable_reason(page)
        if reason:
            self.ui.warn(f"Posting unavailable: {reason}. Skipping this role.")
            return None, f"posting unavailable: {reason}"
        entered = self._enter_form(page, ats) or page
        if self.unattended and entered is not page:
            self._close(page)   # Apply opened the form in a new tab: don't leave the posting behind
        page = entered
        reason = sites.unavailable_reason(page)
        if reason:
            self.ui.warn(f"Posting unavailable: {reason}. Skipping this role.")
            return None, f"posting unavailable: {reason}"
        if self.unattended:
            self._page = page
        if resume and self.upload:
            self._upload_resume(page, resume["path"], ats)

        resolver = Resolver(self.profile, self.llm, job=job, resume_key=resume_key, ask=self.ui.ask,
                            memory=self.memory,
                            auto_drafts=bool(self.profile.get("automation.auto_accept_drafts", True)))
        self._consent_approved = bool(self.profile.get("automation.auto_consent", False))
        self._consent_allowed = set()
        self._consent_declined = set()
        self._manual_records = {}
        self._mine = set()   # labels jobbot has filled or confirmed during this application
        self._broken = set()  # labels whose field could not be filled; not retried in later review rounds
        self._log(f"=== {job['company']} — {job['title']} [{ats}] {url} resume={resume_key}")
        step = 1
        visits, began, check = {}, time.time(), None
        while step <= MAX_PAGES:
            if self.unattended:
                # Never get stuck on one application: the same page 3 times (Next not moving, Submit
                # rejected, a re-check changing nothing) or MAX_APPLY_SECONDS in all, and it moves on.
                try:   # the fields on the page tell steps apart where the URL stays the same
                    labels = frozenset(f["label"] for f in self._fields(page))
                except Exception:
                    labels = frozenset()
                key = (page.url, self._step_marker(page), labels)
                visits[key] = visits.get(key, 0) + 1
                why = "; ".join(check.lines()[:2]) if check is not None and not check.ok else "the page did not move on"
                if visits[key] > MAX_ATTEMPTS:
                    raise NeedsYou(f"Gave up after {MAX_ATTEMPTS} attempts on page {step}: {why}")
                if time.time() - began > MAX_APPLY_SECONDS:
                    raise NeedsYou(f"Gave up after {MAX_APPLY_SECONDS // 60} minutes on this application: {why}")
            reason = sites.unavailable_reason(page)
            if reason:
                self.ui.warn(f"Posting unavailable: {reason}. Skipping this role.")
                return None, f"posting unavailable: {reason}"
            if sites.maintenance(page):   # e.g. Workday went down between the posting and its form
                raise NeedsYou(f"{ats.title()} is down for maintenance; retry this role later.")
            self._decline_cookies(page)
            signed_in = self._ensure_signed_in(page) if self._needs_account(page) else True
            report, check, rounds = self.review_page(page, resolver, step) if signed_in else \
                ({"filled": [], "skipped": [], "records": []}, self.verify(page, {}), 0)
            self.ui.report(report, check, step)
            if rounds:
                self.ui.info(f"Reviewed page {step} in {rounds} round(s); "
                             + ("the last round changed nothing." if check.ok else "problems remain."))

            reason = sites.unavailable_reason(page)   # some boards show it only after the page settles
            if reason:
                self.ui.warn(f"Posting unavailable: {reason}. Skipping this role.")
                return None, f"posting unavailable: {reason}"

            submit_re = WORKDAY_SUBMIT_RE if ats == "workday" else SUBMIT_RE
            can_next = bool(self._buttons(page, NEXT_RE))
            # A page with Next / Save and Continue is never the final step, whatever else it shows.
            can_submit = not can_next and bool(self._buttons(page, submit_re))
            if getattr(self, "auto_submit", False) and not self.dry_run and check.ok and can_submit:
                choice = "submit"
            elif self.auto_next and check.ok and can_next:
                self.ui.info("All checks passed; moving to the next step.")
                choice = "next"
            else:
                choice = self.ui.next_action(can_submit=can_submit and not self.dry_run, can_next=can_next and (check.ok or not getattr(self, "validation", False)),
                                             dry_run=self.dry_run, check_ok=check.ok, final_page=can_submit)
            if choice == "submit" and not check.ok and not self.ui.confirm(
                    "The check still shows problems. Submit anyway?"):
                continue

            if isinstance(choice, dict) and choice.get("action") == "correct":
                self._correct_field(page, choice)
                continue
            if choice == "refill":
                import importlib
                import sys
                for name in ("jobbot.apply.fields", "jobbot.apply.sites", "jobbot.apply.verify"):
                    importlib.reload(sys.modules[name])
                module = importlib.reload(sys.modules[__name__])
                self.__class__ = module.Session
                self._broken.clear()
                self._mine.clear()
                continue
            if choice == "next":
                before = page.url, self._step_marker(page)
                self._decline_cookies(page)
                try:
                    self._click(page, NEXT_RE)
                except Exception as exc:
                    if self.unattended:
                        raise NeedsYou("Next step is blocked; review the dialog or page in Chrome.") from exc
                    self.ui.warn("Could not open the next step. A dialog or site error may be blocking it.")
                    self._wait_for_user(page, "Review the dialog or error in Chrome and resolve it if appropriate, "
                                          "then press Enter here to check the page again.")
                    continue
                page.wait_for_timeout(3500)
                if ats == "workday":
                    self._workday_settle(page)
                if (page.url, self._step_marker(page)) == before:
                    after = check_page(page, [], [], [])
                    if after.errors:
                        self.ui.warn("The site kept us on the same step: " + "; ".join(after.lines()[:3]))
                self._manual_records.clear()
                step += 1
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
                if getattr(self, "auto_submit", False):
                    # A click may have succeeded even when the site uses unfamiliar confirmation text.
                    # Never submit the same application again to discover whether it worked.
                    raise NeedsYou("Submit clicked but confirmation was not detected; check the site before retrying.")
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
            if self.dry_run and can_submit and check.ok:
                return None, "dry run: final page verified; not submitted"
            if self.dry_run and not check.ok:
                return None, "validation blocked: " + "; ".join(check.lines()[:3])
            return None, "stopped without submitting"
        return None, f"stopped after {MAX_PAGES} pages"

    def review_page(self, page, resolver, step):
        """Fill, verify and correct until a whole round changes nothing and the check passes.

        Each round re-reads the page. Values the site pre-filled (e.g. Workday's resume autofill)
        are overwritten when your profile says otherwise; values jobbot set are re-filled only if
        the check shows they did not stick. Stops after MAX_ROUNDS rounds.
        """
        total = {"filled": [], "skipped": [], "records": list(getattr(self, "_manual_records", {}).values())}
        force, check = set(), None
        for rnd in range(1, MAX_ROUNDS + 1):
            rep = self.fill_page(page, resolver, force=force)
            total = self._merge(total, rep)
            page.wait_for_timeout(500)
            check = self.verify(page, total)
            changes = len(rep["filled"])
            if changes == 0 or rnd == MAX_ROUNDS:
                # The profile check decides every field your profile answers; the model reviews the rest.
                confirmed = consistency.apply(self, page, resolver, total, check)
                if getattr(self, "auto_submit", False) or self.profile.get("automation.ollama_review_each_step", False):
                    self._ollama_review(page, resolver, total, check, step, confirmed)
            self._log(f"page {step} round {rnd}: {changes} change(s)", *[f"  set {l} = {a}" for l, a in rep["filled"]],
                      *[f"  ! {line}" for line in check.lines()])
            if hasattr(self.ui, "audit"):
                self.ui.audit(step, rnd, self.audit_fields(page, total), check)
                if hasattr(self.ui, "preview_page"):
                    self._preview_page(page)
            force = {m[0] for m in check.mismatches}
            for label in force:
                self._mine.discard(label)
            if changes == 0 and check.ok:
                return total, check, rnd
            if changes == 0 and not force:
                return total, check, rnd   # nothing left that jobbot can change by itself
        return total, check, MAX_ROUNDS

    _ollama_review = review.review_step

    def _correct_field(self, page, action):
        """Apply a reviewed text/select correction, then verify its exact value next round."""
        f = next((f for f in self._fields(page) if f["id"] == action.get("field")), None)
        if not f or f["kind"] not in ("text", "textarea", "select", "radio", "yesno"):
            self.ui.warn("That field is no longer editable; re-check the page.")
            return
        if CONSENT_RE.search(f["label"]) or re.search(r"gender|race|ethnic|veteran|disability|signature|password", f["label"], re.I):
            self.ui.warn("This field needs to be handled directly by you in Chrome.")
            return
        value = str(action.get("value", ""))
        loc = page.locator(f'[data-jobbot-id="{f["id"]}"]')
        target_id = f["id"]
        if f["kind"] in ("radio", "yesno"):
            if value not in f["options"]:
                self.ui.warn("Choose an option the site actually offers.")
                return
            target_id = f["id"].split(",")[f["options"].index(value)]
            self._tick(page, target_id)
        elif f["kind"] == "select":
            if value not in f["options"]:
                self.ui.warn("Choose an option the site actually offers.")
                return
            loc.select_option(label=value)
        else:
            loc.fill(value)
        self._manual_records[target_id] = {"id": target_id, "kind": f["kind"], "label": f["label"], "expected": value}
        self._broken.discard(f["label"])
        self._mine.add(f["label"])
        self.ui.info(f"Corrected {f['label']}; reading the value back again.")

    def _preview_page(self, page):
        if hasattr(self.ui, "preview_page"):
            try:
                import base64
                data = page.screenshot(type="jpeg", quality=65, full_page=True, timeout=10000)
                self.ui.preview_page(base64.b64encode(data).decode())
            except Exception:
                self.ui.warn("Could not capture the application preview; inspect the Chrome window.")

    def _wait_for_user(self, page, message):
        self._preview_page(page)
        self.ui.wait_for_user(message)

    def audit_fields(self, page, report):
        """Read every current field and expose expected/actual values for page revision."""
        records = report.get("records", [])
        readback = {r["id"]: r for r in page.evaluate(READBACK_JS, records)} if records else {}
        expected = {r["id"]: r for r in records}
        out = []
        for f in self._fields(page):
            ids = f["id"].split(",")
            r = next((expected[i] for i in ids if i in expected), None)
            value = f.get("text") or f.get("shown") or f.get("value") or ""
            if isinstance(value, list):
                value = ", ".join(o for o, selected in zip(f.get("options", []), value) if selected)
            got = readback.get(r["id"], {}) if r else {}
            actual = got.get("value", value)
            status = ("verified" if got.get("found") and matches(r["expected"], actual, r["kind"]) else "needs revision") if r else ("present, review" if value else "required, empty" if f.get("required") else "optional, empty")
            out.append({"id": f["id"], "kind": f["kind"], "options": f.get("options", []), "label": f["label"], "required": f.get("required", False), "expected": r["expected"] if r else None,
                        "actual": str(value if f["kind"] in ("radio", "yesno", "checkgroup") else actual), "status": status})
        return out

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
        fields = self._fields(page)
        check = check_page(page, report.get("records", []), report.get("skipped", []), fields)
        if not self._form_fields(page) and not self._buttons(page, NEXT_RE) and not self._buttons(page, WORKDAY_SUBMIT_RE if self._ats == "workday" else SUBMIT_RE):
            check.errors.append("No application fields or navigation controls found; this page cannot be verified.")
        if self._needs_account(page):
            check.errors.append("Still on an account/sign-in step; application details are not verified.")
        return check

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

    @staticmethod
    def _decline_cookies(page):
        """Choose the privacy-preserving option on a cookie/privacy banner, which can also sit over
        the page and swallow clicks on Next. A bare "Decline" or "Reject" counts only beside cookie
        or privacy wording, so it never answers a form question."""
        try:
            choice = page.get_by_role("button", name=re.compile(
                r"^decline non-essential$|^reject all(?: cookies)?$|^necessary cookies only$", re.I))
            if not (choice.count() and choice.first.is_visible()):
                text = page.inner_text("body")
                if not re.search(r"cookie|privacy notice|manage preferences|important notice", text, re.I):
                    return False
                choice = page.get_by_role("button", name=re.compile(r"^(decline|reject)$", re.I))
                if not (choice.count() and choice.first.is_visible()):
                    return False
            choice.first.click(timeout=3000)
            page.wait_for_timeout(500)
            return True
        except Exception:
            return False

    def _enter_form(self, page, ats):
        self._decline_cookies(page)   # some careers pages put a cookie choice above their application button
        if ats == "greenhouse" and not self._fields(page):
            # Company careers pages embed the Greenhouse form in an iframe; open the form itself.
            frame = next((f for f in page.frames if "greenhouse.io/embed/job_app" in f.url), None)
            if frame:
                page.goto(frame.url, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
        if ats == "smartrecruiters":
            page = self._open_application(page)  # SmartRecruiters renders Apply as an ordinary link.
            return page
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
            if self._needs_account(page):
                self._ensure_signed_in(page)
            elif not self._form_fields(page):
                self._wait_for_user(page, "Open the application form in the browser window, then press Enter here.")
            return page

    def _form_fields(self, page):
        """Fields that belong to an application, not to a job page's search box or language picker."""
        return [f for f in self._fields(page) if f["kind"] not in ("listbutton", "file")
                and (f.get("required") or f.get("label"))
                and not re.search(r"search|keyword|language|locale|subscribe|newsletter",
                                  (f["label"] or "") + " " + str(f.get("value") or ""), re.I)]

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

    _needs_account = staticmethod(auth.needs_account)
    _ensure_signed_in = auth.ensure_signed_in

    def _dry_validation(self):
        """A validation run that will not submit: it leaves demographic answers and consents to you.
        An approved auto-submit run answers them from your profile like any normal run."""
        return getattr(self, "validation", False) and not getattr(self, "auto_submit", False)

    _workday_account = auth.workday_sign_in

    _email_login_step = email_verification.email_login_step

    def _upload_resume(self, page, path, ats):
        inputs = [f for f in self._fields(page) if f["kind"] == "file"]
        if not inputs:
            self.ui.warn("No file upload field found; attach your resume in the browser if the form needs one.")
            return
        target = next((f for f in inputs if re.search(r"resume|cv", f["label"] + " " + f.get("name", ""), re.I)), inputs[0])
        page.locator(f'[data-jobbot-id="{target["id"]}"]').set_input_files(str(path))
        # Greenhouse and Workday parse the resume and rewrite fields; fill only after they finish.
        page.wait_for_timeout(8000 if ats in ("greenhouse", "workday") else 3000)
        if ats == "workday" and not getattr(self, "validation", False) and self._buttons(page, NEXT_RE):
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
                # one box per character (Greenhouse: 8 boxes that do not all declare maxlength=1)
                single = len(code_boxes) > 1 and (all(f.get("maxlength") == 1 for f in code_boxes) or len(code_boxes) == len(code))
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
            if kind not in ("file", "checkbox", "listbutton") and not values.meaningful_label(label):
                if f["required"]:
                    skipped.append(f"{label} (question could not be identified)")
                continue
            if re.search(r"captcha|type (?:the |below )?image text", label, re.I):
                if f["required"]:
                    skipped.append("CAPTCHA (requires your action)")
                continue
            demographic_allowed = any(re.search(r"\b" + re.escape(name) + r"\b", label, re.I)
                                      for name in self.profile.get("automation.allowed_demographic_fields", []) or [])
            if self._dry_validation() and not demographic_allowed and re.search(r"\bgender\b|\brace\b|ethnicity|veteran|disability|hispanic|latino|\bsms\b|whatsapp|text messages|marketing|newsletter", label, re.I):
                if f["required"]:
                    skipped.append(f"{label} (requires your answer)")
                continue
            manual = getattr(self, "_manual_records", {}).get(f["id"])
            if manual and kind in ("text", "textarea", "select"):
                value = f.get("text") if kind == "select" else f.get("value")
                if not matches(manual["expected"], value or "", kind):
                    loc = page.locator(f'[data-jobbot-id="{f["id"]}"]')
                    if kind == "select":
                        loc.select_option(label=manual["expected"])
                    else:
                        loc.fill(manual["expected"])
                    note(f, label, manual["expected"], expected=manual["expected"])
                mine.add(label)
                continue
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
                    if kind in ("radio", "yesno") and CONSENT_RE.search(label):
                        consents.append({**f, "id": f["id"].split(",")[0]})
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

        consents = [c for c in consents if c["label"] not in getattr(self, "_consent_declined", set())]
        if self._dry_validation() and any(c["label"] not in getattr(self, "_consent_allowed", set()) for c in consents):
            self._consent_approved = False
        if consents and not self._consent_approved:
            self._preview_page(page)
            self._consent_approved = self.ui.confirm(
                "Approve these consent choices?\n  - "
                + "\n  - ".join(c["label"][:160] for c in consents))
            if self._consent_approved:
                if not hasattr(self, "_consent_allowed"):
                    self._consent_allowed = set()
                self._consent_allowed.update(c["label"] for c in consents)
            else:
                self._consent_declined.update(c["label"] for c in consents)
        if consents and self._consent_approved:
            for c in consents:
                try:
                    self._tick(page, c["id"])
                except Exception as e:   # one stubborn box is listed for review, not fatal to the application
                    skipped.append(f"{c['label'][:110]} (error: {type(e).__name__})")
                    continue
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

    _code_from_email = email_verification.code_from_email

    @staticmethod
    def _tick(page, field_id):
        """Click a checkbox or radio. Many sites hide the real input off-screen behind a styled label
        (Oracle, for one), where even a forced click fails: try the label, then the input, then a click
        from inside the page."""
        loc = page.locator(f'[data-jobbot-id="{field_id}"]')
        if loc.evaluate("el => el.tagName === 'BUTTON'"):
            loc.click(timeout=3000)
            if loc.get_attribute("aria-pressed") == "true":
                return
            if loc.evaluate("el => /selected|active/i.test(el.className)"):
                return
            raise RuntimeError("button choice did not become selected")
        label = loc.evaluate("""el => { const l = (el.labels && el.labels[0])
            || document.getElementById((el.getAttribute('aria-labelledby') || '').split(' ')[0]);
            if (!l || !l.getClientRects().length) return null;
            const id = 'l' + Math.random().toString(36).slice(2, 9); l.setAttribute('data-jobbot-label', id); return id; }""")
        attempts = ([lambda: page.locator(f'[data-jobbot-label="{label}"]').click(timeout=3000)] if label else []) + [
            lambda: loc.click(force=True, timeout=3000), lambda: loc.evaluate("el => el.click()"),
            lambda: (loc.focus(), page.keyboard.press("Space"))]   # last resort: the keyboard toggles most custom boxes
        # Custom controls (role="checkbox" divs, as on some Greenhouse boards) have no .checked: read aria-checked.
        state = lambda: loc.evaluate("el => el.checked !== undefined ? el.checked : el.getAttribute('aria-checked') === 'true'")
        before = state()
        for attempt in attempts:
            try:
                attempt()
            except Exception:
                continue
            if state() != before:
                return
        raise RuntimeError("could not tick this box")

    def _text_value(self, f, label, ans, has_dial_picker):
        return values.format_value(self.profile, f, label, ans.value, has_dial_picker)

    _fill_dropdown = dropdowns.fill_dropdown
    _open_dropdown = staticmethod(dropdowns.open_dropdown)
    _search_options = dropdowns.search_options
    _reopen = dropdowns.reopen
    _click_option = staticmethod(dropdowns.click_option)
    _visible_options = staticmethod(dropdowns.visible_options)


    @staticmethod
    def _fields(page):
        # Revision can replace Session while an older application loop is still running.
        # Read the scanner module afresh so that loop does not retain stale imports.
        from . import fields
        return page.evaluate(fields.SCAN_JS)

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
