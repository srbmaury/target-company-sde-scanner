"""Turn a form question into an answer.

Order of precedence for each question:
  1. your own `answers:` rules in the profile
  2. `always_ask:` patterns (attestations, legal questions) -> ask you; EEO questions are exempt
  3. answers you gave before (`learned_answers:`)
  4. built-in rules mapped to profile facts and your resumes
  5. the local model, if enabled: it reasons from your facts, may infer preferences, and returns
     "unknown" otherwise; fact-only questions (citizenship, visas, clearances...) never reach it
  6. ask you (required fields) or skip (optional fields)

Every answer carries a `source` so the review summary shows where it came from.
"""

import re
from dataclasses import dataclass

from . import answerlog
from .tracker import same_company

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


EEO_RE = re.compile(r"\s*(race|ethnicity|ethnic (background|origin)|gender|sex\b|veteran|protected veteran|"
                    r"disability|hispanic|latino|self.?identif)", re.I)
# Facts only you can state: never answered by the model, whatever the prompt says.
FACT_ONLY_RE = re.compile(r"citizen|nationality|\bvisa\b|green card|permanent resident|work permit|immigration|"
                          r"clearance|criminal|convict|felony|arrest|debar|sanction|export (control|rule)|"
                          r"\bpassport\b|date of birth|\bage\b|social security|aadhaar|\bpan\b", re.I)
# Optional catch-all boxes ("Anything else you'd like us to know?") are better left blank than filled.
OPEN_EXTRA_RE = re.compile(r"anything else|additional (information|comments|details)|other comments|cover letter|^comments?$", re.I)
SIGN_RE = re.compile(r"signature|sign here|\be-?sign|type your (full |legal )?name to (sign|confirm|acknowledge)", re.I)


def same_employer(company, past):
    """Is `company` one of your past employers? Compares cleaned names ("Salesforce India" = "salesforce"),
    never substrings, so "Sales Hub" is not Salesforce."""
    return any(same_company(company, e) for e in past)


COUNTRIES = {"United States": r"\bunited states\b|\bU\.?S\.?A?\.?(?![a-z])|\bamerica\b",
             "United Kingdom": r"\bunited kingdom\b|\bU\.?K\.?(?![a-z])|\bbritain\b",
             "India": r"\bindia\b", "Canada": r"\bcanada\b", "Germany": r"\bgermany\b", "Singapore": r"\bsingapore\b",
             "Ireland": r"\bireland\b", "Australia": r"\baustralia\b", "Netherlands": r"\bnetherlands\b",
             "United Arab Emirates": r"\buae\b|united arab emirates", "Japan": r"\bjapan\b", "France": r"\bfrance\b",
             "Poland": r"\bpoland\b", "Israel": r"\bisrael\b", "Spain": r"\bspain\b"}
INDIA_CITIES = (r"bengaluru|bangalore|hyderabad|noida|gurugram|gurgaon|delhi|pune|chennai|mumbai|kolkata|"
                r"ahmedabad|jaipur|kochi|trivandrum|coimbatore|indore|chandigarh")
GENDER_SYNONYMS = {"male": "Man", "female": "Woman", "man": "Male", "woman": "Female"}
# Follow-ups that depend on an earlier answer ("If yes, ..."): built-in rules would answer the wrong question.
CONDITIONAL_RE = re.compile(r"^\s*(if (yes|so|no|applicable|you (answered|selected|chose|have))|please specify|"
                            r"(please )?(provide|share) (more )?details)", re.I)


MODEL_FAILED = object()


def yes_no(flag):
    return "Yes" if flag else "No"


def bucket(years, options):
    """Index of the range option containing `years`: "2 years to less than 3 years", "1-3 years", "5+ years",
    "Less than 1 year", "None". None when the options are not year ranges."""
    def bounds(text):
        t = text.lower().replace("–", "-")
        bare = bool(re.fullmatch(r"\s*(?:<|>|less than |more than )?\d+(?:\.\d+)?\s*(?:-\s*\d+(?:\.\d+)?|\+)?\s*(?:yrs?)?\s*", t))
        if "year" not in t and not bare and not re.search(r"\bnone\b|no experience|fresher", t):
            return None
        if re.search(r"\bnone\b|no experience|fresher|^0 years?$|^0$", t):
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


RESUME_FACT_RE = re.compile(
    r"\b(years?|months?)\b.{0,60}\bexperience\b|\bexperience\b.{0,80}\b(years?|months?)\b|how many (years|months)"
    r"|^(do|have|are) you (have )?(any )?(worked|work|experience|familiar|hands.?on|used|built|exposure)\b"
    r"|^(total |work |relevant |overall |professional )?(experience|exp\.?|years|months)( \(?in (years|months)\)?)?$"
    r"|^(key |technical |primary |core |relevant )?skills?( set)?$"
    r"|\b(live|based|reside|located) within \d+\s*(miles|mi|km|kilomet)"
    r"|^(salary |ctc |compensation |preferred |expected )?currency\b|deemed export|(previously|ever|formerly) (worked|been employed|employed) (for|at|by)|former employee|worked (for|at) .{0,40} before"
    r"|legally authori[sz]ed to work|(require|need)s? .{0,20}sponsorship|(previously|ever|already) appl(y|ied)\b"
    r"|language.{0,20}\b(fluent|speak|spoken|written)|\bfluent in\b"
    r"|^(current |home )?(location|city)( \((city|city, state|city, country)\))?$|^(current|home) (city|location)\b", re.I)


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
            return yes_no(same_employer(company, past))

        def experience_years():
            return str(g("work.total_experience_years", ""))

        def applied_before():
            """'Have you previously applied to Point72?': Yes only if your tracker has an application there."""
            if not company:
                return None
            from . import tracker
            try:
                conn = tracker.connect()
                return yes_no(any(tracker.same_company(company, r["company"]) for r in conn.execute("SELECT company FROM applications")))
            except Exception:
                return None

        def total_months():
            """Your experience in months: work.total_experience_months, else total years x 12."""
            months = g("work.total_experience_months")
            return int(months) if months not in (None, "") else int(float(g("work.total_experience_years", 0) or 0) * 12)

        def area_years(key):
            """Years in one area (design, SDLC...) when your profile sets it; else your total."""
            value = g(key)
            return str(value) if value not in (None, "") else experience_years()

        def tech_years(question):
            """'Years of experience with Kafka': your total years if a resume mentions it, else 0."""
            m = (re.search(r"(?:experience|years|worked|working)\s+(?:\w+\s+){0,2}?(?:with|in|using|on)\s+"
                           r"([A-Za-z0-9+#./ -]{2,40}?)\s*(?:\?|$|\*|\s+(?:development|programming))", question, re.I)
                 or re.search(r"(?:with|in|using|on|of)\s+([A-Za-z0-9+#./ -]{2,40}?)(?:\?|$|\s+(?:development|programming|experience))",
                              question, re.I))
            if not m:
                return experience_years()
            tech = m.group(1).strip().lower()
            if tech in ("software", "software development", "professional", "the industry", "industry", "total"):
                return experience_years()
            from . import resumes
            # every "and" part needs one of its "/" choices on a resume (full text, not a truncated preview)
            found, _missing = resumes.has_all(p, tech)
            return experience_years() if found else "0"

        def used_tech(question):
            """'Have you worked with Debezium, PeerDB?': Yes only if your resumes mention every tool named."""
            m = re.search(r"(?:worked|experience|familiar|hands.?on|used|built|exposure)\s+(?:\w+\s+){0,3}?"
                          r"(?:with|in|on|using)\s+(.+?)\??\s*[*✱]?\s*$", question, re.I)
            if not m:
                return None
            tools = [t.strip(" .?") for t in re.split(r",|/|\bor\b|\band\b", m.group(1)) if t.strip(" .?")]
            if not tools or len(tools) > 6 or any(len(t) > 30 or len(t.split()) > 3 or re.search(
                    r"\b(our|the|your|this|these|its|company|policy|policies|role|position|team|process|people|"
                    r"customers?|clients?|stakeholders?|environment|industry|domain)\b", t, re.I) for t in tools):
                return None   # a sentence, not a list of tools: leave it to the model
            from . import resumes
            if not p.resumes():
                return None
            return yes_no(resumes.has_all(p, m.group(1))[0])

        def has_credential(question):
            """'Do you hold a PMP certification?': Yes only if your resumes name it."""
            m = re.search(r"(?:hold|have|possess|earned|completed|obtained)\s+(?:an?|the)?\s*(?:active |valid |current )?"
                          r"([A-Za-z0-9+./& -]{2,60})\s+(?:certification|certificate|license|licence)\b", question, re.I)
            name = m.group(1).strip() if m else ""
            if not name or re.fullmatch(r"(any|some|relevant|professional|industry|other)", name, re.I):
                return None
            corpus = " ".join(p.resume_text(k).lower() for k in p.resumes())
            if not corpus:
                return None
            n = re.escape(name.lower())   # named as a credential, not just as a skill ("AWS" alone is not a cert)
            return yes_no(bool(re.search(rf"{n}[\w ]{{0,20}}(certif|licen)|(certif|licen)\w*[\w :]{{0,20}}{n}", corpus)))

        def where(question):
            """The country a work-authorization question is about: named in it, the job's country, or where you
            live ("the country you reside"). None when it can't be told."""
            for name, aliases in COUNTRIES.items():
                if re.search(aliases, question, re.I):
                    return name
            if re.search(r"\breside\b|\blive\b|your (current )?country", question, re.I):
                return g("personal.country")
            # otherwise: the job's country (from its location), or where you live when there is no job
            if not (self.job.get("location") or "").strip():
                return g("personal.country")   # no job location (e.g. added by URL): scans keep only your locations
            loc = f"{self.job.get('location') or ''} {self.job.get('title') or ''}"
            return next((n for n, a in COUNTRIES.items() if re.search(a, loc, re.I)), None) or (
                "India" if re.search(INDIA_CITIES, loc, re.I) else None)

        def authorized_for(question):
            country = where(question)
            if country is None:
                return None
            return yes_no(any(country.lower() == c.lower() for c in g("eligibility.authorized_countries") or []))

        def sponsorship(question):
            country = where(question)
            if country is None:
                return None
            if any(country.lower() == c.lower() for c in g("eligibility.authorized_countries") or []):
                return yes_no(g("eligibility.needs_sponsorship", False))
            return "Yes"   # not authorized there: you would need sponsorship

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
            (r"sponsor", lambda: sponsorship(self._q)),
            (r"(authori[sz]ed|eligible|right|permit(ted)?) to work|work authori[sz]ation|legally (able|eligible|authori[sz]ed)|"
             r"documentation establishing your identity", lambda: authorized_for(self._q)),
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
            (r"\b(certification|certificate|certified|license|licence)\b(?!.*(driv|vehicle))", lambda: has_credential(self._q)),
            (r"^(do|have|are) you (have )?(any )?(worked|work|experience|familiar|hands.?on|used|built|exposure)\b",
             lambda: used_tech(self._q)),
            # Bare boxes: "Experience" / "Years" / "Months" (Keka splits experience into years + months).
            (r"^(total |work |relevant |overall |professional )?(experience|exp\.?|years)( \(?in years\)?| in years)?\s*[*✱]?$",
             lambda: str(int(total_months() // 12))),
            (r"^months\s*[*✱]?$|^(total |work )?experience \(?(in )?months\)?\s*[*✱]?$", lambda: str(int(total_months() % 12))),
            (r"how many months.*(with|in|using|on) ", lambda: str(total_months()) if tech_years(self._q) != "0" else "0"),
            (r"^(key |technical |primary |core |relevant )?skills?( set)?\s*[*✱]?$",
             lambda: __import__("jobbot.resumes", fromlist=["top_skills"]).top_skills(p, self.resume_key) or None),
            (r"years of (hands.?on |professional )?experience (with|in|using|on)|how many years.*(with|in|using|on) ",
             lambda: tech_years(self._q)),
            (r"years of (professional |relevant |total |industry |work )?experience|how many years", experience_years),
            (r"experi\w*ce in (number of )?years|years of experi\w*ce", experience_years),
            (r"\bnotice period\b|when can you (start|join)|how soon can you (start|join)|earliest start|availability to join|"
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
             lambda: ", ".join(dict.fromkeys(([] if re.search(r"(other than|besides|apart from|except) english", self._q, re.I)
                                              else ["English"]) + list(g("personal.languages") or []))) or None),
            # "Do you live within 45 miles of our talent hub in India / of Bangalore?": Yes only when it names your city.
            (r"\b(live|based|reside|located) within \d+\s*(miles|mi|km|kilomet)",
             lambda: yes_no(bool(g("personal.city")) and re.search(r"\b" + re.escape(str(g("personal.city"))) + r"\b", self._q, re.I) is not None)),
            # "Currency" next to a salary box: the currency you are paid in, never a place name.
            (r"^(salary |ctc |compensation |preferred |expected )?currency\b", lambda: g("work.currency") or "INR"),
            # US export rule about releasing controlled technology to foreign nationals in the US: not an India-based role.
            (r"deemed export", lambda: "No" if not any(c.lower() in ("united states", "usa", "us")
                                                     for c in g("eligibility.authorized_countries") or []) else None),
            (r"(previously|ever|already|before) appl(y|ied)\b.{0,40}\b(to|with|at|for)\b|have you appl(y|ied) (to|with|at|for) .{0,40} before",
             lambda: applied_before()),
            (r"phone extension|\bext(ension)?\b", lambda: None),
            (r"\b(phone|mobile|contact) (number|no\.?)\b|^\s*(phone|mobile|telephone)\b(?!.*(app|develop|experience))",
             lambda: g("personal.phone")),
            (r"linkedin", lambda: g("links.linkedin")),
            (r"github", lambda: g("links.github")),
            (r"\bwebsite\b|portfolio|personal (site|url)|\bblog\b|other link", lambda: g("links.website")),
            (r"preferred (work |job )?location|locations? (are you|would you)",
             lambda: (g("preferences.preferred_work_locations") or []) + [g("personal.city")]),
            (r"address line 1|street address", lambda: g("personal.address_line1") or None),
            (r"\bpostal|\bzip\b|pin ?code", lambda: g("personal.postal_code") or None),
            # the field, not the verb: "State/Province" yes, "please state the reason for each gap" no
            (r"^(your |current |home )?(state|province|region)\b(?!\s+(the|any|your|why|whether|if|how|what)\b)|"
             r"\bstate\s*/\s*(province|region)|\b(state|province|region) of (residence|domicile)|"
             r"(which|what|select( your)?) (state|province|region)\b", lambda: g("personal.state")),
            (r"\blocation\b|\bcity\b|where are you (based|located)", lambda: g("personal.location_autocomplete") or g("personal.city")),
            (r"^country\b|country of residence|which country", lambda: g("personal.country")),
            (r"current (\(or most recent\) )?(company|employer|organi[sz]ation)|^company$|most recent (company|employer)",
             lambda: g("work.current_company")),
            (r"(current|most recent|latest) (\(or most recent\) )?(job )?title|current (role|designation)|^title$",
             lambda: g("work.current_title")),
            (r"hispanic|latin[oa]", lambda: g("eeo.hispanic_latino")),
            (r"\bgender\b|\bsex\b", lambda: [g("eeo.gender"), GENDER_SYNONYMS.get(str(g("eeo.gender") or "").lower())]),
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
        if CONDITIONAL_RE.search(q) or re.match(r"\s*search\b", q, re.I):
            return None   # a follow-up to another answer, or a job-search box on the page
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

    def _none_option(self, question, options):
        """'Select all that apply' compliance lists (sanctions, export controls): tick "None of the above";
        for the follow-up "if you selected anything other than none of the above", tick "Not applicable"."""
        opts = real_options(options or [])
        if len(opts) < 2:
            return None
        def pick(rx):
            i = next((i for i, o in enumerate(opts) if re.search(rx, o, re.I)), None)
            return Answer(i, "rule", opts[i]) if i is not None else None
        if re.search(r"if you selected .{0,40}other than .{0,10}none of the above", question, re.I):
            return pick(r"^not applicable") or pick(r"^none of (these|the above)")
        if re.search(r"select all that apply|any of the (below|following) appl", question, re.I) and \
                re.search(r"sanction|export control|embargo|cuba|iran|north korea|syria|crimea", question + " " + " ".join(opts), re.I):
            return pick(r"^none of (the above|these)|^none$|do(es)? not apply")
        return None

    def resolve(self, question, kind="text", options=None, required=False, quick=False):
        """kind: text | textarea | choice | checkbox. Returns Answer or None to leave blank.

        With the local model on, it answers every field: your profile answers, remembered answers and
        the keyword rules only suggest, and the model keeps a suggestion (exactly as written) only when
        it really answers the question. quick=True never asks you.
        """
        question = re.sub(r"\s+", " ", question or "").strip(" *:")
        none = self._none_option(question, options)
        if none is not None:
            return none
        factual = self._profile_fact(question, kind, options)
        if factual is not None:
            return factual
        if kind == "choice" and re.fullmatch(r"(?:name of (?:your )?)?(?:school|university|college|institution)(?:\s*/\s*(?:school|university|college|institution))?(?: name)?", question, re.I):
            # A generic school alias must never select another campus through rule/model fallback.
            return None
        options = real_options(options or [])
        if RESUME_FACT_RE.search(question):
            # Experience, skills and years/months come from your profile and resumes only: the model never
            # overrides them, so it cannot claim a tool your resumes do not show or put "Bangalore" in Experience.
            ans = self._by_rules(question, kind, options, False, quick=True)
            if ans is not None:
                return ans
        if not (self.llm and self.llm.enabled) or kind == "checkbox" or (
                not EEO_RE.match(question) and any(p.search(question) for p in self.always_ask)):
            return self._by_rules(question, kind, options, required, quick)   # consent boxes and always_ask stay yours
        suggestion = self._by_rules(question, kind, options, False, quick=True)
        if suggestion is None and HEAR_RE.search(question):
            suggestion = self._how_did_you_hear(question, kind, options)
        ans = self._cached(("model", question.lower(), kind, tuple(options)),
                           lambda: self._by_model(question, kind, options, suggestion))
        if ans is MODEL_FAILED:
            return self._by_rules(question, kind, options, required, quick)
        if ans is None and required and not quick:
            return self._cached(("ask", question.lower(), kind, tuple(options)), lambda: self._ask(
                question, kind, options, required, None, reason="the model could not answer"))
        if ans is not None and ans.source == "model" and kind == "textarea" and required and not quick \
                and not self.auto_drafts:
            return self._cached(("review", question.lower(), kind, tuple(options)), lambda: self._ask(
                question, kind, options, required, ans.value, reason="model draft, review it"))
        return ans

    def _profile_fact(self, question, kind, options=None):
        """User-confirmed facts cannot be replaced by a model draft or fuzzy memory."""
        q = question.lower()
        if OTHER_PERSON_RE.search(question):
            return None
        value = None
        if re.search(r"salary|compensation|\bctc\b|remuneration|pay expectation|benefit.*expect", q):
            if re.search(r"current|present|existing|previous", q):
                value = self.p.get("work.current_ctc")
            elif re.search(r"expect|desired|target|require|seeking|looking for", q):
                value = self.p.get("work.expected_ctc")
        elif "pronoun" in q:
            value = self.p.get("personal.pronouns")
        elif re.fullmatch(r"(?:your )?(?:mobile(?: phone)?|phone|telephone)(?: number)?", q):
            value = self.p.get("personal.phone")
        elif re.fullmatch(r"(?:your )?e-?mail(?: address)?", q):
            value = self.p.get("personal.email")
        elif re.search(r"(?:ever |have you |did you ).*(?:serve|served).*(?:military|armed forces)|military service", q):
            value = self.p.get("eligibility.military_service")
        elif "veteran" in q:
            value = self.p.get("eeo.veteran")
            if kind == "choice" and {o.strip().lower() for o in (options or [])} == {"yes", "no"}:
                value = self.p.get("eligibility.military_service")
        elif re.search(r"school|university|college|education|course", q) and re.search(r"start|end|graduat|completion|from|to date", q):
            end = bool(re.search(r"end|graduat|completion|to date", q))
            key = "end" if end else "start"
            month = self.p.get(f"education.{key}_month")
            if month:
                year, month_number = month.split("-")
                if "year" in q:
                    value = year
                elif "month" in q and "date" not in q:
                    import calendar
                    value = calendar.month_name[int(month_number)]
                else:
                    value = month
        elif re.fullmatch(r"(?:name of (?:your )?)?(?:school|university|college|institution)(?:\s*/\s*(?:school|university|college|institution))?(?: name)?", q):
            schools = self.p.get("education.school")
            value = schools if kind == "choice" else self.p.get("education.school_name") or (schools[0] if isinstance(schools, list) and schools else schools)
            if kind == "choice" and options:
                # Only an option naming your school: a distinctive word from your aliases (BHU, Banaras, Varanasi),
                # never just "Indian Institute of Technology", which would pick IIT Bombay.
                generic = {"indian", "institute", "technology", "of", "the", "university", "college", "school", "and", "iit", "it", "univ"}
                names = schools if isinstance(schools, list) else [schools or self.p.get("education.school_name") or ""]
                marks = {w for n in names for w in re.findall(r"[a-z]+", str(n).lower())} - generic
                ok = [i for i, o in enumerate(real_options(options)) if marks & set(re.findall(r"[a-z]+", o.lower()))]
                if not ok:
                    return None
                opts = real_options(options)
                return Answer(ok[0], "profile", opts[ok[0]])
        return self._fit(value, kind, real_options(options or []), "profile") if value is not None else None

    def _by_model(self, question, kind, options, suggestion):
        try:
            resume = self.p.resume_text(self.resume_key) if self.resume_key else ""
            shown = None if suggestion is None else (suggestion.display or str(suggestion.value))
            out = self.llm.answer(question, kind, options, self.p.facts(), resume, self.job, shown)
        except Exception:
            return MODEL_FAILED   # model unreachable or timed out: the rules answer instead
        value = out["answer"]
        if kind == "choice":
            value = self._option_index(value, options)
        if suggestion is not None and out["fits"]:
            if kind == "choice":
                same = value == suggestion.value
            else:
                a, b = str(value or "").strip().lower(), str(suggestion.value).strip().lower()
                same = not a or a in b or b in a
            # the model says the suggestion fits but wrote something else: a long-answer box gets its words
            # ("Why Acme?" is not "No"); a short field keeps your exact profile value
            if same or kind != "textarea":
                return suggestion   # the exact profile value, now checked against the question's meaning
        if out["basis"] not in ("fact", "inference") or (out["basis"] != "fact" and FACT_ONLY_RE.search(question)):
            return None
        if kind == "choice":
            if value is None:
                return None
            answerlog.record(question, options[value], self.job.get("company", ""), self.llm.last_reasoning, kind)
            return Answer(value, "model", options[value])
        value = str(value or "").strip()
        if not value or re.fullmatch(r"\W*(unknown|n/?a|none)\W*", value, re.I):
            return None
        answerlog.record(question, value, self.job.get("company", ""), self.llm.last_reasoning, kind)
        return Answer(value, "model")

    @staticmethod
    def _option_index(value, options):
        """The model's chosen option (its exact text, else the closest option) as an index, or None."""
        text = str(value if value is not None else "").strip()
        if not text:
            return None
        exact = next((i for i, o in enumerate(options) if o.strip().lower() == text.lower()), None)
        return exact if exact is not None else pick(text, options)

    def _by_rules(self, question, kind, options, required, quick):
        """Your profile answers, remembered answers and keyword rules (the model only as a last resort)."""

        hint = None   # your answer in your own words, when it matches none of the options literally
        for pattern, value in self.custom:
            if pattern.search(question):
                ans = self._fit(value, kind, options, "profile")
                if ans is not None or kind != "choice":
                    return ans
                hint = value
                break

        if self.p.get("automation.auto_sign") and kind in ("text", "textarea") and SIGN_RE.search(question):
            return Answer(self.p.full_name, "profile")   # your typed signature; Submit stays yours

        # EEO questions carry long definitions ("...Cuban, Mexican, Puerto Rican...") that must not trip
        # always_ask patterns such as sanctioned countries; their answers come from your eeo section.
        eeo = bool(EEO_RE.match(question)) or any(re.search(r"decline|prefer not|don.?t wish", o, re.I) and
                                                  re.search(r"identify|answer|disclose", o, re.I) for o in options)
        if not eeo and any(p.search(question) for p in self.always_ask):
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

        employer = None if CONDITIONAL_RE.search(question) else self._employer_history(question)
        if employer is not None:
            ans = self._fit(employer, kind, options, "rule")
            if ans is not None:
                return ans

        value = self._builtin(question)
        if value is not None:
            ans = self._fit(value, kind, options, "rule")
            if ans is not None:
                return ans
            if kind == "choice":
                hint = hint or (", ".join(value) if isinstance(value, list) else value)

        if quick:
            return None
        return self._once(question, kind, options, lambda: self._slow(question, kind, options, required, hint))

    def _once(self, question, kind, options, get):
        return self._cached((question.lower(), kind, tuple(options)), get)

    def _cached(self, key, get):
        if key not in self._settled:
            self._settled[key] = get()
        return self._settled[key]

    def _slow(self, question, kind, options, required, hint=None):
        """The model's reasoned answer (facts, or inference for preference questions), else yours.

        Optional questions get the model's answer too, but are left blank rather than asked."""
        if self.llm and self.llm.enabled and not FACT_ONLY_RE.search(question):
            try:
                resume = self.p.resume_text(self.resume_key) if self.resume_key else ""
                if kind == "choice" and options:
                    idx = self.llm.choose(question, options, self.p.summary(), resume, hint=hint, job=self.job)
                    if idx is not None:
                        answerlog.record(question, options[idx], self.job.get("company", ""),
                                         getattr(self.llm, "last_reasoning", ""), kind)
                        return Answer(idx, "model", options[idx])
                elif kind in ("text", "textarea") and (required or (
                        (kind == "textarea" or question.rstrip(" *").endswith("?"))
                        and not OPEN_EXTRA_RE.search(question))):
                    draft = self.llm.draft(question, self.job, self.p.summary(), resume,
                                           max_words=150 if kind == "textarea" else 25)
                    if draft and (self.auto_drafts or not required):
                        answerlog.record(question, draft.strip(), self.job.get("company", ""), "drafted", kind)
                        return Answer(draft.strip(), "model")
                    if required:
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
        # Never an option that claims a person sent you ("Employee referral", "Recruiter"): that would be untrue.
        safe = [i for i, o in enumerate(options) if not re.search(r"referr|employee|friend|recruiter|colleague|agency|"
                                                                  r"staffing|headhunter", o, re.I)]
        other = next((i for i in safe if re.match(r"\s*other\b", options[i], re.I)), None)
        idx = other if other is not None else (safe[0] if safe else None)
        return Answer(idx, "rule", options[idx]) if idx is not None else None

    def _employer_history(self, question):
        """'Have you been issued a Cisco employee ID / worked at Cisco…' -> No unless Cisco is a past employer."""
        company = (self.job.get("company") or "").strip()
        if not company:
            return None
        names = {company.lower(), company.split()[0].lower()}
        if not any(re.search(r"\b" + re.escape(n) + r"\b", question, re.I) for n in names if len(n) > 2):
            return None
        if not EMPLOYMENT_RE.search(question) or re.search(r"\bappl(y|ied|ication)\b", question, re.I):
            return None   # "previously applied to Acme" is about applications, not employment
        if re.match(r"\s*(why|what|how|describe|tell|explain|share|please)\b", question, re.I):
            return None   # "Why do you want to work at Acme?" wants an answer in words, not Yes/No
        return yes_no(same_employer(company, self.p.get("work.past_employers") or []))

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
