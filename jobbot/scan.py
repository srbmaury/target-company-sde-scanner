"""Sweep public applicant-tracking-system APIs for 1-3 YOE engineering roles.

Reads references/ats-registry.json, queries each company's public job-board API
(Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, Eightfold, Oracle
Recruiting Cloud) and the Amazon, Google, Apple and Microsoft careers sites, keeps engineering
roles in the requested locations, pulls the stated experience requirement from the
posting body, and prints a Markdown table (or JSON).

This is a discovery pass. Every row is a candidate that must still be opened and
verified before it is reported as an opening (see SKILL.md).

Standard library only. Run it as `python3 scripts/ats_scan.py ...`, or call
`run_scan()` from Python (jobbot does).
"""

import argparse
import concurrent.futures as cf
import datetime as dt
import html
import json
import os
import re
import sys
import threading
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
    r"\bqa\b|quality|\btest|sdet|verification|asic|silicon|analyst|advocate|writer|security engineer|"
    r"network engineer|\bnoc\b|it service|\bit engineer|technical publication",
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


class SiteMaintenance(Exception):
    """The job board redirected to a maintenance page: the board is down, not empty."""


def http_json(url, data=None, timeout=25):
    body = json.dumps(data).encode() if data is not None else None
    headers = dict(UA)
    if body is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(4):
        req = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if "maintenance" in resp.geturl().lower():   # e.g. Workday redirects every call while it is down
                    raise SiteMaintenance(resp.geturl())
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


def worth_details(title, location, location_re):
    """Cheap pre-filter before fetching a posting's details (detail calls are slow)."""
    return bool(ENGINEERING.search(title or "") and not NOT_ENGINEERING.search(title or "")
                and not SENIOR.search(title or "") and location_re.search(location or ""))


def http_text(url, timeout=25):
    req = urllib.request.Request(url, headers={**UA, "Accept": "text/html,application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def eightfold(entry, queries, location_re):
    """Eightfold "PCSX" career sites (Microsoft, NVIDIA, and others): search, then position details."""
    host, domain = entry["host"], entry["domain"]
    seen = {}
    for q in queries:
        time.sleep(1)
        url = f"https://{host}/api/pcsx/search?" + urllib.parse.urlencode(
            {"domain": domain, "query": q, "location": "India", "start": 0, "num": 50, "sort_by": "timestamp"})
        for p in (http_json(url).get("data") or {}).get("positions", []):
            seen[p["id"]] = p
    for pid, p in seen.items():
        loc = "; ".join(p.get("locations") or [])
        if not worth_details(p.get("name"), loc + "; India", location_re):
            continue
        time.sleep(0.5)  # these endpoints rate-limit aggressively
        try:
            d = http_json(f"https://{host}/api/pcsx/position_details?position_id={pid}&domain={domain}")["data"]
        except Exception:
            continue
        yield {
            "title": d.get("name", ""),
            "location": loc,
            "url": d.get("publicUrl") or f"https://{host}/careers/job/{pid}",
            "text": text_of(d.get("jobDescription")),
            "posted": dt.date.fromtimestamp(p["postedTs"]).isoformat() if p.get("postedTs") else "",
        }


def microsoft(entry, queries, location_re):
    return eightfold({"host": "apply.careers.microsoft.com", "domain": "microsoft.com"}, queries, location_re)


def amazon(entry, queries, location_re):
    seen = {}
    for q in queries:
        for offset in range(0, 500, 100):
            d = http_json("https://www.amazon.jobs/en/search.json?" + urllib.parse.urlencode(
                {"base_query": q, "loc_query": "India", "country": "IND", "result_limit": 100, "offset": offset}))
            for j in d.get("jobs", []):
                seen.setdefault(j["id_icims"], j)
            if offset + 100 >= d.get("hits", 0):
                break
    for j in seen.values():
        try:
            posted = dt.datetime.strptime(j.get("posted_date", ""), "%B %d, %Y").date().isoformat()
        except ValueError:
            posted = ""
        yield {
            "title": j.get("title", ""),
            "location": j.get("normalized_location") or j.get("location", ""),
            "url": "https://www.amazon.jobs" + j.get("job_path", ""),
            "text": text_of(" ".join(j.get(k) or "" for k in
                                     ("basic_qualifications", "preferred_qualifications", "description"))),
            "posted": posted,
        }


def google(entry, queries, location_re):
    """Google's careers site embeds each results page as JSON, descriptions included."""
    seen = {}
    for q in queries:
        for page in range(1, 11):
            h = http_text("https://www.google.com/about/careers/applications/jobs/results?"
                          + urllib.parse.urlencode({"q": q, "location": "India", "page": page}))
            m = re.search(r"AF_initDataCallback\(\{key: 'ds:1'.*?data:(.*?), sideChannel", h, re.S)
            jobs = (json.loads(m.group(1))[0] or []) if m else []
            for j in jobs:
                seen.setdefault(j[0], j)
            if len(jobs) < 20:
                break

    def part(j, i):
        return j[i][1] if len(j) > i and isinstance(j[i], list) and len(j[i]) > 1 and isinstance(j[i][1], str) else ""

    for jid, j in seen.items():
        slug = re.sub(r"[^a-z0-9]+", "-", j[1].lower()).strip("-")
        created = j[12][0] if len(j) > 12 and isinstance(j[12], list) and j[12] else None
        yield {
            "title": j[1],
            "location": "; ".join(loc[0] for loc in (j[9] or []) if loc),
            "url": f"https://www.google.com/about/careers/applications/jobs/results/{jid}-{slug}",
            "text": text_of(" ".join([part(j, 19), part(j, 4), part(j, 3), part(j, 10)])),
            "posted": dt.date.fromtimestamp(created).isoformat() if created else "",
        }


def _apple_data(url):
    m = re.search(r'__staticRouterHydrationData = JSON\.parse\("(.*?)"\);', http_text(url), re.S)
    return json.loads(json.loads('"' + m.group(1) + '"'))["loaderData"] if m else {}


def apple(entry, queries, location_re):
    seen = {}
    for q in queries:
        for page in range(1, 11):
            s = _apple_data("https://jobs.apple.com/en-in/search?" + urllib.parse.urlencode(
                {"search": q, "location": "india-INDC", "page": page})).get("search") or {}
            results = s.get("searchResults") or []
            for r in results:
                seen.setdefault(r["positionId"], r)
            if not results or page * len(results) >= (s.get("totalRecords") or 0):
                break
    wanted = []
    for pid, r in seen.items():
        loc = "; ".join(x.get("name", "") for x in r.get("locations") or []) + ", India"
        if worth_details(r.get("postingTitle"), loc, location_re):
            wanted.append((r, loc, f"https://jobs.apple.com/en-in/details/{pid}/{r.get('transformedPostingTitle', '')}"))

    def details(item):
        try:
            return (_apple_data(item[2]).get("jobDetails") or {}).get("jobsData") or {}
        except Exception:
            return None

    with cf.ThreadPoolExecutor(6) as ex:   # detail pages are slow; fetch a few at a time
        for (r, loc, url), d in zip(wanted, ex.map(details, wanted)):
            if d is None:
                continue
            yield {
                "title": r.get("postingTitle", ""),
                "location": loc,
                "url": url,
                "text": " ".join(d.get(k) or "" for k in ("minimumQualifications", "preferredQualifications", "description")),
                "posted": (r.get("postDateInGMT") or "")[:10],
            }


def oracle(entry, queries, location_re):
    """Oracle Recruiting Cloud career sites (JPMorgan Chase, Uber, Oracle, and others)."""
    host, site = entry["host"], entry["site"]
    api = f"https://{host}/hcmRestApi/resources/latest"
    seen = {}
    for q in queries:
        for offset in range(0, 500, 50):
            url = (f"{api}/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations"
                   f"&finder=findReqs;siteNumber={site},keyword={urllib.parse.quote(q)},location=India,"
                   f"limit=50,offset={offset}")
            reqs = ((http_json(url).get("items") or [{}])[0]).get("requisitionList") or []
            for r in reqs:
                seen.setdefault(r["Id"], r)
            if len(reqs) < 50:
                break
    for rid, r in seen.items():
        loc = r.get("PrimaryLocation", "")
        if not worth_details(r.get("Title"), loc, location_re):
            continue
        try:
            d = http_json(f"{api}/recruitingCEJobRequisitionDetails?expand=all&onlyData=true"
                          f"&finder=ById;Id=%22{rid}%22,siteNumber={site}")["items"][0]
        except Exception:
            continue
        yield {
            "title": r.get("Title", ""),
            "location": loc,
            "url": f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{rid}",
            "text": text_of(" ".join(d.get(k) or "" for k in
                                     ("ExternalQualificationsStr", "ExternalResponsibilitiesStr", "ExternalDescriptionStr"))),
            "posted": (r.get("PostedDate") or "")[:10],
        }


def workable(entry, queries, location_re):
    account = entry["id"]
    jobs, token = [], None
    for _ in range(20):
        body = {"query": "", "location": [], "department": [], "worktype": [], "remote": []}
        if token:
            body["token"] = token
        d = http_json(f"https://apply.workable.com/api/v3/accounts/{account}/jobs", body)
        jobs += d.get("results", [])
        token = d.get("nextPage")
        if not token:
            break
    for j in jobs:
        loc = j.get("location") or {}
        where = ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
        if j.get("remote"):
            where += " (remote)"
        if not worth_details(j.get("title"), where, location_re):
            continue
        try:
            d = http_json(f"https://apply.workable.com/api/v2/accounts/{account}/jobs/{j['shortcode']}")
        except Exception:
            continue
        yield {
            "title": j.get("title", ""),
            "location": where,
            "url": f"https://apply.workable.com/{account}/j/{j['shortcode']}/",
            "text": text_of(" ".join(d.get(k) or "" for k in ("requirements", "description"))),
            "posted": (j.get("published") or "")[:10],
        }


def _pick(item, spec):
    """Read a value from a JSON item by a "a.b|c" spec: dotted paths, first non-empty alternative wins."""
    for path in (spec or "").split("|"):
        value = item
        for key in path.split("."):
            value = value.get(key) if isinstance(value, dict) else None
        if value:
            if isinstance(value, list):  # e.g. offices: [{"name": ..., "location": "Bengaluru, India"}]
                return "; ".join(str(v.get("location") or v.get("name") or "") if isinstance(v, dict) else str(v)
                                 for v in value)
            return str(value)
    return ""


def json_feed(entry, queries, location_re):
    """A careers site's own JSON job list, described in the registry entry:
    {"url", "list" (path to the array, "" for the root), "title", "location", "link", "text" (list of specs),
    "posted", "only" ({field: value} filter), "job_url" (template like "https://x.com/jobs/{id}" when
    records carry no link)}."""
    d = http_json(entry["url"])
    items = d
    for key in filter(None, entry.get("list", "").split(".")):
        items = items.get(key, []) if isinstance(items, dict) else []
    for item in items:
        if any(_pick(item, k) != v for k, v in (entry.get("only") or {}).items()):
            continue
        yield {
            "title": _pick(item, entry.get("title", "title")),
            "location": _pick(item, entry.get("location", "location")),
            "url": _pick(item, entry.get("link", "url")) or entry.get("job_url", "").format_map(
                {k: v for k, v in item.items() if isinstance(v, (str, int))}),
            "text": text_of(" ".join(_pick(item, t) for t in entry.get("text", []))),
            "posted": _pick(item, entry.get("posted", ""))[:10],
        }


def keka(entry, queries, location_re):
    """Keka Hire career portals ({id}.keka.com/careers), common with Indian startups."""
    base = f"https://{entry['id']}.keka.com/careers"
    for j in http_json(f"{base}/api/jobs/default/active"):
        locs = "; ".join(", ".join(filter(None, [x.get("city"), x.get("state"), x.get("countryName") or x.get("name")]))
                         for x in j.get("jobLocations") or [])
        yield {
            "title": j.get("title", ""),
            "location": locs,
            "url": f"{base}/jobdetails/{j['id']}",
            "text": (f"Experience: {j['experience']} of experience. " if j.get("experience") else "")
                    + text_of(j.get("description")),
            "posted": (j.get("publishedOn") or "")[:10],
        }


def freshteam(entry, queries, location_re):
    """Freshteam job boards ({id}.freshteam.com/jobs): titles from the list page, text from each posting."""
    base = f"https://{entry['id']}.freshteam.com"
    page = http_text(f"{base}/jobs")
    seen = {}
    for path, where, title in re.findall(
            r'href="(/jobs/[A-Za-z0-9_-]+/[^"]+)"[^>]*?data-portal-location="([^"]*)".*?job-title">([^<]+)<', page, re.S):
        seen.setdefault(path, (html.unescape(title).strip(), html.unescape(where)))
    for path, (title, where) in seen.items():
        if not worth_details(title, where, location_re):
            continue
        try:
            body = http_text(base + path)
        except Exception:
            continue
        yield {"title": title, "location": where, "url": base + path, "text": text_of(body.split("<form")[0])[:12000],
               "posted": ""}


def jibe(entry, queries, location_re):
    """Jibe career sites (AMD and others): /api/jobs search with full descriptions."""
    host = entry["host"]
    seen = {}
    for q in queries:
        for page in range(1, 11):
            d = http_json(f"https://{host}/api/jobs?" + urllib.parse.urlencode(
                {"keywords": q, "location": "India", "page": page}))
            jobs = [x.get("data") or {} for x in d.get("jobs", [])]
            for j in jobs:
                seen.setdefault(j.get("slug") or j.get("req_id"), j)
            if not jobs or page * len(jobs) >= d.get("totalCount", 0):
                break
    for slug, j in seen.items():
        yield {
            "title": j.get("title", ""),
            "location": j.get("full_location") or j.get("location_name", ""),
            "url": entry.get("job_url", "https://{host}/careers-home/jobs/{slug}").format(host=host, slug=slug),
            "text": text_of(" ".join(j.get(k) or "" for k in ("qualifications", "responsibilities", "description"))),
            "posted": (j.get("posted_date") or "")[:10],
        }


SEARCH_ADAPTERS = {"microsoft": microsoft, "eightfold": eightfold, "amazon": amazon, "google": google,
                   "apple": apple, "oracle": oracle, "workable": workable, "json-feed": json_feed,
                   "keka": keka, "freshteam": freshteam, "jibe": jibe}


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
    if ats in SEARCH_ADAPTERS:
        return list(SEARCH_ADAPTERS[ats](entry, queries, location_re))
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
    if in_title:  # "(1 to 4 Years)" in the title is as good as a stated range
        return f"{in_title.group(1)}+ yrs in title", title
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
             queries=DEFAULT_QUERIES, skip_urls=(), workers=16, careers_pages=True):
    """Scan the registry. Returns (results, coverage, missing).

    Each result has company, ats, board, title, location, url, posted, experience,
    evidence and description (plain text, truncated). Companies listed only by their careers
    page ("careers-page") are read in headless Chrome alongside the API sweep, unless
    careers_pages is False.
    """
    registry = load_registry()
    names, missing = resolve_names(registry, companies)
    excluded = {x.strip().lower() for x in exclude if x.strip()}
    names = [n for n in names if n.lower() not in excluded]
    location_re = re.compile(locations, re.I)
    if isinstance(queries, str):
        queries = [q.strip() for q in queries.split(",") if q.strip()]
    skip_urls = set(skip_urls)
    pages = {n: registry[n] for n in names if registry[n]["ats"] == "careers-page"}
    names = [n for n in names if n not in pages]

    results, coverage, lock = [], {}, threading.Lock()

    def absorb(name, jobs):
        with lock:
            if isinstance(jobs, Exception):  # network errors, retired boards, auth walls
                coverage[name] = f"error: {type(jobs).__name__}"
                return
            kept, entry, urls = 0, registry[name], {r["url"] for r in results}
            for job in jobs:
                verdict = classify(job, location_re, max_yoe)
                if not verdict or job["url"] in skip_urls or job["url"] in urls:
                    continue
                if verdict[0] == "not stated" and not include_unstated:
                    continue
                kept += 1
                urls.add(job["url"])
                results.append({
                    "company": name, "ats": entry["ats"],
                    "board": entry.get("id") or entry.get("host") or entry.get("url", ""),
                    **{k: job[k] for k in ("title", "location", "url", "posted")},
                    "experience": verdict[0], "evidence": verdict[1][:160],
                    "description": (job.get("text") or "")[:8000],
                })
            coverage[name] = f"{len(jobs)} postings, {kept} kept"

    browser = None
    if pages and careers_pages:
        from .careers_page import scan_careers_pages
        rules = (ENGINEERING, NOT_ENGINEERING, SENIOR, location_re)
        browser = threading.Thread(target=scan_careers_pages, args=(pages, rules, absorb), daemon=True)
        browser.start()
    elif pages:
        coverage.update({n: "skipped: careers page (--no-careers-pages)" for n in pages})
    with cf.ThreadPoolExecutor(workers) as ex:
        futures = {ex.submit(fetch, n, registry[n], queries, location_re): n for n in names}
        for fut in cf.as_completed(futures):
            try:
                jobs = fut.result()
            except Exception as e:
                jobs = e
            absorb(futures[fut], jobs)
    if browser:
        browser.join()
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
                    help="Search terms for search-based sources (Workday, SmartRecruiters, Oracle, Eightfold, "
                         "Amazon, Google, Apple, Microsoft)")
    ap.add_argument("--history", help="Markdown log of already-shown roles; their URLs are skipped")
    ap.add_argument("--json", action="store_true", help="Print JSON instead of a Markdown table")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--no-careers-pages", action="store_true",
                    help="Skip companies read from their own careers page (needs Playwright and Chrome)")
    args = ap.parse_args(argv)

    results, coverage, missing = run_scan(
        companies=None if args.all else args.companies.split(","),
        exclude=args.exclude.split(","), locations=args.locations, max_yoe=args.max_yoe,
        include_unstated=args.include_unstated, queries=args.queries,
        skip_urls=load_history(args.history), workers=args.workers, careers_pages=not args.no_careers_pages,
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
