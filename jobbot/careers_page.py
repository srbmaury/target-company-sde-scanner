"""Read jobs straight from a company's own careers page, for sites without a public job-board API.

Opens the page in headless Chrome (Playwright), collects links whose text looks like an
engineering role, then reads each posting's text so the scanner can find the location and the
stated experience. Less precise than the API adapters in scan.py: titles come from link text and
locations from the posting text. Needs Playwright; without it these companies are reported as
skipped.
"""

import asyncio
import importlib.util
import json
import re
import urllib.parse

LINK_JS = """() => [...document.querySelectorAll('a[href]')].map(a => {
  let card = a, ctx = '';
  for (let i = 0; i < 4 && card; i++, card = card.parentElement) {
    ctx = (card.innerText || '').trim();
    if (ctx.length > 40) break;
  }
  return {text: (a.innerText || a.getAttribute('aria-label') || '').trim(), href: a.href, ctx: ctx.slice(0, 400)};
})"""

JOBISH = re.compile(r"job|career|position|opening|role|requisition|vacanc|apply|/\d{4,}", re.I)
SKIP = re.compile(r"linkedin\.com|facebook\.com|twitter\.com|x\.com/|instagram\.com|youtube\.com|glassdoor|mailto:|"
                  r"/blog|/news|/press|/events?/|privacy|cookie|terms", re.I)
ROLE = re.compile(r"\bengineers?\b|developer|\bsde\b|\bsdet\b|programmer|architect|scientist|swe\b", re.I)
MAX_LINKS = 40          # postings read per company
PAGE_TIMEOUT = 30000


TITLE_KEYS = ("title", "jobTitle", "job_title", "postingTitle", "name", "text", "position")
LOC_KEYS = ("locationsText", "location", "locations", "location_name", "primaryLocation", "city", "cityState",
            "office", "offices", "workLocation")
URL_KEYS = ("url", "absolute_url", "jobUrl", "hostedUrl", "applyUrl", "canonicalPositionUrl", "externalUrl", "link",
            "href", "job_url")


def _flat(value):
    """Location values come as strings, lists, or objects; reduce them to text."""
    if isinstance(value, dict):
        return ", ".join(_flat(v) for k, v in value.items() if isinstance(v, (str, list, dict)) and
                         re.search(r"name|city|country|display|state|text", k, re.I))
    if isinstance(value, list):
        return "; ".join(filter(None, (_flat(v) for v in value)))
    return str(value) if isinstance(value, (str, int)) else ""


def jobs_in_json(data, found=None):
    """Find job-like records in a JSON payload: lists of 3+ objects, most of which have a title."""
    found = [] if found is None else found
    if isinstance(data, dict):
        for v in data.values():
            jobs_in_json(v, found)
    elif isinstance(data, list):
        dicts = [x for x in data if isinstance(x, dict)]
        titled = [x for x in dicts if any(isinstance(x.get(k), str) and ROLE.search(x[k] or "") or
                                          isinstance(x.get(k), str) and len(x.get(k)) < 150 and k != "name"
                                          for k in TITLE_KEYS if k in x)]
        if len(dicts) >= 3 and len(titled) >= len(dicts) / 2:
            for x in dicts:
                title = next((x[k] for k in TITLE_KEYS if isinstance(x.get(k), str) and x[k].strip()), "")
                found.append({"title": title.strip(),
                              "location": next((_flat(x[k]) for k in LOC_KEYS if x.get(k)), ""),
                              "url": next((x[k] for k in URL_KEYS if isinstance(x.get(k), str) and x[k].startswith("http")), ""),
                              "id": str(next((x[k] for k in ("id", "jobId", "job_id", "reqId", "requisitionId")
                                              if isinstance(x.get(k), (str, int))), ""))})
        else:
            for v in data:
                jobs_in_json(v, found)
    return found


async def _settle(page):
    try:  # single-page apps fetch their job list after the first paint
        await page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass
    await page.wait_for_timeout(1500)
    for _ in range(3):  # lazy lists render on scroll
        await page.mouse.wheel(0, 4000)
        await page.wait_for_timeout(700)


async def _company(ctx, name, entry, rules, sem):
    engineering, not_engineering, senior, location_re = rules
    url = entry["url"] if entry["url"].startswith("http") else "https://" + entry["url"]
    blobs = []

    async def on_response(resp):
        if resp.request.resource_type not in ("xhr", "fetch"):
            return
        try:  # some sites label JSON as text/html, so look at the body
            body = re.sub(r"^for \(;;\);", "", (await resp.text()).lstrip())
            if body[:1] in "{[" and len(body) < 5_000_000:
                blobs.append(json.loads(body))
        except Exception:
            pass

    async with sem:
        page = await ctx.new_page()
        page.on("response", on_response)
        try:
            await page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
            await _settle(page)
            links = await page.evaluate(LINK_JS)
            # Many careers home pages link to a search page; follow the first such link once.
            if not any(engineering.search(x["text"]) for x in links):
                more = page.locator("a:text-matches('(open (roles|positions)|view (all )?(jobs|openings|roles)|"
                                    "search (all )?jobs|see (all )?(jobs|openings|roles)|job openings|current openings|"
                                    "explore (jobs|roles|opportunities)|find (jobs|your role)|browse jobs)', 'i')").first
                if await more.count():
                    await more.click(timeout=8000)
                    await page.wait_for_load_state("domcontentloaded")
                    await _settle(page)
                    links = await page.evaluate(LINK_JS)
        finally:
            await page.close()

    host = urllib.parse.urlparse(url).netloc.split(".")[-2:]
    picked, seen = [], set()
    # 1) job lists the page loaded as JSON; link each record to its posting via its URL or id
    for blob in blobs:
        for j in jobs_in_json(blob):
            href = j["url"] or next((x["href"] for x in links if j["id"] and len(j["id"]) >= 4 and j["id"] in x["href"]), "")
            if not href and j["id"] and entry.get("job_url"):   # e.g. "https://www.metacareers.com/jobs/{id}/"
                href = entry["job_url"].format(id=j["id"])
            title = j["title"][:140]
            if not href or href in seen or not ROLE.search(title):
                continue
            if not engineering.search(title) or not_engineering.search(title) or senior.search(title):
                continue
            seen.add(href)
            picked.append((title, href, j["location"]))
    # 2) job links on the page itself
    for x in links:
        # A link often wraps a whole job card ("Bengaluru\nSoftware Engineer\nFull-time"): use the line that
        # names the role. Category links ("Engineering") have no role noun and are skipped.
        lines = [ln.strip() for ln in x["text"].splitlines() if ln.strip()]
        title = next((ln for ln in lines if ROLE.search(ln)), "")[:140]
        href = x["href"].split("#")[0]
        if not title or href in seen or SKIP.search(href) or not JOBISH.search(href):
            continue
        if not engineering.search(title) or not_engineering.search(title) or senior.search(title):
            continue
        same_site = urllib.parse.urlparse(href).netloc.split(".")[-2:] == host
        if not same_site and not re.search(r"greenhouse|lever|ashby|workday|smartrecruiters|icims|eightfold|"
                                           r"oraclecloud|successfactors|taleo|darwinbox|keka|workable", href, re.I):
            continue
        seen.add(href)
        picked.append((title, href, x["ctx"]))
    jobs = []

    async def read(item):
        title, href, card = item
        async with sem:
            p = await ctx.new_page()
            try:
                await p.goto(href, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
                await p.wait_for_timeout(2000)
                text = re.sub(r"\s+", " ", await p.inner_text("body"))[:12000]
            except Exception:
                text = ""
            finally:
                await p.close()
        where = location_re.search(card) or location_re.search(text)
        jobs.append({"title": title, "location": where.group(0) if where else "", "url": href, "text": text,
                     "posted": ""})

    await asyncio.gather(*(read(i) for i in picked[:MAX_LINKS]))
    return jobs


async def _scan_all(entries, rules, workers, on_done):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/129 Safari/537.36", locale="en-US")
        sem = asyncio.Semaphore(workers)

        async def one(name, entry):
            try:
                jobs = await asyncio.wait_for(_company(ctx, name, entry, rules, sem), timeout=240)
            except Exception as e:  # timeouts, blocked sites, redesigned pages
                on_done(name, e)
            else:
                on_done(name, jobs)

        await asyncio.gather(*(one(n, e) for n, e in entries.items()))
        await browser.close()


def scan_careers_pages(entries, rules, on_done, workers=6):
    """Read every entry ({name: {"url": ...}}); calls on_done(name, jobs_or_exception) for each."""
    if not importlib.util.find_spec("playwright"):
        for name in entries:
            on_done(name, RuntimeError("Playwright is not installed"))
        return
    asyncio.run(_scan_all(entries, rules, workers, on_done))
