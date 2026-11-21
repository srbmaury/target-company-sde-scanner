"""Pure sorting, pagination and dashboard job view classification."""

def table_page(rows, params, columns, default_sort):
    """Bound the response after sorting the full filtered result."""
    column = params.get("sort", default_sort)
    if column not in columns:
        raise ValueError("Invalid sort column.")
    descending = params.get("direction", "desc") == "desc"
    def sort_key(row):
        value = row[column]
        return (value is not None, value or 0) if column in ("n", "id", "fit_score") else str(value or "").casefold()
    rows.sort(key=sort_key, reverse=descending)
    offset = max(0, int(params.get("offset", "0")))
    end = offset + 50
    return {"rows": rows[offset:end], "total": len(rows),
            "next_offset": end if end < len(rows) else None}


def jobs_page(rows, params):
    def view(job):
        if job["dismissed"]:
            return "dismissed"
        if job["applied"] in ("exact", "likely"):
            return "applied"
        if job["excluded"] and not job["gone"]:
            return "excluded"
        if job["applied"] == "possible":
            return "possible" if not job["gone"] else None
        return "gone" if job["gone"] else "new"

    counts = {"all": len(rows)}
    selected = params["view"]
    matching = []
    for job in rows:
        bucket = view(job)
        if bucket:
            counts[bucket] = counts.get(bucket, 0) + 1
        if selected == "all" or selected == bucket:
            matching.append(job)
    return {**table_page(matching, params, {"n", "fit_score", "company", "title", "location", "experience"},
                         "fit_score"), "counts": counts}

