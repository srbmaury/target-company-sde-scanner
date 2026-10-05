"""SQLite tracker for discovered jobs and submitted applications.

Two tables:
  jobs          every role a scan has surfaced (keyed by posting URL), with fit scores
  applications  every application you have made, through jobbot or elsewhere,
                with a status history in `events`
"""

import csv
import datetime as dt
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
    sql = "SELECT rowid AS n, * FROM jobs WHERE 1=1"
    if unranked:
        sql += " AND fit_score IS NULL"
    if not include_applied:
        sql += " AND url NOT IN (SELECT url FROM applications WHERE url IS NOT NULL)"
    if not include_dismissed:
        sql += " AND dismissed = 0"
    sql += " ORDER BY fit_score IS NULL, fit_score DESC, first_seen DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql).fetchall()


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
            url = (row.get("url") or "").strip() or None
            if not url and is_applied(conn, company=row["company"], title=row["title"]):
                continue
            add_application(conn, row["company"].strip(), row["title"].strip(), url=url,
                            location=row.get("location"), status=status, resume=row.get("resume"),
                            source=row.get("source") or "import", applied_on=row.get("applied_on") or None,
                            notes=row.get("notes"))
            added += 1
    return added
