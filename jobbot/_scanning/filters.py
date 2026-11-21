"""Pure title, location and experience filters for discovered vacancies."""

import re

from .experience import YEARS, experience_bounds, stated_experience

DEFAULT_MIN_YOE = 1
DEFAULT_MAX_YOE = 3

ENGINEERING = re.compile(
    r"engineer|developer|\bsde\b|software|programmer|member of technical staff|\bmts\b|computer scientist",
    re.I,
)
NOT_ENGINEERING = re.compile(
    r"sales|solutions? engineer|customer|support|account|recruit|partner|field|"
    r"technical program|program manager|product manager|designer|marketing|consultant|"
    r"\bqa\b|quality|\btest|sdet|verification|asic|silicon|analyst|advocate|writer|security engineer|"
    r"network engineer|\bnoc\b|it service|\bit engineer|technical publication",
    re.I,
)
SENIOR = re.compile(
    r"\bsenior\b|\bsr\.?\b|(?<!technical )\bstaff\b|\bprincipal\b|\blead\b|"
    r"\bmanager\b|\bdirector\b|head of|\barchitect\b|\bdistinguished\b|\bfellow\b",
    re.I,
)
ENTRY_LEVEL = re.compile(r"\bintern(?:ship)?\b|\bapprentice\b|\bnew grad(?:uate)?\b|"
                         r"\bgraduate\b|\bcampus\b|\btrainee\b", re.I)
MID_LEVEL = re.compile(r"\bii\b|\b2\b|sde\s*-?\s*2|mid[- ]level|engineer\s*2|\bl[34]\b|\bmts\b", re.I)

def classify(job, location_re, max_yoe, min_yoe=DEFAULT_MIN_YOE):
    title, loc = job["title"] or "", job["location"] or ""
    if not ENGINEERING.search(title) or NOT_ENGINEERING.search(title) or not location_re.search(loc):
        return None
    if (max_yoe <= DEFAULT_MAX_YOE and SENIOR.search(title)) or (min_yoe > 0 and ENTRY_LEVEL.search(title)):
        return None
    in_title = YEARS.search(title)
    if in_title:
        bounds, snippet, source = experience_bounds(in_title), title, "in title"
    else:
        bounds, snippet = stated_experience(job.get("text"))
        source = "stated"
    if bounds:
        low, high = bounds
        if high < low or low > max_yoe or high < min_yoe:
            return None
        years = f"{low:g}+" if high == float("inf") else f"{low:g}–{high:g}"
        return f"{years} yrs {source}", snippet
    if MID_LEVEL.search(title) and min_yoe <= DEFAULT_MAX_YOE and max_yoe >= DEFAULT_MIN_YOE:
        return "implied by title", ""
    return "not stated", ""

