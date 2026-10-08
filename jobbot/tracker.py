"""SQLite tracker for discovered jobs and submitted applications.

Two tables:
  jobs          every role a scan has surfaced (keyed by posting URL), with fit scores
  applications  every application you have made, through jobbot or elsewhere,
                with a status history in `events`
"""

import csv
import datetime as dt
import re
import sqlite3

from . import paths

STATUSES = ("shortlisted", "applied", "assessment", "interview", "offer", "rejected", "withdrawn", "ghosted")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    url TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    ats TEXT,
    board TEXT,
    experience TEXT,
    evidence TEXT,
    description TEXT,
    posted TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    fit_score INTEGER,
    fit_resume TEXT,
    fit_reason TEXT,
    dismissed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    status TEXT NOT NULL,
    resume TEXT,
    source TEXT,
    applied_on TEXT,
    updated_on TEXT NOT NULL,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES applications(id),
    at TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT
);
"""


def now():
    return dt.datetime.now().isoformat(timespec="seconds")


def today():
    return dt.date.today().isoformat()


def connect(path=None):
    paths.ensure_home()
    conn = sqlite3.connect(path or paths.DB)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    if "not_duplicate" not in cols:   # added later: you marked a "possibly applied" role as a different opening
        conn.execute("ALTER TABLE jobs ADD COLUMN not_duplicate INTEGER DEFAULT 0")
        conn.commit()
    return conn


# --- jobs ---------------------------------------------------------------------

def upsert_jobs(conn, results):
    """Store scan results. Returns the URLs that were new to the tracker."""
    new, stamp = [], now()
    for r in results:
        cur = conn.execute("SELECT 1 FROM jobs WHERE url = ?", (r["url"],))
        if cur.fetchone():
            conn.execute(
                "UPDATE jobs SET last_seen=?, title=?, location=?, experience=?, evidence=?, description=? WHERE url=?",
                (stamp, r["title"], r["location"], r["experience"], r["evidence"], r.get("description", ""), r["url"]),
            )
        else:
            new.append(r["url"])
            conn.execute(
                "INSERT INTO jobs (url, company, title, location, ats, board, experience, evidence, description,"
                " posted, first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["url"], r["company"], r["title"], r["location"], r.get("ats"), r.get("board"), r["experience"],
                 r["evidence"], r.get("description", ""), r.get("posted", ""), stamp, stamp),
            )
    conn.commit()
    return new


def get_job(conn, key):
    """Look a job up by URL or by its row number in `jobbot jobs` output."""
    if str(key).isdigit():
        return conn.execute("SELECT rowid AS n, * FROM jobs WHERE rowid = ?", (int(key),)).fetchone()
    return conn.execute("SELECT rowid AS n, * FROM jobs WHERE url = ?", (key,)).fetchone()


def list_jobs(conn, unranked=False, include_applied=False, include_dismissed=False, limit=None):
    """Tracked roles, best fit first. Unless include_applied, roles that match an application
    by URL or by company and title (see applied_match) are left out."""
    sql = "SELECT rowid AS n, * FROM jobs WHERE 1=1"
    if unranked:
        sql += " AND fit_score IS NULL"
    if not include_dismissed:
        sql += " AND dismissed = 0"
    sql += " ORDER BY fit_score IS NULL, fit_score DESC, first_seen DESC"
    rows = conn.execute(sql).fetchall()
    if not include_applied:
        apps = conn.execute("SELECT * FROM applications").fetchall()
        rows = [r for r in rows if job_level(conn, r, apps)[0] not in ("exact", "likely")]
    return rows[: int(limit)] if limit else rows


def set_fit(conn, url, score, resume, reason):
    conn.execute("UPDATE jobs SET fit_score=?, fit_resume=?, fit_reason=? WHERE url=?", (score, resume, reason, url))
    conn.commit()


def dismiss_job(conn, key):
    job = get_job(conn, key)
    if job:
        conn.execute("UPDATE jobs SET dismissed = 1 WHERE url = ?", (job["url"],))
        conn.commit()
    return job


# --- applications ---------------------------------------------------------------

def find_application(conn, key):
    if str(key).isdigit():
        return conn.execute("SELECT * FROM applications WHERE id = ?", (int(key),)).fetchone()
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
    t = t.replace("sde", "software development engineer").replace("swe", "software engineer")
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


def applied_match(conn, url=None, company=None, title=None, _apps=None, first_seen=None, posted=None):
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
    apps = _apps if _apps is not None else conn.execute("SELECT * FROM applications").fetchall()
    key = norm_company(company)
    if not key:
        return None, None
    same_company = [a for a in apps if norm_company(a["company"]) == key]
    for a in same_company:
        if titles_match(a["title"], title):
            if a["url"] and url and a["url"] != url:
                continue  # we know the exact posting applied to, and this is a different one
            if _reposted(a, posted, first_seen):
                return "possible", a  # big employers reuse titles; this looks like a newer opening
            return "likely", a
    for a in same_company:
        if a["title"].startswith("(role not stated"):
            return "possible", a
    return None, None


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


def job_level(conn, job, apps=None):
    """applied_match for a stored job row, honouring "not a duplicate" when you said so."""
    level, app = applied_match(conn, job["url"], job["company"], job["title"], _apps=apps,
                               first_seen=job["first_seen"] if "first_seen" in job.keys() else None,
                               posted=job["posted"] if "posted" in job.keys() else None)
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
