"""Pure answer normalization and option selection utilities."""

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
    initials = "".join(w[0] for w in a.split() if w not in ("and", "of", "in", "the", "with"))
    if len(initials) >= 2:   # "Electronics and Communication Engineering" -> "ECE", "E.C.E."
        acr = [i for i, o in enumerate(normed) if o.replace(" ", "") == initials]
        if len(acr) == 1:
            return acr[0]
    if a == "no":   # "No" against sentence options: the one negative statement ("I have never been employed by ...")
        neg = [i for i, o in enumerate(normed) if re.match(r"(i (have|had) (never|not)|i (am|was) not|i do not|i don ?t|never|none|not )", o)]
        if len(neg) == 1:
            return neg[0]
    return None

