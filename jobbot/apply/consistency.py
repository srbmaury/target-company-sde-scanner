"""Profile check: every field whose answer your profile or rules determine must show that answer.

The read-back check only confirms the page shows what jobbot typed; this one confirms what jobbot typed
(or the site pre-filled) is *your* answer. It is exact, so it decides those fields on its own: a
mismatch blocks the page whatever the model says, and a match overrides a model complaint about that
field. Free text, uploads, consent boxes and questions with no profile answer are left to the model.
"""
import re

from ..answers import HEAR_RE, SOCIAL_KEYS, SOCIAL_RE

TRUSTED = ("profile", "rule", "remembered")
CHOICE_KINDS = ("select", "combo", "radio", "yesno", "listbutton", "checkgroup")
SKIP_LABEL = re.compile(r"consent|privacy|acknowledge|agree|terms|certify|signature|captcha|password|"
                        r"cover letter|why |describe|tell us|explain|additional information", re.I)


def _words(text):
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower())) - {"the", "of", "and", "a", "an"}


YES_NO = {"yes", "no", "true", "false"}


def same_value(expected, actual, dial_code=""):
    """Does the page show your answer? Phone numbers by their last 10 digits, numbers by value,
    everything else by words: "India" matches "India +91", but not "British Indian Ocean Territory".
    A phone-country box that shows only your dialling code ("+91") matches; a list of your choices
    ("Hyderabad, Bengaluru, ...") matches any one of them."""
    e, a = str(expected or "").strip(), str(actual or "").strip()
    if not e:
        return True
    if not a:
        return False
    if dial_code and re.fullmatch(r"\+?\d{1,4}", a) and a.lstrip("+") == str(dial_code).lstrip("+"):
        return True
    if e.lower() in YES_NO and a.lower() not in YES_NO:
        return True   # a Yes/No rule met a question with other answers ("source of your right to work"): not comparable
    if re.match(r"https?://|www\.", e, re.I) or "@" in e:   # a URL or an email: exactly yours
        url = lambda t: re.sub(r"^(https?://)?(www\.)?", "", t.lower()).rstrip("/")  # noqa: E731
        return url(e) == url(a)
    if len(e.split()) >= 8 and len(a.split()) >= 8:
        # sentence-long options differ by one word ("I am not ..." vs "I am ..."): whole text, not word sets
        norm = lambda t: re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()  # noqa: E731
        return norm(e) == norm(a)
    parts = [x for x in re.split(r"\s*[,;]\s*", e) if x]
    if len(parts) >= 4:   # your list of choices ("Hyderabad, Bengaluru, Noida, ..."), not "City, State, Country"
        return any(_words(x) and _words(x) <= _words(a) for x in parts) or _words(a) <= _words(e)
    de, da = re.sub(r"\D", "", e), re.sub(r"\D", "", a)
    if len(de) >= 7 and len(de) >= len(re.sub(r"[\s+()-]", "", e)) - 1:   # a phone number
        return de[-10:] == da[-10:]
    if re.fullmatch(r"\d+(\.\d+)?", e) and re.fullmatch(r"\d+(\.\d+)?", a):
        return float(e) == float(a)
    we, wa = _words(e), _words(a)
    return bool(we) and (we <= wa or (bool(wa) and wa <= we))


def expected_answer(resolver, field):
    """Your answer to this field from the profile and rules only (never the model, never asking you),
    or None when they do not determine it."""
    label, kind = field.get("label") or "", field.get("kind")
    if kind in ("file", "checkbox", "textarea") or SKIP_LABEL.search(label) or label == "(unlabelled field)":
        return None
    options = field.get("options") or []
    choice = kind in CHOICE_KINDS and bool(options)   # a type-ahead box stores no option list: compare text
    q = re.sub(r"\s+", " ", label).strip(" *:")
    if HEAR_RE.search(q):
        return None   # "how did you hear about us" picks from the site's own list: not a fact about you
    # Rules only: no model and no questions in the middle of a review. The resolver's rules are bound to
    # this very object, so pause its model and questions instead of copying it, and restore them after.
    saved = resolver.llm, resolver.ask
    resolver.llm, resolver.ask = None, None
    try:
        ans = resolver._profile_fact(q, "choice" if choice else "text", options) or \
            resolver._by_rules(q, "choice" if choice else "text", options, False, True)
    except Exception:
        return None
    finally:
        resolver.llm, resolver.ask = saved
    if ans is None or ans.source not in TRUSTED:
        return None
    value = ans.display or ("" if isinstance(ans.value, int) and choice else str(ans.value))
    if not value or len(value) > 120:   # long rule answers are prose: the model reviews those
        return None
    return value


def check(resolver, fields):
    """(mismatches, confirmed ids): fields that contradict your profile, and fields that match it."""
    mismatches, confirmed = [], set()
    schools = resolver.p.get("education.school") or []
    schools = [str(x) for x in (schools if isinstance(schools, list) else [schools])]
    from .email_verification import CODE_RE
    from .verify import HEAR_OPTION_RE
    hear = [f for f in fields if f.get("kind") == "checkbox" and HEAR_OPTION_RE.fullmatch((f.get("label") or "").strip(" *"))]
    if any(str(f.get("actual")) == "checked" for f in hear):
        confirmed |= {f["id"] for f in hear}   # "how did you hear about us": one ticked option answers the group
    for f in fields:
        if f["id"] in confirmed:
            continue
        actual = str(f.get("actual") or "").strip()
        if CODE_RE.search(f.get("label") or "") and actual:
            # a code box filled from your email: one character per box, so a model reviewing boxes
            # one by one calls it "incomplete"; jobbot entered the exact emailed code
            confirmed.add(f["id"])
            continue
        if f.get("kind") == "file" and re.search(r"\.(pdf|docx?|rtf|txt)\b", actual, re.I):
            confirmed.add(f["id"])   # your resume is attached (the upload itself is checked when attaching)
            continue
        if not actual and not f.get("required"):
            confirmed.add(f["id"])   # an optional field left blank (e.g. Ashby's "Autofill from resume") is never a block
            continue
        if f.get("kind") == "textarea" and actual:
            if free_text_ok(actual, resolver):
                confirmed.add(f["id"])   # passes the exact checks: a model's wording complaint will not block it
            continue
        social = SOCIAL_RE.search(f.get("label") or "")
        if social and actual and not resolver.p.get(
                "links." + SOCIAL_KEYS.get(social.group(1).lower(), social.group(1).lower())):
            mismatches.append((f, "(blank: not a profile you listed)"))   # e.g. "Telangana" typed into Facebook
            continue
        want = expected_answer(resolver, f)
        if want is None:
            continue
        # your school goes by several names (profile education.school); a site may show any of them
        names = [want] + (schools if re.search(r"school|university|college|institut", f.get("label") or "", re.I) else [])
        if any(same_value(w, f.get("actual"), resolver.p.get("personal.phone_country_code", "")) for w in names):
            confirmed.add(f["id"])
        elif str(f.get("actual") or "").strip() or f.get("required"):
            mismatches.append((f, want))
    return mismatches, confirmed


def apply(session, page, resolver, report, check_result):
    """Run the profile check on this page: mismatches block it (and are re-filled next round).
    Returns the ids of fields confirmed to match your profile, for the model review."""
    mismatches, confirmed = check(resolver, session.audit_fields(page, report))
    for f, want in mismatches:
        check_result.mismatches.append((f["label"], want, str(f.get("actual") or "")))
    return confirmed


_COMPANIES = None


def _companies():
    """Company names from the registry, for spotting an answer that names the wrong employer."""
    global _COMPANIES
    if _COMPANIES is None:
        import json
        from .. import paths
        try:
            data = json.loads((paths.REPO / "references" / "ats-registry.json").read_text(encoding="utf-8"))
            _COMPANIES = [c for c in data.get("companies", {}) if len(c) >= 4]
        except (OSError, ValueError, AttributeError):
            _COMPANIES = []
    return _COMPANIES


def free_text_ok(text, resolver):
    """A free-text answer passes when it is a real answer, names no other company than this employer and
    your past employers, and claims no more years of experience than your profile."""
    if len(re.findall(r"[A-Za-z]{2,}", text)) < 4 or re.fullmatch(r"\W*(n/?a|none|test|asdf+|lorem.*)\W*", text, re.I):
        return False
    from ..tracker import same_company
    allowed = [resolver.job.get("company") or ""] + list(resolver.p.get("work.past_employers") or []) + \
        [resolver.p.get("work.current_company") or ""]
    for name in _companies():
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", text) and \
                not any(a and same_company(name, a) for a in allowed):
            return False
    years = float(resolver.p.get("work.total_experience_years", 0) or 0)
    claims = [float(n) for n in re.findall(r"(\d+(?:\.\d+)?)\+?\s*(?:years|yrs)", text, re.I)]
    return not any(n > years + 1 for n in claims)
