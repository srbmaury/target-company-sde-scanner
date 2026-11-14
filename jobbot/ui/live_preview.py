"""Viewport frames and user input for a paused browser, on its Playwright thread."""

import base64
import math
import re
import secrets


KEYS = {"Tab", "Shift+Tab", "Enter", "Escape", "Backspace", "Delete", "Home", "End",
        "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "PageUp", "PageDown", "Space"}


def validate(body):
    if not isinstance(body, dict):
        raise ValueError("Invalid browser command.")
    action = body.get("action")
    if action in ("open", "frame", "release"):
        return {"action": action}
    out = {"action": action}
    if action in ("click", "scroll"):
        for key in ("x", "y"):
            val = body.get(key)
            if type(val) not in (int, float) or not 0 <= val <= 1:
                raise ValueError("Invalid browser position.")
            out[key] = val
        if action == "scroll":
            delta = body.get("delta")
            if type(delta) not in (int, float) or not -1600 <= delta <= 1600:
                raise ValueError("Invalid scroll amount.")
            out["delta"] = delta
    elif action == "text":
        val = body.get("text")
        if not isinstance(val, str) or not 1 <= len(val) <= 4000:
            raise ValueError("Enter up to 4000 characters.")
        out["text"] = val
    elif action == "key":
        val = body.get("key")
        if not isinstance(val, str) or (val not in KEYS and not re.fullmatch(r"[ -~]", val)):
            raise ValueError("Unsupported browser key.")
        out["key"] = val
    else:
        raise ValueError("Unknown browser command.")
    return out


def capture(page, *, quality=55):
    """Capture the actual viewport and mask password and OTP input elements."""
    masks = [frame.locator('input[type="password"], input[autocomplete="one-time-code"]') for frame in page.frames]
    return page.screenshot(type="jpeg", quality=quality, timeout=3500, animations="allow",
                         …48498 tokens truncated…nt(key),)).fetchone()
    return conn.execute("SELECT * FROM applications WHERE url = ?", (key,)).fetchone()


# --- matching applications that came from email (no URL) to scanned roles ----------

_COMPANY_SUFFIX = re.compile(r"\b(ai|inc|llc|llp|ltd|limited|pvt|private|labs?|technologies|technology|tech|software|"
                             r"corp(oration)?|co|company|india|global|group|careers|security|research)\b")
_ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4"}
_TITLE_NOISE = {"the", "a", "an", "and", "of", "for", "in", "at", "india", "remote", "hybrid", "role", "position",
                "earlier", "application", "august", "september", "october"}


def norm_company(name):
    name = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    name = _COMPANY_SUFFIX.sub(" ", name)
    return re.sub(r"\s+", "", name)


def same_company(a, b):
    """Same employer? Whole words after cleanup, one name a word-prefix of the other: "Cisco" = "Cisco
    Systems", "Meta" = "Meta Platforms", but "Sales Hub" != "Salesforce" and "Meta" != "Metabase"."""
    def words(name):
        name = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
        return _COMPANY_SUFFIX.sub(" ", name).split()
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return False
    short, long_ = sorted((wa, wb), key=len)
    return long_[:len(short)] == short


def title_tokens(title):
    t = (title or "").lower()
    t = re.sub(r"\((?:[^)]*\d{4,}[^)]*|job number[^)]*)\)", " ", t)      # (200047960), (Job number: ...)
    t = re.sub(r"\b(r-?\d{4,}|jr\d+|\d{5,})\b", " ", t)                   # requisition ids
    t = re.sub(r"\bsde(?=\b|[-\s]?\d)", "software development engineer", t)   # "SDE 2", "SDE-2", never "insider"
    t = re.sub(r"\bswe(?=\b|[-\s]?\d)", "software engineer", t)
    words = re.findall(r"[a-z0-9+#]+", t)
    words = [_ROMAN.get(w, w) for w in words]
    return {w for w in words if w not in _TITLE_NOISE}


def titles_match(a, b):
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return False
    if {w for w in ta if w.isdigit()} != {w for w in tb if w.isdigit()}:
        return False  # "Software Engineer II" is not "Software Engineer"
    if ta == tb:
        return True
    small, big = sorted((ta, tb), key=len)
    if small <= big and len(big) - len(small) <= 1 and len(small) >= 2:
        return True
    return len(ta & tb) / len(ta | tb) >= 0.8


def applied_match(conn, url=None, company=None, title=None, _apps=None, first_seen=None, posted=None, *, company_apps=None):
    """How sure are we that this role was already applied to?

    Returns (level, application row): "exact" (same URL), "likely" (same company and
    matching title), "possible" (same company, the email did not name the role), or
    (None, None). Rejected/withdrawn applications still count: they were applied to.
    """
    if url:
        row = conn.execute("SELECT * FROM applications WHERE url = ?", (url,)).fetchone()
        if row:
            return "exact", row
    if not company:
        return None, None
    if company_apps is None:
        apps = _apps if _apps is not None else conn.execute("SELECT * FROM applications").fetchall()
        at_company = _applications_at_company(apps, company)
    else:
        at_company = company_apps(company)
    for a in at_company:
        if titles_match(a["title"], title):
            if a["url"] and url and a["url"] != url:
                continue  # we know the exact posting applied to, and this is a different one
            if _reposted(a, posted, first_seen):
                return "possible", a  # big employers reuse titles; this looks like a newer opening
            return "likely", a
    for a in at_company:
        if a["title"].startswith("(role not stated"):
            return "possible", a
    return None, None


def _applications_at_company(apps, company):
    key = norm_company(company)
    if not key:
        return []
    return [app for app in apps if norm_company(app["company"]) == key or same_company(app["company"], company)]


def job_matcher(conn):
    """Reuse company candidates within one scan of the tracker."""
    apps = conn.execute("SELECT * FROM applications").fetchall()

    @lru_cache(maxsize=None)
    def company_apps(company):
        return _applications_at_company(apps, company)

    return lambda job: job_level(conn, job, company_apps=company_apps)


def _reposted(app, posted, first_seen):
    """Is the scanned role probably a newer opening with the same title?"""
    if posted:
        # Posted after you applied: it cannot be the posting you applied to.
        return _older_than(app["applied_on"], posted, days=0)
    # No posting date (e.g. Microsoft): an old rejection plus a role still listed suggests a new opening.
    return app["status"] == "rejected" and _older_than(app["applied_on"], first_seen, days=14)


def _older_than(applied_on, first_seen, days):
    if not applied_on or not first_seen:
        return False
    try:
        a = dt.date.fromisoformat(applied_on[:10])
        f = dt.date.fromisoformat(first_seen[:10])
    except ValueError:
        return False
    return (f - a).days > days


def job_level(conn, job, apps=None, *, company_apps=None):
    """applied_match for a stored job row, honouring "not a duplicate" when you said so."""
    level, app = applied_match(conn, job["url"], job["company"], job["title"], _apps=apps,
                               first_seen=job["first_seen"] if "first_seen" in job.keys() else None,
                               posted=job["posted"] if "posted" in job.keys() else None, company_apps=company_apps)
    if level == "possible" and "not_duplicate" in job.keys() and job["not_duplicate"]:
        return None, None
    return level, app


def set_not_duplicate(conn, key, flag=True):
    job = get_job(conn, key)
    if job:
        conn.execute("UPDATE jobs SET not_duplicate = ? WHERE url = ?", (1 if flag else 0, job["url"]))
        conn.commit()
    return job


def is_applied(conn, url=None, company=None, title=None):
    if url and conn.execute("SELECT 1 FROM applications WHERE url = ?", (url,)).fetchone():
        return True
    if company and title:
        return bool(conn.execute(
            "SELECT 1 FROM applications WHERE lower(company)=lower(?) AND lower(title)=lower(?)",
            (company, title)).fetchone())
    return False


def add_application(conn, company, title, url=None, location=None, status="applied", resume=None,
                    source="jobbot", applied_on=None, notes=None):
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    stamp = now()
    existing = find_application(conn, url) if url else None
    if existing:
        if status in ("applied", "shortlisted") and existing["status"] not in ("applied", "shortlisted"):
            return existing   # already further along (assessment, interview, offer, rejected...): keep it
        return update_status(conn, existing["id"], status, notes)
    cur = conn.execute(
        "INSERT INTO applications (url, company, title, location, status, resume, source, applied_on, updated_on, notes)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (url, company, title, location, status, resume, source,
         applied_on or (today() if status != "shortlisted" else None), stamp, notes),
    )
    conn.execute("INSERT INTO events (application_id, at, status, note) VALUES (?,?,?,?)",
                 (cur.lastrowid, stamp, status, notes or f"added via {source}"))
    conn.commit()
    return find_application(conn, cur.lastrowid)


def update_status(conn, key, status, note=None):
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    app = find_application(conn, key)
    if not app:
        raise KeyError(f"no application matches {key}")
    stamp = now()
    applied_on = app["applied_on"] or (today() if status == "applied" else None)
    conn.execute("UPDATE applications SET status=?, updated_on=?, applied_on=? WHERE id=?",
                 (status, stamp, applied_on, app["id"]))
    conn.execute("INSERT INTO events (application_id, at, status, note) VALUES (?,?,?,?)",
                 (app["id"], stamp, status, note))
    conn.commit()
    return find_application(conn, app["id"])


def submitted_today(conn):
    """Applications jobbot submitted today (for automation.max_applications_per_day)."""
    return conn.execute("SELECT COUNT(*) FROM applications WHERE source = 'jobbot' AND applied_on = ?",
                        (today(),)).fetchone()[0]


def edit_application(conn, key, company=None, title=None, url=None):
    """Fix an application's company, role or posting link (e.g. a Gmail import that didn't name the role)."""
    app = find_application(conn, key)
    if not app:
        return None
    new = {"company": (company or "").strip() or app["company"], "title": (title or "").strip() or app["title"],
           "url": (url.strip() or None) if url is not None else app["url"]}
    changed = [f"{k}: {app[k] or '-'} → {new[k] or '-'}" for k in new if new[k] != app[k]]
    if changed:
        conn.execute("UPDATE applications SET company=?, title=?, url=?, updated_on=? WHERE id=?",
                     (new["company"], new["title"], new["url"], now(), app["id"]))
        conn.execute("INSERT INTO events (application_id, at, status, note) VALUES (?,?,?,?)",
                     (app["id"], now(), app["status"], "edited " + "; ".join(changed)))
        conn.commit()
    return find_application(conn, app["id"])


def list_applications(conn, status=None, company=None):
    sql, args = "SELECT * FROM applications WHERE 1=1", []
    if status:
        sql += " AND status = ?"
        args.append(status)
    if company:
        sql += " AND lower(company) LIKE ?"
        args.append(f"%{company.lower()}%")
    sql += " ORDER BY updated_on DESC"
    return conn.execute(sql, args).fetchall()


def events_for(conn, app_id):
    return conn.execute("SELECT * FROM events WHERE application_id = ? ORDER BY at", (app_id,)).fetchall()


def stats(conn):
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM applications GROUP BY status").fetchall()
    return {r["status"]: r["n"] for r in rows}


EXPORT_FIELDS = ("id", "company", "title", "location", "status", "applied_on", "updated_on", "resume", "source", "url", "notes")


def export_csv(conn, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(EXPORT_FIELDS)
        for a in list_applications(conn):
            w.writerow([a[k] for k in EXPORT_FIELDS])


def import_csv(conn, path):
    """Import rows with at least company and title. Existing URLs are updated, not duplicated."""
    added = 0
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if not row.get("company") or not row.get("title"):
                continue
            status = (row.get("status") or "applied").strip().lower()
            if status not in STATUSES:   # e.g. "Applied - phone screen": keep the row, note the original
                row["notes"] = "; ".join(filter(None, [row.get("notes"), f"status in file: {row.get('status')}"]))
                status = next((s for s in STATUSES if s in status), "applied")
            url = (row.get("url") or "").strip() or None
            if not url and is_applied(conn, company=row["company"], title=row["title"]):
                continue
            add_application(conn, row["company"].strip(), row["title"].strip(), url=url,
                            location=row.get("location"), status=status, resume=row.get("resume"),
                            source=row.get("source") or "import", applied_on=row.get("applied_on") or None,
                            notes=row.get("notes"))
            added += 1
    return added
