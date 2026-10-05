"""Turn a form question into an answer.

Order of precedence for each question:
  1. your own `answers:` rules in the profile
  2. `always_ask:` patterns (attestations, legal questions)  -> ask you
  3. built-in rules mapped to profile facts
  4. the local model, if enabled (multiple choice or free text)
  5. ask you (required fields) or skip (optional fields)

Every answer carries a `source` so the review summary shows where it came from.
"""

import re
from dataclasses import dataclass

PLACEHOLDER = re.compile(r"^(select|choose|please select|--|—|none selected|select one|select\.\.\.)\b", re.I)
DECLINE = re.compile(r"decline|prefer not|don.?t wish|do not wish|not to (say|disclose|answer)|choose not", re.I)


@dataclass
class Answer:
    value: object            # str for text, int index for choices, bool for checkboxes
    source: str              # profile | rule | model | you
    display: str = ""

    def __str__(self):
        return self.display or str(self.value)


def norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+ ]", " ", (text or "").lower())).strip()


def real_options(options):
    return [o for o in options if o and o.strip() and not PLACEHOLDER.match(o.strip())]


def pick(answer, options):
    """Index of the option that best matches `answer`, or None.

    Exact match first, then prefix, then whole-word containment, so "Male" never
    lands on "Female" and "No" picks "No, I have not been employed by PwC".
    """
    a = norm(str(answer))
    if not a:
        return None
    normed = [norm(o) for o in options]
    for i, o in enumerate(normed):
        if o == a:
            return i
    for i, o in enumerate(normed):
        if o and not PLACEHOLDER.match(options[i]) and (o.startswith(a + " ") or a.startswith(o + " ")):
            return i
    if a in ("decline", "decline to answer"):
        for i, o in enumerate(options):
            if DECLINE.search(o):
                return i
    pattern = re.compile(r"\b" + re.escape(a) + r"\b")
    hits = [i for i, o in enumerate(normed) if pattern.search(o)]
    if len(hits) == 1:
        return hits[0]
    return None


HEAR_RE = re.compile(r"how did you (hear|learn|find|come across)|where did you (hear|find|learn)|source of (application|referral)|"
                     r"how (did you|were you) (referred|introduced)", re.I)
HEAR_PREFERENCES = ["company website", "career site", "careers site", "careers website", "careers page", "company career",
                    "corporate website", "website", "linkedin", "job board", "online job", "internet", "other"]
EMPLOYMENT_RE = re.compile(r"employee id|employee number|(company|corporate|work) email|email address|worked|work(ing)? (for|at)|"
                           r"employed|employee|intern|contractor|contingent|consultant|vendor|alumni|former|previous(ly)?|rehire",
                           re.I)


def yes_no(flag):
    return "Yes" if flag else "No"


class Resolver:
    def __init__(self, profile, llm=None, job=None, resume_key=None, ask=None, memory=None, auto_drafts=False):
        self.p = profile
        self.llm = llm
        self.job = job or {}
        self.resume_key = resume_key
        self.ask = ask  # callable(question, options, required, suggestion) -> str|int|None
        self.auto_drafts = auto_drafts  # use model drafts for free-text questions without asking
        self.custom = [(re.compile(r["match"], re.I), r["answer"]) for r in (profile.get("answers") or [])]
        self.always_ask = [re.compile(x, re.I) for x in (profile.get("always_ask") or [])]
        self.rules = self._rules()
        self.memory = memory

    # --- built-in rules: (pattern, function returning the answer or None) -------------
    def _rules(self):
        p, g = self.p, self.p.get
        company = (self.job.get("company") or "").lower()
        past = [e.lower() for e in (g("work.past_employers") or [])]

        def worked_here():
            if not company:
                return None
            return yes_no(any(company.split()[0] in e or e.split()[0] in company for e in past))

        def experience_years():
            return str(g("work.total_experience_years", ""))

        return [
            (r"preferred (first )?name|nick ?name", lambda: g("personal.preferred_name") or g("personal.first_name")),
            (r"first name|given name|legal first", lambda: g("personal.first_name")),
            (r"last name|family name|surname|legal last", lambda: g("personal.last_name")),
            (r"^(full |legal |your )?name\b", lambda: p.full_name),
            (r"e-?mail", lambda: g("personal.email")),
            (r"country (phone )?code|phone country|dialing code", lambda: g("personal.phone_country")),
            (r"phone|mobile|contact number", lambda: g("personal.phone")),
            (r"linkedin", lambda: g("links.linkedin")),
            (r"github", lambda: g("links.github")),
            (r"website|portfolio|personal (site|url)|blog|other link", lambda: g("links.website")),
            (r"preferred (work )?location|locations? (are you|would you)", lambda: g("personal.city")),
            (r"address line 1|street address", lambda: g("personal.address_line1") or None),
            (r"postal|zip|pin ?code", lambda: g("personal.postal_code") or None),
            (r"\bstate\b|province|region", lambda: g("personal.state")),
            (r"location|\bcity\b|where are you (based|located)|current location", lambda: g("personal.location_autocomplete") or g("personal.city")),
            (r"^country\b|country of residence|which country", lambda: g("personal.country")),
            (r"current (company|employer|organi[sz]ation)|^company$|most recent (company|employer)", lambda: g("work.current_company")),
            (r"(current|most recent|latest) (job )?title|current (role|designation)|^title$", lambda: g("work.current_title")),
            (r"notice period|when can you (start|join)|earliest start|availability to join|(preferred|expected|available) (start|joining) date|start date", lambda: f"{g('work.notice_period_days')} days notice"),
            (r"years of (professional |relevant |total |industry |work )?experience|how many years", experience_years),
            (r"current (total |annual |fixed )?(ctc|compensation|salary|cost to company|package)|present (ctc|salary)", lambda: g("work.current_ctc")),
            (r"expected (ctc|compensation|salary)|salary expectation|desired (salary|compensation)", lambda: g("work.expected_ctc")),
            (r"reason for (leaving|change|looking)|why are you (leaving|looking)", lambda: g("work.reason_for_change")),
            (r"sponsor", lambda: yes_no(g("eligibility.needs_sponsorship", False))),
            (r"(authori[sz]ed|eligible|right|permit(ted)?) to work|work authori[sz]ation|legally (able|eligible|authori[sz]ed)|documentation establishing your identity",
             lambda: yes_no(bool(g("eligibility.authorized_countries")))),
            (r"legal age|at least 18|over (the age of )?18", lambda: "Yes"),
            (r"hybrid|in.?office|on.?site|onsite|work (from|in|at) (the|our) .*office|days a week|come (in )?to the office|"
             r"based in our .* office|office.?based", lambda: yes_no(g("eligibility.willing_to_relocate", True))),
            (r"relocat|work (on a daily basis )?in the (work )?location|able to work from|commute", lambda: yes_no(g("eligibility.willing_to_relocate", True))),
            (r"currently (based|located|living|residing) in|do you (live|reside) in", lambda: None),
            (r"notice period.*(negotiable|buy ?out|serve)|can you (join|start) (early|sooner|immediately)|buy ?out", lambda: "Yes"),
            (r"serving (your )?notice|on notice period|currently on notice", lambda: "No"),
            (r"willing to (work|take|do).*(shift|weekend|on.?call|night|rotational)", lambda: "Yes"),
            (r"open to (contract|full.?time|permanent)|employment type|full.?time (role|position)", lambda: "Yes"),
            (r"(how many|number of) years.*(experience|exp)|years of (hands.?on )?experience (with|in|using)", lambda: str(g("work.total_experience_years", ""))),
            (r"background (check|verification)", lambda: yes_no(g("eligibility.background_check_ok", True))),
            (r"(have you )?(ever |previously )?(worked|been employed) (at|for|by)|former employee|current(ly)? .*employee|employed by .* in the past", worked_here),
            (r"hispanic|latin[oa]", lambda: g("eeo.hispanic_latino")),
            (r"gender|\bsex\b", lambda: g("eeo.gender")),
            (r"race|ethnic", lambda: g("eeo.race")),
            (r"veteran|military", lambda: g("eeo.veteran")),
            (r"disabilit", lambda: g("eeo.disability")),
            (r"how did you (hear|learn|find|come across)|source of (application|referral)|where did you (hear|find)", lambda: g("preferences.how_did_you_hear")),
            (r"school|university|college|institution", lambda: g("education.school")),
            (r"\bdegree\b|qualification|level of education", lambda: g("education.degree")),
            (r"major|field of study|discipline|specialization", lambda: g("education.field")),
            (r"\bc?gpa\b|grade|percentage|overall result", lambda: g("education.gpa")),
            (r"graduat(ion|ed) (year|date)|year of (graduation|passing)|expected graduation", lambda: str(g("education.end_year", ""))),
        ]

    def _builtin(self, question):
        q = question.strip()
        m = re.search(r"currently (?:based|located|living|residing) in ([A-Za-z ,/]+)|do you (?:live|reside) in ([A-Za-z ,/]+)", q, re.I)
        if m:
            place = (m.group(1) or m.group(2) or "").lower()
            return yes_no(str(self.p.get("personal.city", "")).lower() in place)
        for pattern, fn in self.rules:
            if re.search(pattern, q, re.I):
                value = fn()
                if value not in (None, ""):
                    return str(value)
                return None
        return None

    def resolve(self, question, kind="text", options=None, required=False, quick=False):
        """kind: text | textarea | choice | checkbox. Returns Answer or None to leave blank.

        quick=True uses only your answers, remembered answers and built-in rules: no model,
        no questions to you. Used before searching long dropdown lists.
        """
        question = re.sub(r"\s+", " ", question or "").strip(" *:")
        options = real_options(options or [])

        for pattern, value in self.custom:
            if pattern.search(question):
                return self._fit(value, kind, options, "profile")

        if any(p.search(question) for p in self.always_ask):
            return self._ask(question, kind, options, required, None, reason="needs your confirmation", learn=False)

        if self.memory and kind != "checkbox":
            learned = self.memory.lookup(question, options if kind == "choice" else None)
            if learned is not None:
                ans = self._fit(learned, kind, options, "remembered")
                if ans is not None:
                    return ans

        if kind == "checkbox":
            return None  # consent boxes are handled by the review step, never ticked silently

        if HEAR_RE.search(question) and not quick:
            return self._how_did_you_hear(question, kind, options)

        employer = self._employer_history(question)
        if employer is not None:
            ans = self._fit(employer, kind, options, "rule")
            if ans is not None:
                return ans

        value = self._builtin(question)
        if value is not None:
            ans = self._fit(value, kind, options, "rule")
            if ans is not None:
                return ans

        if quick:
            return None

        if self.llm and self.llm.enabled:
            try:
                resume = self.p.resume_text(self.resume_key) if self.resume_key else ""
                if kind == "choice" and options:
                    idx = self.llm.choose(question, options, self.p.summary(), resume)
                    if idx is not None:
                        return Answer(idx, "model", options[idx])
                elif kind in ("text", "textarea") and required:
                    draft = self.llm.draft(question, self.job, self.p.summary(), resume,
                                           max_words=150 if kind == "textarea" else 25)
                    if self.auto_drafts and draft:
                        return Answer(draft.strip(), "model")
                    return self._ask(question, kind, options, required, draft, reason="model draft, review it")
            except Exception:
                pass

        if required:
            return self._ask(question, kind, options, required, None, reason="no rule matched")
        return None

    def _how_did_you_hear(self, question, kind, options):
        """Never ask: the profile's answer, a close synonym, the model's pick, else the first option."""
        preferred = self.p.get("preferences.how_did_you_hear") or ""
        if kind != "choice" or not options:
            return Answer(preferred or "Company website", "rule")
        for wanted in [preferred] + HEAR_PREFERENCES:
            idx = pick(wanted, options) if wanted else None
            if idx is None and wanted:
                idx = next((i for i, o in enumerate(options) if wanted.lower() in o.lower()), None)
            if idx is not None:
                return Answer(idx, "rule", options[idx])
        if self.llm and self.llm.enabled:
            try:
                idx = self.llm.choose(f"{question} (the candidate found the job on {preferred or 'the company website'})",
                                      options, self.p.summary(), "")
                if idx is not None:
                    return Answer(idx, "model", options[idx])
            except Exception:
                pass
        return Answer(0, "rule", options[0])

    def _employer_history(self, question):
        """'Have you been issued a Cisco employee ID / worked at Cisco…' -> No unless Cisco is a past employer."""
        company = (self.job.get("company") or "").strip()
        if not company:
            return None
        names = {company.lower(), company.split()[0].lower()}
        if not any(re.search(r"\b" + re.escape(n) + r"\b", question, re.I) for n in names if len(n) > 2):
            return None
        if not EMPLOYMENT_RE.search(question):
            return None
        past = [e.lower() for e in (self.p.get("work.past_employers") or [])]
        worked = any(n in e or e.split()[0] in n for n in names for e in past)
        return yes_no(worked)

    def _fit(self, value, kind, options, source):
        if kind == "choice":
            idx = pick(value, options)
            return Answer(idx, source, options[idx]) if idx is not None else None
        return Answer(str(value), source)

    def _ask(self, question, kind, options, required, suggestion, reason, learn=True):
        if not self.ask:
            return None
        got = self.ask(question, options, required, suggestion, reason)
        if got is None or got == "":
            return None
        if kind == "choice":
            if isinstance(got, int) and 0 <= got < len(options):
                ans = Answer(got, "you", options[got])
            else:
                idx = pick(got, options)
                ans = Answer(idx, "you", options[idx]) if idx is not None else None
        else:
            ans = Answer(str(got), "you")
        if ans and learn and self.memory and got != suggestion:
            self.memory.remember(question, ans.display or ans.value, company=self.job.get("company"))
        return ans
