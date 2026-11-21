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

from ._answering import log as answerlog
from ._answering.options import (
    Answer as Answer, bucket as bucket, norm as norm, pick as pick,
    real_options as real_options, yes_no as yes_no,
)
from ._answering.patterns import (
    CONDITIONAL_RE, EEO_RE, EMPLOYMENT_RE, FACT_ONLY_RE, HEAR_EVENT, HEAR_PREFERENCES,
    HEAR_RE, HEAR_WHOLE_ONLY, MODEL_FAILED, OPEN_EXTRA_RE, OTHER_PERSON_RE, RESUME_FACT_RE,
    SIGN_RE, SOCIAL_KEYS, SOCIAL_RE, same_employer,
)
from ._answering.rules import build_rules


class Resolver:
    def __init__(self, profile, llm=None, job=None, resume_key=None, ask=None, memory=None, auto_drafts=False, profile_first=False, warn=None):
        self.profile_first = profile_first
        self.warn = warn
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

    def _rules(self):
        return build_rules(self.p, self.job, self.resume_key, lambda: self._q)

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

    def resolve(self, question, kind="text", options=None, required=False, quick=False, context=None):
        """Resolve a field from profile facts, rules, optional model, or user input.

        context describes the field without changing the label used by deterministic
        rules. quick=True never asks you.
        """
        question = re.sub(r"\s+", " ", question or "").strip(" *:")
        self._q = question
        context = {key: value for key, value in (context or {}).items() if value}
        conditional = bool(re.match(r"^(if|when)\b", question, re.I))
        parent = context.get("parent") or {}
        if parent and conditional:
            condition = re.match(r"^if\s+(yes|no|so)\b", question, re.I)
            answer = str(parent.get("answer", "")).strip().lower()
            applicable = condition and answer in ("yes", "no")
            if applicable and answer != ("yes" if condition[1].lower() == "so" else condition[1].lower()):
                return None
            options = real_options(options or [])
            key = (question.lower(), kind, tuple(options), repr(context))
            if applicable and not self.profile_first and self.llm and self.llm.enabled and kind != "checkbox" and not any(
                    pattern.search(question) for pattern in self.always_ask):
                draft = self._cached(("follow-up", *key), lambda: self._by_model(question, kind, options, None, context))
                if draft is not None and draft is not MODEL_FAILED:
                    if kind != "textarea" or self.auto_drafts or not required:
                        return draft
                    if not quick:
                        return self._cached(("follow-up review", *key), lambda: self._ask(
                            question, kind, options, required, draft.value, reason="review the follow-up draft", learn=False))
            return self._cached(("follow-up ask", *key), lambda: self._ask(
                question, kind, options, required, None,
                reason=f"follow-up to “{parent.get('question', '')}”", learn=False)) if required and not quick else None
        if not parent and not required and re.match(r"\s*if (yes|so|applicable|you (answered|selected|chose))\b", question, re.I):
            return None   # an optional follow-up to another answer ("If you answered Other, please specify"): blank
        employer = self.job.get("company") or ""
        past = list(self.p.get("work.past_employers") or []) + [self.p.get("work.current_company") or ""]
        worked_here = bool(employer) and same_employer(employer, [e for e in past if e])
        if not parent and kind in ("text", "textarea") and re.match(r"\s*if (yes|so)\b", question, re.I) and \
                re.search(r"visa|sponsor|relative|related to|family|government|convict|referr" +
                          ("" if worked_here else r"|worked (for|at)|employed by"), question, re.I):
            # the parent question ("Are you on a visa?", "Do you have relatives here?") is a No from your profile
            return Answer("Not applicable", "rule")
        none = self._none_option(question, options)
        if none is not None:
            return none
        if kind == "choice" and options and re.search(r"\bmajor\b|field of study|discipline|specialization|\bbranch\b.*(major|study|engineering|degree)", question, re.I):
            # Your branch from the profile, else "Other": never the model's guess ("CS" for an ECE graduate).
            opts = real_options(options)
            i = pick(self.p.get("education.field") or "", opts)
            if i is None:
                i = next((j for j, o in enumerate(opts) if re.fullmatch(r"\s*others?\b.*", o, re.I)), None)
            return Answer(i, "profile", opts[i]) if i is not None else None
        factual = self._profile_fact(question, kind, options)
        if factual is not None:
            return factual
        if kind == "choice" and re.fullmatch(r"(?:name of (?:your )?)?(?:school|university|college|institution)(?:\s*/\s*(?:school|university|college|institution))?(?: name)?", question, re.I):
            # A generic school alias must never select another campus through rule/model fallback.
            return None
        options = real_options(options or [])
        social = SOCIAL_RE.search(question)
        if social:
            # Social profiles come from your profile's links only: a model must not invent one (it once put
            # "Telangana" in Facebook). A network you do not list stays blank.
            return self._fit(self.p.get(f"links.{SOCIAL_KEYS.get(social.group(1).lower(), social.group(1).lower())}"),
                             kind, options, "profile") if self.p.get(
                f"links.{SOCIAL_KEYS.get(social.group(1).lower(), social.group(1).lower())}") else None
        if self.profile_first:
            return self._by_rules(question, kind, options, required, quick)
        if RESUME_FACT_RE.search(question):
            # Experience, skills and years/months come from your profile and resumes only: the model never
            # overrides them, so it cannot claim a tool your resumes do not show or put "Bangalore" in Experience.
            ans = self._by_rules(question, kind, options, False, quick=True)
            if ans is not None:
                return ans
            return self._by_rules(question, kind, options, required, quick)
        if not (self.llm and self.llm.enabled) or kind == "checkbox" or (
                not EEO_RE.match(question) and any(p.search(question) for p in self.always_ask)):
            return self._by_rules(question, kind, options, required, quick)   # consent boxes and always_ask stay yours
        if HEAR_RE.search(question) and kind == "choice" and options:
            # Where you found the job is your profile's answer (company website) mapped onto the site's list
            # ("Carrers"): the model second-guessing it only left such boxes blank.
            return self._how_did_you_hear(question, kind, options)
        suggestion = self._by_rules(question, kind, options, False, quick=True)
        if suggestion is None and HEAR_RE.search(question):
            suggestion = self._how_did_you_hear(question, kind, options)
        # Same label can mean different things in different sections of an application.
        context_key = repr(context)
        ans = self._cached(("model", question.lower(), kind, tuple(options), context_key),
                           lambda: self._by_model(question, kind, options, suggestion, context))
        if ans is MODEL_FAILED:
            return self._by_rules(question, kind, options, required, quick)
        if ans is None and required and not quick:
            return self._cached(("ask", question.lower(), kind, tuple(options), context_key), lambda: self._ask(
                question, kind, options, required, None, reason="the model could not answer"))
        if ans is not None and ans.source == "model" and kind == "textarea" and required and not quick \
                and not self.auto_drafts:
            return self._cached(("review", question.lower(), kind, tuple(options), context_key), lambda: self._ask(
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
        elif (re.search(r"school|university|college|education|course", q) and re.search(r"start|end|graduat|completion|from|to date", q)) \
                or re.fullmatch(r"(start|end) date (month|year)", q) or re.search(r"\b(year|when) did you graduate|graduation year", q):
            # Greenhouse's education block asks "Start date year" / "End date month" with no school word
            end = bool(re.search(r"end|graduat|completion|to date", q))
            key = "end" if end else "start"
            month = self.p.get(f"education.{key}_month")
            if month:
                year, month_number = month.split("-")
                if "year" in q:
                    value = year
                elif "month" in q and ("date" not in q or q.endswith("date month")):
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

    def _by_model(self, question, kind, options, suggestion, context=None):
        try:
            resume = self.p.resume_text(self.resume_key) if self.resume_key else ""
            shown = None if suggestion is None else (suggestion.display or str(suggestion.value))
            out = self.llm.answer(question, kind, options, self.p.facts(), resume, self.job, shown,
                                  **({"context": context} if context else {}))
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
        """Accept only a unique visible option with the same text."""
        text = str(value if value is not None else "").strip()
        if not text:
            return None
        normalize = lambda s: " ".join(s.split()).casefold()
        exact = [i for i, o in enumerate(options) if normalize(o) == normalize(text)]
        return exact[0] if len(exact) == 1 else None

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
            if self.profile_first and (quick or not required):
                return None
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

        if HEAR_RE.search(question) and (not quick or self.profile_first):
            answer = self._how_did_you_hear(question, kind, options)
            if answer is not None:
                return answer

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

        if quick or (self.profile_first and not required):
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
        if not self.profile_first and self.llm and self.llm.enabled and not FACT_ONLY_RE.search(question) and not RESUME_FACT_RE.search(question):
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
            if idx is None and wanted and wanted.lower() not in HEAR_WHOLE_ONLY:
                # "company website" inside "Company Website / Careers Page"; never an event ("Career Fair")
                idx = next((i for i, o in enumerate(options) if wanted.lower() in o.lower()
                            and not HEAR_EVENT.search(o)), None)
            if idx is not None and HEAR_EVENT.search(options[idx]):
                idx = None
            if idx is not None:
                return Answer(idx, "rule", options[idx])
        if not self.profile_first and self.llm and self.llm.enabled:
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
        if self.profile_first:
            return None
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
            if idx is None and str(value).strip().lower() == "yes":
                # "Comfortable working from our Bengaluru office?" offering "Bengaluru" / "Others": a Yes is
                # the one option naming a place the question names.
                q = getattr(self, "_q", "") or ""
                named = [i for i, o in enumerate(options) if len(norm(o)) > 2 and not re.match(r"others?\b", norm(o))
                         and re.search(r"\b" + re.escape(norm(o)) + r"\b", norm(q))]
                idx = named[0] if len(named) == 1 else None
            return Answer(idx, source, options[idx]) if idx is not None else None
        return Answer(str(value), source)

    def remember_answer(self, question, value):
        if (self.memory and not any(p.search(question) for p in self.always_ask)
                and not re.search(r"password|verification code|security code|one.time|\botp\b|\bconsent\b|\bsignature\b|\bour (company|team|role)\b", question, re.I)
                and not FACT_ONLY_RE.search(question)):
            try:
                self.memory.remember(question, value, company=self.job.get("company"))
            except Exception as exc:
                if self.warn:
                    self.warn(f"Could not save this learned answer ({type(exc).__name__}).")

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
            self.remember_answer(question, ans.display or ans.value)
        return ans
