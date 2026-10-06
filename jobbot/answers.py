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


OTHER_PERSON_RE = re.compile(r"referr(er|al|ed by)|\breference\b|emergency|next of kin|\bmanager'?s\b|hiring manager|recruiter|"
                             r"\bspouse\b|relative|guardian|parent'?s|supervisor|family member|immediate family", re.I)


def yes_no(flag):
    return "Yes" if flag else "No"


def bucket(years, options):
    """Index of the range option containing `years`: "2 years to less than 3 years", "1-3 years", "5+ years",
    "Less than 1 year", "None". None when the options are not year ranges."""
    def bounds(text):
        t = text.lower().replace("–", "-")
        if "year" not in t and not re.search(r"\bnone\b|no experience", t):
            return None
        if re.search(r"\bnone\b|no experience|^0 years?$", t):
            return (0, 0.01)
        nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", t)]
        if re.search(r"less than|under|below|<", t) and len(nums) == 1:
            return (0, nums[0])
        if re.search(r"\+|or more|more than|over|above|at least", t) and len(nums) == 1:
            return (nums[0], 99)
        if len(nums) >= 2:
            upper_open = bool(re.search(r"less than|to under|-\s*<|up to but", t))
            return (nums[0], nums[1] if upper_open else nums[1] + 1)
        if len(nums) == 1:
            return (nums[0], nums[0] + 1)
        return None
    for i, o in enumerate(options):
        b = bounds(o)
        if b and b[0] <= years < b[1]:
            return i
    return None


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
        self._q = ""
        self._first_personal_rule = next(i for i, (pat, _) in enumerate(self.rules) if pat.startswith("preferred (first )?name"))
        self.memory = memory
        # Answers that cost a model call or a question to you, settled once per application: review
        # rounds re-read the page, and must not ask you (or the model) the same thing again.
        self._settled = {}

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

        def area_years(key):
            """Years in one area (design, SDLC...) when your profile sets it; else your total."""
            value = g(key)
            return str(value) if value not in (None, "") else experience_years()

        def tech_years(question):
            """'Years of experience with Kafka': your total years if a resume mentions it, else 0."""
            m = re.search(r"(?:with|in|using|on|of)\s+([A-Za-z0-9+#./ -]{2,40}?)(?:\?|$|\s+(?:development|programming|experience))",
                          question, re.I)
            if not m:
                return experience_years()
            tech = m.group(1).strip().lower()
            if tech in ("software", "software development", "professional", "the industry", "industry", "total"):
                return experience_years()
            corpus = " ".join(p.resume_text(k).lower() for k in p.resumes())
            words = [w for w in re.findall(r"[a-z0-9+#.]+", tech) if len(w) > 1]
            return experience_years() if words and all(w in corpus for w in words) else "0"

        willing = lambda: yes_no(g("eligibility.willing_to_relocate", True))  # noqa: E731

        def open_to_place():
            """'Are you open for Bangalore location?': Yes for a place in your preferred locations or city."""
            places = g("preferences.locations") or ""
            if (places and re.search(places, self._q, re.I)) or (g("personal.city") and
                                                                  g("personal.city").lower() in self._q.lower()):
                return "Yes"
            return willing()
        # Order matters: specific yes/no policy questions first, so e.g. "relocation" never reaches the
        # location rule and "mobile development" never reaches the phone rule.
        return [
            (r"sponsor", lambda: yes_no(g("eligibility.needs_sponsorship", False))),
            (r"(authori[sz]ed|eligible|right|permit(ted)?) to work|work authori[sz]ation|legally (able|eligible|authori[sz]ed)|"
             r"documentation establishing your identity", lambda: yes_no(bool(g("eligibility.authorized_countries")))),
            (r"legal age|at least 18|over (the age of )?18", lambda: "Yes"),
            # before the "worked for / current employee" rule, which would read the government as an employer
            (r"government (employee|official|servant|agency|entity|organi[sz]ation|body|job)|public (official|servant)|"
             r"(worked|employed|work) (for|by|with|in) (the |a |any )?(government|govt)|\bgovt\b|state.?owned",
             lambda: None if OTHER_PERSON_RE.search(self._q) else (g("eligibility.government_employee") or None)),
            (r"outside (business|employment|activit)|side business|board (role|seat|member)|moonlight",
             lambda: g("work.outside_business_activities") or None),
            (r"background (check|verification)", lambda: yes_no(g("eligibility.background_check_ok", True))),
            (r"(have you )?(ever |previously )?(worked|been employed) (at|for|by)|former employee|current(ly)? .*employee|"
             r"employed by .* in the past", worked_here),
            (r"\bhybrid\b|in.?office|\bon.?site\b|work (from|in|at) (the|our) .*office|days a week|come (in )?to the office|"
             r"based in our .* office|office.?based", willing),
            (r"(open|okay|ok|comfortable|fine|willing) (for|to|with|in) .*\b(location|city|office)\b|"
             r"(open|willing|able) to (work|be based|move) (in|from|at|to) ", open_to_place),
            (r"relocat|work (on a daily basis )?in the (work )?location|able to work from|\bcommute", willing),
            (r"currently (based|located|living|residing) in|do you (live|reside) in", lambda: None),
            (r"notice period.*(negotiable|buy ?out|serve)|can you (join|start) (early|sooner|immediately)|buy ?out", lambda: "Yes"),
            (r"serving (your )?notice|on notice period|currently on notice", lambda: "No"),
            (r"willing to (work|take|do).*(shift|weekend|on.?call|night|rotational)", lambda: "Yes"),
            (r"open to (contract|full.?time|permanent)|employment type|full.?time (role|position)", lambda: "Yes"),
            # Amazon-style screeners: "Which option best describes your total non-internship ... experience?"
            (r"design (or|and) architecture|design patterns,? reliability", lambda: area_years("work.design_experience_years")),
            (r"software development life ?cycle|\bsdlc\b|code reviews?,? source control", lambda: area_years("work.sdlc_experience_years")),
            (r"(best describes|how (much|many)).*(professional|software|development|engineering|work|industry).*experience",
             experience_years),
            (r"experience (programming )?(with|in) (at least )?(one|a|any) (software )?programming language|"
             r"(know|use) (at least )?one programming language",
             lambda: yes_no(float(g("work.total_experience_years", 0) or 0) > 0 or bool(p.resumes()))),
            (r"bachelor.?s degree in computer science|degree in (computer science|cs)\b|computer science or (an? )?(equivalent|related)",
             lambda: None if g("education.cs_or_equivalent") is None else yes_no(g("education.cs_or_equivalent"))),
            (r"years of (hands.?on |professional )?experience (with|in|using|on)|how many years.*(with|in|using|on) ",
             lambda: tech_years(self._q)),
            (r"years of (professional |relevant |total |industry |work )?experience|how many years", experience_years),
            (r"\bnotice period\b|when can you (start|join)|earliest start|availability to join|"
             r"(preferred|expected|available) (start|joining) date|\bstart date\b", lambda: f"{g('work.notice_period_days')} days notice"),
            (r"current (total |annual |fixed )?(ctc|compensation|salary|cost to company|package)|present (ctc|salary)",
             lambda: g("work.current_ctc")),
            (r"expected (ctc|compensation|salary)|salary expectation|desired (salary|compensation)", lambda: g("work.expected_ctc")),
            (r"reason for (leaving|change|looking)|why are you (leaving|looking)", lambda: g("work.reason_for_change")),
            # --- facts about you (skipped for questions about other people: see OTHER_PERSON_RE) ---
            (r"preferred (first )?name|nick ?name", lambda: g("personal.preferred_name") or g("personal.first_name")),
            (r"\bfirst name|given name|legal first", lambda: g("personal.first_name")),
            (r"\blast name|family name|surname|legal last", lambda: g("personal.last_name")),
            (r"^(full |legal |your )?name\b", lambda: p.full_name),
            (r"\be-?mail\b", lambda: g("personal.email")),
            (r"country (phone )?code|phone country|dialing code", lambda: g("personal.phone_country")),
            (r"phone (device )?type|type of (phone|device)", lambda: g("personal.phone_device_type") or None),
            (r"language.*\b(fluent|speak|spoken|written|proficien)|\bfluent in\b",
             lambda: g("personal.languages") or None),
            (r"\b(phone|mobile|contact) (number|no\.?)\b|^\s*(phone|mobile|telephone)\b(?!.*(app|develop|experience))",
             lambda: g("personal.phone")),
            (r"linkedin", lambda: g("links.linkedin")),
            (r"github", lambda: g("links.github")),
            (r"\bwebsite\b|portfolio|personal (site|url)|\bblog\b|other link", lambda: g("links.website")),
            (r"preferred (work |job )?location|locations? (are you|would you)",
             lambda: (g("preferences.preferred_work_locations") or []) + [g("personal.city")]),
            (r"address line 1|street address", lambda: g("personal.address_line1") or None),
            (r"\bpostal|\bzip\b|pin ?code", lambda: g("personal.postal_code") or None),
            (r"\bstate\b|\bprovince\b|\bregion\b", lambda: g("personal.state")),
            (r"\blocation\b|\bcity\b|where are you (based|located)", lambda: g("personal.location_autocomplete") or g("personal.city")),
            (r"^country\b|country of residence|which country", lambda: g("personal.country")),
            (r"current (company|employer|organi[sz]ation)|^company$|most recent (company|employer)", lambda: g("work.current_company")),
            (r"(current|most recent|latest) (job )?title|current (role|designation)|^title$", lambda: g("work.current_title")),
            (r"hispanic|latin[oa]", lambda: g("eeo.hispanic_latino")),
            (r"\bgender\b|\bsex\b", lambda: g("eeo.gender")),
            (r"\brace\b|ethnic", lambda: g("eeo.race")),
            (r"(served|serve|service) in the (military|armed forces)|military service|armed forces",
             lambda: g("eligibility.military_service") or None),
            (r"veteran|military", lambda: g("eeo.veteran")),
            (r"disabilit", lambda: g("eeo.disability")),
            (r"how did you (hear|learn|find|come across)|source of (application|referral)|where did you (hear|find)",
             lambda: g("preferences.how_did_you_hear")),
            (r"\b(school|university|college|institution)\b(?!.*\?$)|name of (your )?(school|university|college)",
             lambda: g("education.school")),
            (r"\bdegree\b(?!.*\?$)|highest (level of )?(education|qualification)|level of education", lambda: g("education.degree")),
            (r"\bmajor\b|field of study|discipline|specialization", lambda: g("education.field")),
            (r"\bc?gpa\b|\bgrade\b|\bpercentage\b|overall result", lambda: g("education.gpa")),
            (r"graduat(ion|ed) (year|date)|year of (graduation|passing)|expected graduation", lambda: str(g("education.end_year", ""))),
        ]

    def _builtin(self, question):
        q = question.strip()
        self._q = q
        about_someone_else = bool(OTHER_PERSON_RE.search(q))
        m = re.search(r"currently (?:based|located|living|residing) in ([A-Za-z ,/]+)|do you (?:live|reside) in ([A-Za-z ,/]+)", q, re.I)
        if m:
            place = (m.group(1) or m.group(2) or "").lower()
            return yes_no(str(self.p.get("personal.city", "")).lower() in place)
        for i, (pattern, fn) in enumerate(self.rules):
            if about_someone_else and i >= self._first_personal_rule:
                return None  # never put your own name/email/phone into a referrer or contact field
            if re.search(pattern, q, re.I):
                value = fn()
                if isinstance(value, (list, tuple)):   # alternatives, best first (empty entries dropped)
                    value = [str(v) for v in value if v not in (None, "")]
                    return value or None
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
            return self._once(question, kind, options, lambda: self._ask(
                question, kind, options, required, None, reason="needs your confirmation", learn=False))

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
        return self._once(question, kind, options, lambda: self._slow(question, kind, options, required))

    def _once(self, question, kind, options, get):
        key = (question.lower(), kind, tuple(options))
        if key not in self._settled:
            self._settled[key] = get()
        return self._settled[key]

    def _slow(self, question, kind, options, required):
        """The model's answer, else yours."""
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
        if kind == "choice" and isinstance(value, str) and re.fullmatch(r"\d+(\.\d+)?", value):
            idx = bucket(float(value), options)   # "2" against "2 years to less than 3 years", "1-3 years"...
            if idx is not None:
                return Answer(idx, source, options[idx])
        if isinstance(value, (list, tuple)):   # e.g. preferred locations: the first one the form offers
            if kind != "choice":
                return Answer(", ".join(map(str, value)), source) if value else None
            return next((a for a in (self._fit(v, kind, options, source) for v in value) if a), None)
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
