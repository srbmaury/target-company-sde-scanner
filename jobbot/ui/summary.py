"""Application dashboard summary metrics and rates."""

from .. import tracker


def summary_payload(conn, open_jobs=None):
    """Return status totals and rates, excluding non-submitted applications."""
    stats = tracker.stats(conn)
    total = sum(v for k, v in stats.items() if k not in ("shortlisted", "submission_unverified"))
    responded = sum(stats.get(k, 0) for k in ("assessment", "interview", "offer", "rejected"))
    return {
        "applications": stats, "total": total,
        "response_rate": round(100 * responded / total) if total else 0,
        "interview_rate": round(100 * (stats.get("interview", 0) + stats.get("offer", 0)) / total) if total else 0,
        "open_jobs": open_jobs,
    }
