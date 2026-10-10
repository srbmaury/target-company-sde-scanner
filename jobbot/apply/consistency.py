"""Profile check: every field whose answer your profile or rules determine must show that answer.

The read-back check only confirms the page shows what jobbot typed; this one confirms what jobbot typed
(or the site pre-filled) is *your* answer. It is exact, so it decides those fields on its own: a
mismatch blocks the page whatever the model says, and a match overrides a model complaint about that
field. Free text, uploads, consent boxes and questions with no profile answer are left to the model.
"""
import re

from ..answers import HEAR_RE

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
    for f in fields:
        want = expected_answer(resolver, f)
        if want is None:
            continue
        if same_value(want, f.get("actual"), resolver.p.get("personal.phone_country_code", "")):
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
