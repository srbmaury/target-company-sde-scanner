"""Sweep public applicant-tracking-system APIs for 1-3 YOE engineering roles.

Reads references/ats-registry.json, queries each company's public job-board API
(Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Microsoft), keeps engineering
roles in the requested locations, pulls the stated experience requirement from the
posting body, and prints a Markdown table (or JSON).

This is a discovery pass. Every row is a candidate that must still be opened and
verified before it is reported as an opening (see SKILL.md).

Standard library only. Run it as `python3 scripts/ats_scan.py ...`, or call
`run_scan()` from Python (jobbot does).
"""

import argparse
import concurrent.futures as cf
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "..", "references", "ats-registry.json")
DEFAULT_QUERIES = "software engineer,backend engineer,full stack engineer,developer"
UA = {"User-Agent": "Mozilla/5.0 (target-company-sde-scanner)"}

DEFAULT_LOCATIONS = r"india|bengaluru|bangalore|hyderabad|noida|gurugram|gurgaon|delhi|pune|chennai|mumbai"
ENGINEERING = re.compile(
    r"engineer|developer|\bsde\b|software|programmer|member of technical staff|\bmts\b|computer scientist",
    re.I,
)
NOT_ENGINEERING = re.compile(
    r"sales|solutions? engineer|customer|support|account|recruit|partner|field|"
    r"technical program|program manager|product manager|designer|marketing|consultant|"
    r"\bqa\b|quality|\btest|sdet|verification|asic|silicon|analyst|advocate|writer|security engineer",
    re.I,
)
SENIOR = re.compile(
    r"senior|\bsr\.?\b|staff|principal|\blead\b|manager|director|head of|architect|"
    r"distinguished|fellow|"
    r"intern|apprentice|new grad|graduate|campus|trainee",
    re.I,
)
MID_LEVEL = re.compile(r"\bii\b|\b2\b|sde\s*-?\s*2|mid[- ]level|engineer\s*2|\bl[34]\b|\bmts\b", re.I)
YEARS = re.compile(
    r"(?:(?:minimum|min\.?|at least|over)\s+(?:of\s+)?)?"
    r"(\d{1,2})(?:\s*(?:\+|plus)|\s*(?:-|–|—|to)\s*(\d{1,2}))?\s*\+?\s*(?:years?|yrs?)",
    re.I,
)


def http_json(url, data=None, timeout=25):
    body = json.dumps(data).encode() if data is not None else None
    headers = dict(UA)
    if body is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(4):
        req = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            # Back off on rate limits and transient server errors; fail fast otherwise.
            if e.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
            wait = e.headers.get("Retry-After")
            time.sleep(float(wait) if wait and wait.isdigit() else 2 ** (attempt + 1))


def text_of(markup):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", html.unescape(markup or ""))))


def stated_years(text):
    """Return (min_years, snippet) for the first experience requirement found."""
    for m in YEARS.finditer(text or ""):
        low = int(m.group(1))
        if low > 20:
            continue
        start = max(0, m.start() - 60)
        context = text[start : m.end() + 50]
        if re.search(r"experience|exp\b|expertise|professional|industry|hands-on|relevant|engineering|building|working|develop", context, re.I):
            return low, context.strip()
    return None, ""


# --- Adapters: each yields dicts with title, location, url, text, posted ---------

def greenhouse(entry):
    d = http_json(f"https://boards-api.greenhouse.io/v1/boards/{entry['id']}/jobs?content=true")
    for j in d.get("jobs", []):
        yield {
            "title": j.get("title", ""),
            "location": (j.get("location") or {}).get("name", ""),
            "url": j.get("absolute_url", ""),
            "text": text_of(j.get("content")),
            "posted": (j.get("updated_at") or "")[:10],
        }


def lever(entry, host="api.lever.co"):
    d = http_json(f"https://{host}/v0/postings/{entry['id']}?mode=json")
    for j in d:
        lists = " ".join(text_of(x.get("content")) for x in j.get("lists", []))
        yield {
            "title": j.get("text", ""),
            "location": (j.get("categories") or {}).get("location", "")
            or ", ".join((j.get("categories") or {}).get("allLocations", [])),
            "url": j.get("hostedUrl", ""),
            "text": (j.get("descriptionPlain") or "") + " " + lists,
            "posted": "",
        }


def ashby(entry):
    d = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{entry['id']}")
    for j in d.get("jobs", []):
        locs = [j.get("location") or ""] + [
            (s.get("location") or "") for s in j.get("secondaryLocations", []) or []
        ]
        yield {
            "title": j.get("title", ""),
            "location": "; ".join(x for x in locs if x),
            "url": j.get("jobUrl", ""),
            "text": j.get("descriptionPlain", ""),
            "posted": (j.get("publishedAt") or "")[:10],
        }


def workday(entry, queries, location_re):
    host, tenant, site = entry["host"], entry["tenant"], entry["site"]
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    seen = {}
    for q in queries:
        for offset in range(0, 100, 20):
            d = http_json(f"{base}/jobs", {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": q})
            posts = d.get("jobPostings", [])
            for p in posts:
                if p.get("externalPath"):
                    seen.setdefault(p["externalPath"], p)
            if len(posts) < 20:
                break
    for path, p in seen.items():
        loc = p.get("locationsText", "")
        title = p.get("title", "")
        # Detail calls are slow: only fetch the ones that can still pass the filters.
        if not ENGINEERING.search(title) or NOT_ENGINEERING.search(title) or SENIOR.search(title):
            continue
        if not location_re.search(loc + " " + path):
            continue
        try:
            info = http_json(f"{base}{path}")["jobPostingInfo"]
        except Exception:
            continue
        yield {
            "title": info.get("title", title),
            "location": info.get("location", loc),
            "url": f"https://{host}/{site}{path}",
            "text": text_of(info.get("jobDescription")),
            "posted": info.get("startDate", ""),
        }


def smartrecruiters(entry, queries, location_re):
    seen = {}
    for q in queries:
        url = (
            f"https://api.smartrecruiters.com/v1/companies/{entry['id']}/postings?"
            + urllib.parse.urlencode({"q": q, "country": "in", "limit": 100})
        )
        for p in http_json(url).get("content", []):
            seen[p["id"]] = p
    for pid, p in seen.items():
        if SENIOR.search(p.get("name", "")) or not ENGINEERING.search(p.get("name", "")):
            continue
        try:
            d = http_json(f"https://api.smartrecruiters.com/v1/companies/{entry['id']}/postings/{pid}")
        except Exception:
            continue
        sections = (d.get("jobAd") or {}).get("sections", {})
        yield {
            "title": d.get("name", ""),
            "location": ", ".join(filter(None, [(d.get("location") or {}).get("city"), "India"])),
            "url": d.get("postingUrl") or d.get("applyUrl") or "",
            "text": " ".join(text_of(s.get("text")) for s in sections.values()),
            "posted": (p.get("releasedDate") or "")[:10],
        }


def microsoft(entry, queries, location_re):
    seen = {}
    for q in queries:
        time.sleep(1)
        url = "https://apply.careers.microsoft.com/api/pcsx/search?" + urllib.parse.urlencode(
            {"domain": "microsoft.com", "query": q, "location": "India", "start": 0, "num": 50, "sort_by": "timestamp"}
        )
        for p in (http_json(url).get("data") or {}).get("positions", []):
            seen[p["id"]] = p
    for pid, p in seen.items():
        if SENIOR.search(p.get("name", "")) or not ENGINEERING.search(p.get("name", "")):
            continue
        time.sleep(0.5)  # this endpoint rate-limits aggressively
        try:
            d = http_json(
                f"https://apply.careers.microsoft.com/api/pcsx/position_details?position_id={pid}&domain=microsoft.com"
            )["data"]
        except Exception:
            continue
        yield {
            "title": d.get("name", ""),
            "location": "; ".join(p.get("locations") or []),
            "url": f"https://apply.careers.microsoft.com/careers/job/{pid}",
            "text": text_of(d.get("jobDescription")),
            "posted": "",
        }


def fetch(name, entry, queries, location_re):
    ats = entry["ats"]
    if ats == "greenhouse":
        return list(greenhouse(entry))
    if ats == "lever":
        return list(lever(entry))
    if ats == "lever-eu":
        return list(lever(entry, "api.eu.lever.co"))
    if ats == "ashby":
        return list(ashby(entry))
    if ats == "workday":
        return list(workday(entry, queries, location_re))
    if ats == "smartrecruiters":
        return list(smartrecruiters(entry, queries, location_re))
    if ats == "microsoft":
        return list(microsoft(entry, queries, location_re))
    raise ValueError(f"unknown ats {ats}")


def classify(job, location_re, max_yoe):
    title, loc = job["title"], job["location"]
    if not ENGINEERING.search(title) or NOT_ENGINEERING.search(title) or SENIOR.search(title):
        return None
    if not location_re.search(loc or ""):
        return None
    in_title = re.search(r"(\d{1,2})\s*\+?\s*(?:-|–|to)?\s*\d*\s*\+?\s*(?:years?|yrs?)", title, re.I)
    if in_title and int(in_title.group(1)) > max_yoe:
        return None
    low, snippet = stated_years(job["text"])
    if low is not None:
        if low > max_yoe:
            return None
        return f"{low}+ yrs stated", snippet
    if MID_LEVEL.search(title):
        return "implied by title", ""
    return "not stated", ""


def load_history(path):
    if not path or not os.path.exists(path):
        return set()
    return set(re.findall(r"https?://[^\s|)>\]]+", open(path, encoding="utf-8").read()))


def load_registry():
    with open(REGISTRY, encoding="utf-8") as fh:
        return json.load(fh)["companies"]


def resolve_names(registry, companies=None):
    """Map user-supplied names to registry keys. Returns (names, missing)."""
    if not companies:
        return list(registry), []
    lookup = {k.lower(): k for k in registry}
    names, missing = [], []
    for raw in companies:
        if not raw.strip():
            continue
        key = lookup.get(raw.strip().lower())
        (names.append(key) if key else missing.append(raw.strip()))
    return names, missing


def run_scan(companies=None, exclude=(), locations=DEFAULT_LOCATIONS, max_yoe=3, include_unstated=False,
             queries=DEFAULT_QUERIES, skip_urls=(), workers=16):
    """Scan the registry. Returns (results, coverage, missing).

    Each result has company, ats, board, title, location, url, posted, experience,
    evidence and description (plain text, truncated).
    """
    registry = load_registry()
    names, missing = resolve_names(registry, companies)
    excluded = {x.strip().lower() for x in exclude if x.strip()}
    names = [n for n in names if n.lower() not in excluded]
    location_re = re.compile(locations, re.I)
    if isinstance(queries, str):
        queries = [q.strip() for q in queries.split(",") if q.strip()]
    skip_urls = set(skip_urls)

    results, coverage = [], {}
    with cf.ThreadPoolExecutor(workers) as ex:
        futures = {ex.submit(fetch, n, registry[n], queries, location_re): n for n in names}
        for fut in cf.as_completed(futures):
            name = futures[fut]
            try:
                jobs = fut.result()
            except Exception as e:  # network errors, retired boards, auth walls
                coverage[name] = f"error: {type(e).__name__}"
                continue
            kept = 0
            entry = registry[name]
            for job in jobs:
                verdict = classify(job, location_re, max_yoe)
                if not verdict or job["url"] in skip_urls:
                    continue
                if verdict[0] == "not stated" and not include_unstated:
                    continue
                kept += 1
                results.append({
                    "company": name, "ats": entry["ats"], "board": entry.get("id") or entry.get("host", ""),
                    **{k: job[k] for k in ("title", "location", "url", "posted")},
                    "experience": verdict[0], "evidence": verdict[1][:160],
                    "description": (job.get("text") or "")[:8000],
                })
            coverage[name] = f"{len(jobs)} postings, {kept} kept"
    results.sort(key=lambda r: (r["company"].lower(), r["title"]))
    return results, coverage, missing


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    scope = ap.add_mutually_exclusive_group(required=True)
    scope.add_argument("--companies", help="Comma-separated company names as written in the registry")
    scope.add_argument("--all", action="store_true", help="Scan every company in the registry")
    ap.add_argument("--exclude", default="", help="Comma-separated companies to skip (e.g. current employer)")
    ap.add_argument("--locations", default=DEFAULT_LOCATIONS, help="Regex matched against job location")
    ap.add_argument("--max-yoe", type=int, default=3, help="Drop roles whose stated minimum exceeds this")
    ap.add_argument("--include-unstated", action="store_true", help="Keep roles with no stated range and no level in the title")
    ap.add_argument("--queries", default=DEFAULT_QUERIES,
                    help="Search terms for search-based ATSs (Workday, SmartRecruiters, Microsoft)")
    ap.add_argument("--history", help="Markdown log of already-shown roles; their URLs are skipped")
    ap.add_argument("--json", action="store_true", help="Print JSON instead of a Markdown table")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args(argv)

    results, coverage, missing = run_scan(
        companies=None if args.all else args.companies.split(","),
        exclude=args.exclude.split(","), locations=args.locations, max_yoe=args.max_yoe,
        include_unstated=args.include_unstated, queries=args.queries,
        skip_urls=load_history(args.history), workers=args.workers,
    )
    if missing:
        print(f"Not in registry (use the career-site/search path instead): {', '.join(missing)}", file=sys.stderr)
    if args.json:
        for r in results:
            r.pop("description", None)
        print(json.dumps({"results": results, "coverage": coverage}, indent=2, ensure_ascii=False))
        return
    print("| Company | Role | Location | Experience | Link |")
    print("|---|---|---|---|---|")
    for r in results:
        print(f"| {r['company']} | {r['title']} | {r['location'][:60]} | {r['experience']} | {r['url']} |")
    print("\nCoverage:")
    for name in sorted(coverage, key=str.lower):
        print(f"- {name}: {coverage[name]}")
    print("\nCandidates only: open each link and confirm an active Apply control before reporting it.")


if __name__ == "__main__":
    main()
