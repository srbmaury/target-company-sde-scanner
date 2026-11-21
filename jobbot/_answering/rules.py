"""Ordered rules for answering application questions from candidate facts."""

import re

from .options import yes_no
from .patterns import COUNTRIES, GENDER_SYNONYMS, INDIA_CITIES, OTHER_PERSON_RE, same_employer


def build_rules(profile, job, resume_key, current_question):
    """Return question patterns and callbacks in matching order."""
    p, g = profile, profile.get
    company = (job.get("company") or "").lower()
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
        from .. import tracker
        try:
            conn = tracker.connect()
            try:
                rows = conn.execute("SELECT company FROM applications").fetchall()
            finally:
                conn.close()   # asked on many applications in a long run: never leak a connection per question
            return yes_no(any(tracker.same_company(company, r["company"]) for r in rows))
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
        """'Years of experience with Kafka': your total years if a resume mentions it, otherwise ask."""
        m = (re.search(r"(?:experience|years|worked|working)\s+(?:\w+\s+){0,2}?(?:with|in|using|on)\s+"
                       r"([A-Za-z0-9+#./ -]{2,40}?)\s*(?:\?|$|\*|\s+(?:development|programming))", question, re.I)
             or re.search(r"(?:with|in|using|on|of)\s+([A-Za-z0-9+#./ -]{2,40}?)(?:\?|$|\s+(?:development|programming|experience))",
                          question, re.I))
        if not m:
            return experience_years()
        tech = m.group(1).strip().lower()
        if tech in ("software", "software development", "professional", "the industry", "industry", "total"):
            return experience_years()
        from .. import resumes
        # every "and" part needs one of its "/" choices on a resume (full text, not a truncated preview)
        found, _missing = resumes.has_all(p, tech)
        return experience_years() if found else None

    def tools_statement(question):
        """'Share your hands-on experience with AWS services like S3, EKS, or MSK': name what your resumes show,
        say plainly what they don't, and invent no projects or use cases."""
        m = re.search(r"\b(?:experience|work)\s+(?:with|using|in|on)\s+(.+?)(?:\?|\.\s|$)", question, re.I)
        if not m:
            return None
        from .. import resumes
        phrase = re.sub(r"\b(services?|tools?|technologies|platforms?|frameworks?|like|such as|e\.g\.?|including|etc)\b", ",", m.group(1), flags=re.I)
        items = [x.strip(" .") for x in re.split(r",|/|\bor\b|\band\b", phrase) if x.strip(" .")]
        items = [x for x in items if 1 < len(x) <= 25 and len(x.split()) <= 3][:8]
        if not items or not p.resumes():
            return None
        have = [x for x in items if resumes.mentions(p, x)]
        lack = [x for x in items if x not in have]
        join = lambda xs: xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]  # noqa: E731
        parts = []
        if have:
            parts.append(f"I have hands-on experience with {join(have)}, as listed on my resume.")
        if lack:
            return None
        return " ".join(parts)

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
        from .. import resumes
        if not p.resumes():
            return None
        return "Yes" if resumes.has_all(p, m.group(1))[0] else None

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
        if not (job.get("location") or "").strip():
            return g("personal.country")   # no job location (e.g. added by URL): scans keep only your locations
        loc = f"{job.get('location') or ''} {job.get('title') or ''}"
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
        if (places and re.search(places, current_question(), re.I)) or (g("personal.city") and
                                                              g("personal.city").lower() in current_question().lower()):
            return "Yes"
        return willing()
    # Order matters: specific yes/no policy questions first, so e.g. "relocation" never reaches the
    # location rule and "mobile development" never reaches the phone rule.
    return [
        (r"sponsor|\brequir\w*\b.{0,80}\b(visa|work permit|right to work support)\b", lambda: sponsorship(current_question())),
        (r"(authori[sz]ed|eligible|right|permit(ted)?) to work|work authori[sz]ation|legally (able|eligible|authori[sz]ed)|"
         r"documentation establishing your identity", lambda: authorized_for(current_question())),
        (r"legal age|at least 18|over (the age of )?18", lambda: "Yes"),
        # before the "worked for / current employee" rule, which would read the government as an employer
        (r"government (employee|official|servant|agency|entity|organi[sz]ation|body|job)|public (official|servant)|"
         r"(worked|employed|work) (for|by|with|in) (the |a |any )?(government|govt)|\bgovt\b|state.?owned",
         lambda: None if OTHER_PERSON_RE.search(current_question()) else (g("eligibility.government_employee") or None)),
        (r"outside (business|employment|activit)|side business|board (role|seat|member)|moonlight",
         lambda: g("work.outside_business_activities") or None),
        (r"background (check|verification)", lambda: yes_no(g("eligibility.background_check_ok", True))),
        (r"(have you )?(ever |previously )?(worked|been employed) (at|for|by)|former employee|current(ly)? .*employee|"
         r"employed by .* in the past", worked_here),
        (r"\bhybrid\b|in.?office|\bon.?site\b|work (from|in|at) (the|our) .*office|days a week|come (in )?to the office|"
         r"based in our .* office|office.?based", willing),
        (r"(open|okay|ok|comfortable|fine|willing|happy) (working |to work )?(for|to|with|in|at|from) .*\b(location|city|office)\b|"
         r"(open|willing|able) to (work|be based|move) (in|from|at|to) ", open_to_place),
        (r"relocat|work (on a daily basis )?in the (work )?location|able to work from|\bcommute", willing),
        (r"(?<!city )(?<!town )(currently (based|located|living|residing) in|do you (live|reside) in)\b(?!\s*\?)", lambda: None),
        (r"notice period.*(negotiable|buy ?out|serve)|can you (join|start) (early|sooner|immediately)|buy ?out", lambda: "Yes"),
        # "If serving, when is your last working day?": you are not serving notice (rule below)
        (r"if (you are |you.re )?serving|last working (day|date)|\blwd\b", lambda: "Not applicable - not currently serving notice"),
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
        (r"\b(certification|certificate|certified|license|licence)\b(?!.*(driv|vehicle))", lambda: has_credential(current_question())),
        (r"^(do|have|are) you (have )?(any )?(worked|work|experience|familiar|hands.?on|used|built|exposure)\b",
         lambda: used_tech(current_question())),
        # Bare boxes: "Experience" / "Years" / "Months" (Keka splits experience into years + months).
        (r"^(total |work |relevant |overall |professional )?(experience|exp\.?|years)( \(?in years\)?| in years)?\s*[*✱]?$",
         lambda: str(int(total_months() // 12))),
        (r"^months\s*[*✱]?$|^(total |work )?experience \(?(in )?months\)?\s*[*✱]?$", lambda: str(int(total_months() % 12))),
        (r"how many months.*(with|in|using|on) ", lambda: str(total_months()) if tech_years(current_question()) is not None else None),
        (r"^(key |technical |primary |core |relevant )?skills?( set)?\s*[*✱]?$",
         lambda: __import__("jobbot.resumes", fromlist=["top_skills"]).top_skills(p, resume_key) or None),
        (r"^(please )?(share|describe|tell us about|explain|walk us through) (your )?(hands.?on |practical |professional )?"
         r"(experience|work) (with|using|in|on)\b", lambda: tools_statement(current_question())),
        (r"years of (hands.?on |professional )?experience (with|in|using|on)|how many years.*(with|in|using|on) ",
         lambda: tech_years(current_question())),
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
         lambda: ", ".join(dict.fromkeys(([] if re.search(r"(other than|besides|apart from|except) english", current_question(), re.I)
                                          else ["English"]) + list(g("personal.languages") or []))) or None),
        # "Do you live within 45 miles of our talent hub in India / of Bangalore?": Yes only when it names your city.
        (r"\b(live|based|reside|located) within \d+\s*(miles|mi|km|kilomet)",
         lambda: yes_no(bool(g("personal.city")) and re.search(r"\b" + re.escape(str(g("personal.city"))) + r"\b", current_question(), re.I) is not None)),
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
        (r"address line 1|street address|\bhome address\b|\bresidential address\b", lambda: g("personal.address_line1") or None),
        (r"\bpostal|\bzip\b|pin ?code", lambda: g("personal.postal_code") or None),
        # the field, not the verb: "State/Province" yes, "please state the reason for each gap" no
        (r"^(your |current |home )?(state|province|region)\b(?!\s+(the|any|your|why|whether|if|how|what)\b)|"
         r"\bstate\s*/\s*(province|region)|\b(state|province|region) of (residence|domicile)|"
         r"(which|what|select( your)?) (state|province|region)\b", lambda: g("personal.state")),
        (r"\blocation\b|\bcity\b|where are you (based|located)|where do you (live|reside)\b|place of residence",
         lambda: g("personal.location_autocomplete") or g("personal.city")),
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
