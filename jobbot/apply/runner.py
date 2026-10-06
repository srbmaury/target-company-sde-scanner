"""Choosing which roles to apply to, and working through them. Shared by the terminal
command (`jobbot apply`) and the dashboard, so both behave the same."""

from .. import tracker


def excluded(company, exclude):
    """True when `company` is one of `exclude`, ignoring case, punctuation and suffixes ("Inito Inc" = "inito")."""
    return any(tracker.same_company(company, x) for x in exclude)


def select_targets(conn, keys=(), all_=False, top=None, min_fit=None, force=False, ask_url=None, note=print,
                   exclude=()):
    """Resolve job numbers, ranges, URLs, --top and --all into a list of job dicts.

    Roles at companies in `exclude` are skipped (with a note when you named them explicitly).

    Already-applied roles (exact or likely matches) are skipped unless force; "possibly applied"
    roles are kept with a `_possible` explanation so the caller can ask first.
    """
    from ..cli import expand_job_keys   # local import: cli imports this module

    targets = []
    if all_:
        targets = [dict(r) for r in tracker.list_jobs(conn)]
    elif top:   # the N best roles after exclusions, so --top 10 --exclude X still gives 10
        ranked = [dict(r) for r in tracker.list_jobs(conn) if r["fit_score"] is not None]
        targets = [t for t in ranked if not excluded(t["company"], exclude)][:top]
    for key in expand_job_keys(list(keys)):
        row = tracker.get_job(conn, key)
        if row and row["dismissed"]:
            note(f"Skipping #{key}: dismissed ({row['company']} — {row['title']}).")
        elif row:
            targets.append(dict(row))
        elif key.startswith("http") and ask_url:
            company, title = ask_url(key)
            targets.append({"url": key, "company": company, "title": title, "location": "", "ats": None,
                            "board": None, "description": "", "experience": "", "evidence": "", "fit_resume": None})
        else:
            note(f"Skipping {key}: not a tracked job number or URL.")
    if min_fit is not None:
        targets = [t for t in targets if (t.get("fit_score") or 0) >= min_fit]
    if exclude:
        skipped = [t for t in targets if excluded(t["company"], exclude)]
        if skipped and keys:
            note("Skipping excluded companies: " + ", ".join(sorted({t["company"] for t in skipped})) + ".")
        targets = [t for t in targets if t not in skipped]
    seen, unique = set(), []
    for t in targets:
        if t["url"] in seen:
            continue
        seen.add(t["url"])
        level, app = tracker.applied_match(conn, t["url"], t["company"], t["title"], first_seen=t.get("first_seen"),
                                            posted=t.get("posted"))
        if level in ("exact", "likely") and not force:
            note(f"Skipping {t['company']} — {t['title']}: already applied "
                 f"(#{app['id']} {app['title']}, {app['status']}, {app['applied_on'] or 'date unknown'}).")
            continue
        if level == "possible":
            what = "an unnamed" if app["title"].startswith("(role not stated") else f"a similar ({app['title']})"
            t["_possible"] = f"you applied to {what} {app['company']} role on {app['applied_on'] or 'an unknown date'}"
        unique.append(t)
    return unique


def run_jobs(session, conn, profile, targets, ui, resume=None, dry_run=False, confirm_possible=True,
             should_stop=lambda: False, on_job=None, on_result=None):
    """Apply to each target in turn. Returns a list of (job, status, note, application id).

    In an unattended session, jobs that need you get status "needs you" (with the reason), and
    finished ones "ready" (held open for review_ready)."""
    from .engine import NeedsYou, record

    resumes = profile.resumes()
    cap = int(profile.get("automation.max_applications_per_day", 25) or 0)
    results = []
    for n, job in enumerate(targets, 1):
        if should_stop():
            break
        if cap and not dry_run and tracker.submitted_today(conn) >= cap:
            ui.warn(f"Daily limit reached ({cap} applications today, automation.max_applications_per_day); "
                    "stopping. Many job sites discourage high-volume applying.")
            break
        if job.get("_possible") and confirm_possible and not ui.confirm(
                f"{job['company']} — {job['title']}: {job['_possible']}. Apply anyway?"):
            results.append((job, "skipped", "possibly applied already", None))
            if on_result:
                on_result(job, "skipped", "possibly applied already", None)
            continue
        resume_key = resume or job.get("fit_resume") or next(iter(resumes))
        if resume_key not in resumes:
            ui.warn(f"Resume '{resume_key}' not found; using {next(iter(resumes))}.")
            resume_key = next(iter(resumes))
        if on_job:
            on_job(n, len(targets), job)
        try:
            status, note = session.apply(job, resume_key)
        except NeedsYou as e:
            ui.warn(f"Needs you, moving on: {str(e)[:200]}")
            status, note = "needs you", str(e)[:300]
        except KeyboardInterrupt:
            raise
        except Exception as e:  # one broken site must not stop the batch
            ui.warn(f"{type(e).__name__}: {e}")
            status, note = None, f"error: {type(e).__name__}"
        app_id = None
        if status in ("needs you", "ready"):
            if status == "ready":
                ui.info("Filled and checked; held open for your Submit at the end.")
            results.append((job, status, note, None))
            if on_result:
                on_result(job, status, note, None)
            continue
        if status and not dry_run:
            app_id = record(conn, job, status, note, resume_key)["id"]
            ui.info(f"✓ Tracked as application #{app_id} ({status}).")
        elif dry_run:
            ui.info("Dry run: nothing recorded.")
        results.append((job, status or "not submitted", note, app_id))
        if on_result:
            on_result(job, status or "not submitted", note, app_id)
    return results


def review_ready(session, conn, results, ui, resume=None, on_result=None):
    """After an unattended batch: list what needs you, then go through each held application for your Submit."""
    from .engine import record

    needs = [(j, n) for j, s, n, _ in results if s == "needs you"]
    ready = [j for j, s, _, _ in results if s == "ready"]
    if needs:
        ui.warn(f"{len(needs)} application(s) need you:")
        for job, note in needs:
            ui.warn(f"  {job['company']} — {job['title']}: {note[:160]}  {job['url']}")
    for i, job in enumerate(ready, 1):
        if job["url"] not in session.ready:
            continue
        session.ready[job["url"]][0].bring_to_front()
        ui.info(f"Ready to submit ({i}/{len(ready)}): {job['company']} — {job['title']}")
        while job["url"] in session.ready:
            choice = ui.next_action(can_submit=True, can_next=False, dry_run=False, check_ok=True, final_page=True)
            if choice == "refill":
                continue   # nothing to refill here: look at the tab, then choose again
            if choice == "submit":
                status, note = session.submit_ready(job["url"])
            elif choice == "done":
                session.discard_ready(job["url"])
                status, note = "applied", "you submitted it in the browser"
            else:
                session.discard_ready(job["url"])
                status, note = None, "not submitted"
            if status:
                app_id = record(conn, job, status, note, resume or job.get("fit_resume"))["id"]
                ui.info(f"✓ Tracked as application #{app_id} ({status}): {note[:80]}")
            elif job["url"] in session.ready:
                ui.warn(note)
                continue
            if on_result:
                on_result(job, status or "not submitted", note, None)
    return len(ready), len(needs)
