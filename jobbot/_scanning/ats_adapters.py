"""Adapters for Greenhouse, Lever, and Ashby public job boards."""

import re


def greenhouse(entry, *, http_json, text_of):
    d = http_json(f"https://boards-api.greenhouse.io/v1/boards/{entry['id']}/jobs?content=true")
    for j in d.get("jobs", []):
        yield {
            "title": j.get("title", ""),
            "location": (j.get("location") or {}).get("name", ""),
            "url": j.get("absolute_url", ""),
            "text": text_of(j.get("content")),
            "posted": (j.get("updated_at") or "")[:10],
        }


def lever(entry, host, *, http_json, text_of):
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


def ashby(entry, *, http_json):
    d = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{entry['id']}")
    for j in d.get("jobs", []):
        locs = [j.get("location") or ""] + [
            (s.get("location") or "") for s in j.get("secondaryLocations", []) or []
        ]
        department = (j.get("department") or "").strip()
        if department:
            locs = [re.sub(r"\s+[–—-]\s+" + re.escape(department) + r"$", "", loc, flags=re.I) for loc in locs]
        yield {
            "title": j.get("title", ""),
            "location": "; ".join(x for x in locs if x),
            "url": j.get("jobUrl", ""),
            "text": j.get("descriptionPlain", ""),
            "posted": (j.get("publishedAt") or "")[:10],
        }
