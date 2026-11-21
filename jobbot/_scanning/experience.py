"""Pure experience-requirement parsing shared by scanning and fallback ranking."""

import re

YEARS = re.compile(
    r"(?<![\d.])(?P<low>\d+(?:\.\d+)?)"
    r"(?:\s*(?P<open>\+|plus)|\s*(?:-|–|—|to)\s*(?P<high>\d+(?:\.\d+)?)(?P<high_open>\s*\+)?)?"
    r"\s*(?:years?|yrs?)\b",
    re.I,
)


def validate_experience_range(min_yoe, max_yoe):
    if any(type(value) is not int or value < 0 for value in (min_yoe, max_yoe)) or min_yoe > max_yoe:
        raise ValueError("Set min_yoe and max_yoe to non-negative whole numbers with min_yoe <= max_yoe.")


def experience_bounds(match):
    low = float(match["low"])
    if match["open"] or match["high_open"] or not match["high"]:
        return low, float("inf")
    return low, float(match["high"])


REQUIRED_RE = re.compile(r"minimum|at least|required|must have|must possess|requirement|qualifications?:", re.I)
PREFERRED_RE = re.compile(r"preferred|nice to have|bonus|plus|ideally|desired", re.I)


def stated_experience(text):
    """Return ((min_years, max_years), snippet) for the posting's experience requirement. "5+ years preferred ... 2+ years
    required" is 2: a stated requirement wins over a preference, and among several the lowest counts."""
    found = []
    for m in YEARS.finditer(text or ""):
        low, high = experience_bounds(m)
        if high < low:
            continue
        # Keep neighboring sentences from lending their qualification markers to this match.
        left = re.split(r"[.!?;]\s+|\n", text[max(0, m.start() - 60):m.start()])[-1]
        right = re.split(r"[.!?;](?:\s+|$)|\n", text[m.end():m.end() + 50])[0]
        context = left + m.group() + right
        if re.search(r"experience|exp\b|expertise|professional|industry|hands-on|relevant|engineering|building|working|develop", context, re.I):
            near = left[-40:] + m.group() + right[:40]
            rank = 0 if REQUIRED_RE.search(near) else (2 if PREFERRED_RE.search(near) else 1)
            found.append((rank, low, high, context.strip()))
    if not found:
        return None, ""
    _, low, high, context = min(found)
    return (low, high), context


def stated_years(text):
    bounds, snippet = stated_experience(text)
    return (bounds[0] if bounds else None), snippet

