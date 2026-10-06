"""What differs between job sites: which applicant-tracking system a job uses, where its form starts,
Workday's late rendering, and recognising sign-in pages."""

import re
import urllib.parse

SIGNIN_RE = re.compile(r"sign ?in|log ?in|create (an )?account|register", re.I)


# --- where to start for each applicant-tracking system --------------------------------

# Application flows jobbot knows how to drive. Jobs found through other sources (Amazon, Google, Oracle,
# Eightfold, careers pages...) are applied to by their URL, which may still point at one of these.
FORM_ATS = ("greenhouse", "lever", "lever-eu", "ashby", "smartrecruiters", "workday")


def detect_ats(url, job=None):
    if job and job.get("ats") in FORM_ATS:
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
        # A job's "board" is a Greenhouse board id only when the scan read it from Greenhouse; a careers
        # page (e.g. digitalocean.com/careers/...?gh_jid=) stores its own URL there instead.
        board = (job or {}).get("board") if (job or {}).get("ats") == "greenhouse" else None
        board = board or (m.group(1) if m and "greenhouse.io" in parsed.netloc else None)
        job_id = job_id or (m.group(2) if m else None)
        if board and job_id:
            return f"https://job-boards.greenhouse.io/embed/job_app?for={board}&token={job_id}"
        return url
    if ats in ("lever", "lever-eu"):
        return url if url.rstrip("/").endswith("/apply") else url.rstrip("/") + "/apply"
    if ats == "ashby":
        return url if url.rstrip("/").endswith("/application") else url.rstrip("/") + "/application"
    if ats == "workday":
        # ".../job/<loc>/<title>/apply/..." -> the posting. Only after /job/: some sites are named "apply".
        return re.sub(r"(/job/[^?#]+?)/apply(/.*)?$", r"\1", url)
    return url


def workday_settle(page, timeout_ms=15000):
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


def signin_page(page):
    try:
        if page.locator("input[type=password]:visible").count():
            return True
        heading = " ".join(page.locator("h1, h2, button").all_inner_texts()[:20])
    except Exception:
        return False
    host = urllib.parse.urlparse(page.url).netloc
    return bool(re.search(r"^(passport|login|signin|accounts?|auth|sso|id)\.", host)
                or SIGNIN_RE.search(urllib.parse.urlparse(page.url).path) or SIGNIN_RE.search(heading))
