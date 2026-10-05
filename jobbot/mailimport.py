"""Build application rows from job-application emails.

Input is a JSON list of messages (or a Gmail-style search result with
`threads[].messages[]`), each with at least sender, subject, snippet, and date.
Acknowledgements become `applied`, rejections `rejected`, and assessment or
interview invitations `assessment` / `interview`. The latest email for a
company+role wins. Heuristic: review the result with `jobbot track`.
"""

import html
import json
import re

REJECT = re.compile(
    r"unfortunately|not (be )?moving forward|not to move forward|decided to (move|proceed) forward with other|"
    r"move forward with (other|another) candidate|regret to inform|won.?t be (moving|progressing)|will not be (moving|progressing)|"
    r"not (been )?selected|position has (now )?been filled|role has (now )?been (filled|closed)|other candidates whose|"
    r"move forward with candidates|decided not to (move|proceed)|(although|while) we were impressed|"
    r"appreciate the time, effort, and thought you invested", re.I)
INTERVIEW = re.compile(r"interview (invitation|confirmation|reminder|scheduled)|invitation: interview|schedule (an|your) interview", re.I)
ASSESSMENT = re.compile(r"online assessment|coding (test|challenge|assessment)|pre-screening test|take-home|hackerrank test|test link", re.I)
APPLIED = re.compile(r"thank(s| you) for (applying|your application|your interest|completing)|application (has been )?(received|submitted)|"
                     r"received your application|application was sent|we.ve received", re.I)

COMPANY_PATTERNS = [
    r"for choosing ([A-Z][\w&. ]{1,40}?) in your",
    r"(?:role|position|opportunity) at ([A-Z][\w&.\- ]{1,40}?)(?:[!.,|:]| - |$)",
    r"with ([A-Z][\w&. ]{1,40}?)!?$",
    r"(?:applying|applied|application) (?:to|at|with) (?:the )?(.+?)(?:[!.,|:-]| - |$)",
    r"interest in (?:joining )?(.+?)(?:[!.,|:]| - |$)",
    r"application to (.+?)(?:[!.,|:]| - |$)",
    r"\bat ([A-Z][\w&.\- ]{1,40}?)(?:[!.,|:]| - |$)",
    r"^(?!thank)(.+?) (?:careers)",
]
TITLE_PATTERNS = [
    r"for (?:the |our )?(?:role|position) of ([^.,;]+?)(?:[.,;]| at |$)",
    r"position of ([^.,;]+?)(?:,| at |\.|$)",
    r"application for (?:the |our )?([^.,;!]+?)(?: role| position| job| at |[.,;!]|$)",
    r"for (?:the |our )?([^.,;!]+?) (?:role|position|job|opening|opportunity)",
    r"applying (?:for|to) (?:the |our )?([^.,;!]+?) (?:role|position|job)",
    r"(?:in|for) the ([^.,;!]+?) (?:role|position)",
]
GENERIC_SENDERS = re.compile(r"greenhouse|lever\.co|ashbyhq|workable|smartrecruiters|myworkday|icims|pinpoint|rippling|"
                             r"successfactors|taleo|jobvite|bamboohr", re.I)


def _clean(text):
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def _first(patterns, *texts):
    for text in texts:
        for p in patterns:
            m = re.search(p, text, re.I)
            if m:
                value = _clean(m.group(1)).strip(" -–:")
                if 1 < len(value) <= 90:
                    return value
    return None


def _sender_company(sender):
    m = re.search(r"@([\w.-]+)", sender or "")
    if not m or GENERIC_SENDERS.search(m.group(1)):
        return None
    parts = [p for p in m.group(1).split(".") if p not in ("com", "co", "in", "io", "ai", "email", "mail", "careers",
                                                            "recruitment", "jobs", "hire", "talent", "us", "eu", "candidates")]
    return parts[-1].capitalize() if parts else None


TITLE_JUNK = re.compile(r"^(?:the|our|your application to the|applying (?:to|for)(?: the)?|(?:expressing an )?interest in(?: the)?|your|an?)\s+|"
                        r"\s+(?:has been (?:received|successfully)|and wil\w*)$|^R\d{5,}\s+", re.I)
NOT_A_TITLE = re.compile(r"^(this|following|that|it|expressing an interest in|interest in)$", re.I)
ROLE_WORDS = re.compile(r"engineer|developer|\bsde\b|backend|frontend|full ?stack|software|intelligence|analyst|^opportunit|^job ", re.I)


def _title(snippet, subject):
    title = _first(TITLE_PATTERNS, snippet, subject)
    if not title:
        return None
    for _ in range(3):
        title = TITLE_JUNK.sub("", title).strip()
    return title if len(title) > 3 and not NOT_A_TITLE.match(title) and title.lower() not in ("role", "position") else None


def classify(subject, snippet):
    text = f"{subject} {snippet}"
    if REJECT.search(text):
        return "rejected"
    if INTERVIEW.search(text):
        return "interview"
    if ASSESSMENT.search(text):
        return "assessment"
    if APPLIED.search(text):
        return "applied"
    return None


def messages_from(data):
    if isinstance(data, dict) and "threads" in data:
        for t in data["threads"]:
            for m in t.get("messages", []):
                yield m
    elif isinstance(data, list):
        yield from data


def rows_from(data, skip_senders=()):
    latest = {}
    for m in messages_from(data):
        sender = m.get("sender", "")
        if any(s in sender for s in skip_senders) or "SENT" in (m.get("labelIds") or []):
            continue
        subject, snippet = _clean(m.get("subject")), _clean(m.get("snippet"))
        if re.match(r"(invitation|updated invitation|accepted|declined):", subject, re.I):
            continue  # calendar invites duplicate the recruiter's own email
        status = classify(subject, snippet)
        if not status:
            continue
        company = _first(COMPANY_PATTERNS, subject, snippet)
        if not company or ROLE_WORDS.search(company):
            company = _sender_company(sender)  # the pattern grabbed a role or a phrase, not an employer
        title = _title(snippet, subject) or "(role not stated in email)"
        if not company:
            continue
        company = re.sub(r"^(the |join )", "", company, flags=re.I)
        company = re.split(r" - | \| |, | for the ", company)[0].strip()
        company = re.sub(r"\s+(careers|inc\.?|llp|ltd\.?|pvt\.? ltd\.?|private limited|technologies)$", "",
                         company, flags=re.I)
        title = re.sub(r",?\s*\d{6,}$", "", title).strip()  # trailing requisition ids
        date = (m.get("date") or "")[:10]
        key = (re.sub(r"\W", "", company.lower()), title.lower())
        prev = latest.get(key)
        if not prev or date >= prev["date"]:
            first = prev["applied_on"] if prev else date
            latest[key] = {"company": company, "title": title, "status": status, "date": date,
                           "applied_on": min(first, date) if first else date, "source": "gmail",
                           "notes": subject[:140]}
    return list(latest.values())


def import_rows(conn, rows):
    from . import tracker

    added = updated = 0
    for r in rows:
        existing = conn.execute(
            "SELECT id, status FROM applications WHERE lower(company)=lower(?) AND lower(title)=lower(?)",
            (r["company"], r["title"])).fetchone()
        if not existing and r["title"].startswith("(role not stated"):
            # Same company already tracked from the same day: almost certainly the same application.
            existing = conn.execute(
                "SELECT id, status FROM applications WHERE lower(company)=lower(?) AND applied_on=?",
                (r["company"], r["applied_on"])).fetchone()
        if existing:
            if existing["status"] != r["status"] and r["status"] != "applied":
                tracker.update_status(conn, existing["id"], r["status"], f"from email {r['date']}: {r['notes']}")
                updated += 1
            continue
        tracker.add_application(conn, r["company"], r["title"], status=r["status"], source="gmail",
                                applied_on=r["applied_on"], notes=r["notes"])
        added += 1
    return added, updated


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
