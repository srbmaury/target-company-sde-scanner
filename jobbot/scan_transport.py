"""HTTP retry policy, maintenance detection, and markup text normalization."""

import html
import json
import re
import time
import urllib.error
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (target-company-sde-scanner)"}

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
            time.sleep(min(30, int(wait)) if wait and wait.isdigit() else 2 ** (attempt + 1))


def text_of(markup):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", html.unescape(markup or ""))))



