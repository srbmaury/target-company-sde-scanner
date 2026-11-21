"""Dashboard job filtering and eligibility queries."""

from .. import profile as profile_mod, tracker

def _excluded_companies():
    """preferences.exclude_companies, so the page can show which roles apply will skip."""
    try:
        return list(profile_mod.load().get("preferences.exclude_companies") or [])
    except Exception:   # missing or invalid profile: nothing is excluded
        return []


def jobs_payload(conn, params):
    from ..apply.runner import excluded
    exclude = _excluded_companies()
    include_applied = params.get("include_applied") == "1"
    include_dismissed = params.get("include_dismissed") == "1"
    rows = tracker.list_jobs(conn, include_applied=True, include_dismissed=include_dismissed, include_gone=True)
    match = tracker.job_matcher(conn)
    q = (params.get("q") or "").lower()
    min_fit = int(params["min_fit"]) if params.get("min_fit", "").isdigit() else None
    out = []
    for r in rows:
        if q and q not in f"{r['company']} {r['title']} {r['location']} {r['ats'] or ''}".lower():
            continue
        if min_fit is not None and (r["fit_score"] or 0) < min_fit:
            continue
        level, app = match(r)
        if level in ("exact", "likely") and not include_applied:
            continue
        item = {k: r[k] for k in ("n", "url", "company", "title", "location", "ats", "experience", "evidence",
                                  "posted", "first_seen", "fit_score", "fit_resume", "fit_reason", "dismissed",
                                  "not_duplicate")}
        item["applied"] = level
        item["excluded"] = excluded(r["company"], exclude)
        item["gone"] = bool(r["gone"])
        item["applied_note"] = (f"#{app['id']} {app['title']} ({app['status']}, {app['applied_on'] or 'date unknown'})"
                                if app else "")
        out.append(item)
    return out


def _new_jobs(conn):
    """Roles you can apply to: not dismissed, not applied, not possibly applied, not at an excluded company."""
    from ..apply.runner import excluded
    match, exclude = tracker.job_matcher(conn), _excluded_companies()
    return sum(1 for r in tracker.list_jobs(conn, include_applied=True)
               if not excluded(r["company"], exclude) and match(r)[0] is None)

