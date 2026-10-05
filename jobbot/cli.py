"""jobbot command line.

    jobbot init                     create ~/.jobbot/profile.yaml from the example
    jobbot doctor                   check profile, resumes, browser, and Ollama
    jobbot scan [--companies ...]   sweep company job boards; new roles go into the tracker
    jobbot jobs                     list tracked roles you have not applied to, best fit first
    jobbot rank                     score unranked roles against your resumes
    jobbot apply <n|url> ...        fill applications in a browser; you approve each submit
    jobbot dismiss <n>              hide a role you are not interested in
    jobbot track ...                list, add, update, export, and import applications (CSV or Gmail JSON)
"""

import argparse
import sys
import textwrap

from . import llm as llm_mod
from . import paths, profile as profile_mod, tracker
from .scan import DEFAULT_LOCATIONS, run_scan


def _profile():
    try:
        return profile_mod.load()
    except profile_mod.ProfileError as e:
        sys.exit(str(e))


def _llm(args):
    if getattr(args, "llm", "ollama") == "none":
        return llm_mod.LLM(enabled=False)
    model = llm_mod.LLM(model=args.model)
    if not model.enabled:
        print("Ollama is not running; continuing without the local model (`ollama serve` to enable).")
    elif not model.has_model():
        print(f"Model {args.model} is not pulled; run `ollama pull {args.model}`. Continuing without it.")
        model.enabled = False
    return model


def _short(text, n):
    text = (text or "").replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"


# --- commands ----------------------------------------------------------------

def cmd_init(args):
    created = profile_mod.init(force=args.force)
    print(("Created " if created else "Profile already exists: ") + str(paths.PROFILE))
    if created:
        print("Edit it with your details and resume paths, then run `jobbot doctor`.")


def cmd_doctor(args):
    ok = True
    try:
        p = profile_mod.load()
        print(f"✓ profile: {p.path}")
        rs = p.resumes()
        missing = set((p.get("resumes") or {})) - set(rs)
        print(f"✓ resumes found: {', '.join(rs) or 'none'}")
        if missing:
            ok = False
            print(f"✗ resume files missing for: {', '.join(sorted(missing))}")
    except profile_mod.ProfileError as e:
        ok = False
        print(f"✗ {e}")
    import importlib.util

    if importlib.util.find_spec("playwright"):
        print("✓ playwright installed")
    else:
        ok = False
        print("✗ playwright missing: pip install -r requirements.txt")
    model = llm_mod.LLM(model=args.model)
    if model.enabled:
        print(f"✓ ollama running; model {args.model}: {'ready' if model.has_model() else 'not pulled'}")
    else:
        print("- ollama not running (optional): brew install ollama && brew services start ollama")
    conn = tracker.connect()
    print(f"✓ tracker: {paths.DB} ({sum(tracker.stats(conn).values())} applications)")
    sys.exit(0 if ok else 1)


def cmd_scan(args):
    p = _profile()
    conn = tracker.connect()
    exclude = list(p.get("preferences.exclude_companies") or []) + [x for x in args.exclude.split(",") if x]
    applied = {r["url"] for r in tracker.list_applications(conn) if r["url"]}
    print("Scanning job boards (about 2 minutes for --all)…")
    results, coverage, missing = run_scan(
        companies=args.companies.split(",") if args.companies else None,
        exclude=exclude,
        locations=args.locations or p.get("preferences.locations") or DEFAULT_LOCATIONS,
        max_yoe=args.max_yoe if args.max_yoe is not None else p.get("preferences.max_yoe", 3),
        include_unstated=args.include_unstated, skip_urls=applied,
    )
    if missing:
        print(f"Not in registry: {', '.join(missing)}")
    new = set(tracker.upsert_jobs(conn, results))
    errors = [k for k, v in coverage.items() if v.startswith("error")]
    print(f"{len(results)} matching roles across {len(coverage)} companies; {len(new)} new.")
    if errors:
        print(f"Boards that errored: {', '.join(sorted(errors))}")
    shown = [r for r in results if r["url"] in new] if not args.show_all else results
    for r in shown:
        flag = "NEW " if r["url"] in new else "    "
        print(f"{flag}{r['company']:22s} {_short(r['title'], 58):58s} {_short(r['location'], 28):28s} {r['experience']}")
    if new:
        print("\nNext: `jobbot rank` to score them, then `jobbot jobs`.")


def cmd_jobs(args):
    conn = tracker.connect()
    rows = tracker.list_jobs(conn, include_applied=args.include_applied, limit=args.limit)
    if not rows:
        print("No tracked roles yet. Run `jobbot scan`.")
        return
    print(f"{'#':>4} {'fit':>3}  {'company':20s} {'role':52s} {'location':24s} {'exp':16s} resume")
    for r in rows:
        fit = "" if r["fit_score"] is None else str(r["fit_score"])
        print(f"{r['n']:>4} {fit:>3}  {_short(r['company'], 20):20s} {_short(r['title'], 52):52s} "
              f"{_short(r['location'], 24):24s} {_short(r['experience'], 16):16s} {r['fit_resume'] or ''}")
        if args.why and r["fit_reason"]:
            print(f"{'':10s}{_short(r['fit_reason'], 140)}")
        if args.urls:
            print(f"{'':10s}{r['url']}")


def cmd_rank(args):
    from .rank import rank_jobs

    p, conn, model = _profile(), tracker.connect(), _llm(args)
    how = f"local model {model.model}" if model.enabled else "keyword matching"
    print(f"Ranking with {how}…")

    def progress(i, total, job, score):
        print(f"  [{i}/{total}] {score:>3}  {job['company']} — {_short(job['title'], 60)}")

    done = rank_jobs(conn, p, model, limit=args.limit, rerank=args.rerank, on_progress=progress)
    print(f"Ranked {len(done)} roles. `jobbot jobs --why` shows the best fits first.")


def cmd_apply(args):
    from .apply.engine import Session, record
    from .apply.ui import TerminalUI

    p, conn, model = _profile(), tracker.connect(), _llm(args)
    targets = []
    if args.top:
        targets = [dict(r) for r in tracker.list_jobs(conn, limit=args.top) if r["fit_score"] is not None]
        if not targets:
            sys.exit("No ranked roles. Run `jobbot rank` first.")
    for key in args.jobs:
        row = tracker.get_job(conn, key)
        if row:
            targets.append(dict(row))
        elif key.startswith("http"):
            company = input(f"Company for {key}: ").strip()
            title = input("Role title: ").strip()
            targets.append({"url": key, "company": company, "title": title, "location": "", "ats": None,
                            "board": None, "description": "", "experience": "", "evidence": "", "fit_resume": None})
        else:
            print(f"Skipping {key}: not a tracked job number or URL.")
    if not targets:
        sys.exit("Nothing to apply to. Pass job numbers from `jobbot jobs`, URLs, or --top N.")

    resumes = p.resumes()
    if not resumes:
        sys.exit("No resume files found; fix `resumes:` in your profile.")
    ui = TerminalUI()
    with Session(p, model, ui, dry_run=args.dry_run, upload=not args.no_upload) as session:
        for job in targets:
            if tracker.is_applied(conn, url=job["url"]) and not args.force:
                print(f"\nAlready applied: {job['company']} — {job['title']} (use --force to reopen)")
                continue
            resume_key = args.resume or job.get("fit_resume") or next(iter(resumes))
            if resume_key not in resumes:
                print(f"Resume '{resume_key}' not found; using {next(iter(resumes))}.")
                resume_key = next(iter(resumes))
            print(f"\n=== {job['company']} — {job['title']} ===")
            try:
                status, note = session.apply(job, resume_key)
            except KeyboardInterrupt:
                print("\nStopped.")
                break
            except Exception as e:
                print(f"  ! {type(e).__name__}: {e}")
                status, note = None, None
            if status and not args.dry_run:
                app = record(conn, job, status, note, resume_key)
                print(f"  ✓ Tracked as application #{app['id']} ({status}).")
            elif args.dry_run:
                print("  Dry run: nothing recorded.")


def cmd_dismiss(args):
    conn = tracker.connect()
    for key in args.jobs:
        job = tracker.dismiss_job(conn, key)
        print(f"Dismissed {job['company']} — {job['title']}" if job else f"No job {key}")


def cmd_track(args):
    conn = tracker.connect()
    action = args.action or "list"
    if action == "list":
        rows = tracker.list_applications(conn, status=args.status, company=args.company)
        if not rows:
            print("No applications tracked yet.")
            return
        print(f"{'id':>4}  {'status':11s} {'applied':10s} {'company':22s} {'role':50s} source")
        for a in rows:
            print(f"{a['id']:>4}  {a['status']:11s} {a['applied_on'] or '':10s} {_short(a['company'], 22):22s} "
                  f"{_short(a['title'], 50):50s} {a['source'] or ''}")
        counts = tracker.stats(conn)
        print("\n" + "  ".join(f"{k}: {v}" for k, v in sorted(counts.items())) + f"  (total {sum(counts.values())})")
    elif action == "add":
        if not (args.company and args.title):
            sys.exit("track add needs --company and --title")
        a = tracker.add_application(conn, args.company, args.title, url=args.url, location=args.location,
                                    status=args.status or "applied", resume=args.resume, source=args.source or "manual",
                                    applied_on=args.date, notes=args.note)
        print(f"Added #{a['id']}: {a['company']} — {a['title']} ({a['status']})")
    elif action == "update":
        if not (args.ref and args.status):
            sys.exit("track update needs an application id (or URL) and --status")
        a = tracker.update_status(conn, args.ref, args.status, args.note)
        print(f"#{a['id']} {a['company']} — {a['title']} is now {a['status']}")
    elif action == "show":
        a = tracker.find_application(conn, args.ref)
        if not a:
            sys.exit(f"No application {args.ref}")
        for k in tracker.EXPORT_FIELDS:
            print(f"{k:11s} {a[k] or ''}")
        print("history:")
        for e in tracker.events_for(conn, a["id"]):
            print(f"  {e['at']}  {e['status']:11s} {e['note'] or ''}")
    elif action == "stats":
        counts = tracker.stats(conn)
        total = sum(counts.values())
        for k in tracker.STATUSES:
            if counts.get(k):
                print(f"{k:11s} {counts[k]:>4}")
        print(f"{'total':11s} {total:>4}")
        responded = sum(counts.get(k, 0) for k in ("assessment", "interview", "offer", "rejected"))
        if total:
            print(f"response rate {100 * responded / total:.0f}%   interview rate "
                  f"{100 * (counts.get('interview', 0) + counts.get('offer', 0)) / total:.0f}%")
    elif action == "export":
        out = args.ref or "applications.csv"
        tracker.export_csv(conn, out)
        print(f"Wrote {out}")
    elif action == "import":
        if not args.ref:
            sys.exit("track import needs a CSV path")
        print(f"Imported {tracker.import_csv(conn, args.ref)} rows")
    elif action == "import-gmail":
        from . import mailimport

        if not args.ref:
            sys.exit("track import-gmail needs a JSON file of emails (see jobbot/mailimport.py)")
        rows = mailimport.rows_from(mailimport.load(args.ref))
        added, updated = mailimport.import_rows(conn, rows)
        print(f"Read {len(rows)} application emails: {added} new applications, {updated} status updates.")


def build_parser():
    ap = argparse.ArgumentParser(prog="jobbot", description=textwrap.dedent(__doc__),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def with_llm(sp):
        sp.add_argument("--llm", choices=("ollama", "none"), default="ollama")
        sp.add_argument("--model", default=llm_mod.DEFAULT_MODEL)

    sp = sub.add_parser("init", help="create your profile")
    sp.add_argument("--force", action="store_true", help="overwrite an existing profile")
    sp.set_defaults(fn=cmd_init)

    sp = sub.add_parser("doctor", help="check setup")
    sp.add_argument("--model", default=llm_mod.DEFAULT_MODEL)
    sp.set_defaults(fn=cmd_doctor)

    sp = sub.add_parser("scan", help="find matching roles")
    sp.add_argument("--companies", help="comma-separated registry names (default: all)")
    sp.add_argument("--exclude", default="", help="extra companies to skip")
    sp.add_argument("--locations", help="location regex (default: profile preferences)")
    sp.add_argument("--max-yoe", type=int)
    sp.add_argument("--include-unstated", action="store_true")
    sp.add_argument("--show-all", action="store_true", help="print every match, not only new ones")
    sp.set_defaults(fn=cmd_scan)

    sp = sub.add_parser("jobs", help="list tracked roles")
    sp.add_argument("--limit", type=int, default=40)
    sp.add_argument("--why", action="store_true", help="show the fit reason")
    sp.add_argument("--urls", action="store_true")
    sp.add_argument("--include-applied", action="store_true")
    sp.set_defaults(fn=cmd_jobs)

    sp = sub.add_parser("rank", help="score roles against your resumes")
    with_llm(sp)
    sp.add_argument("--limit", type=int)
    sp.add_argument("--rerank", action="store_true", help="re-score roles that already have a score")
    sp.set_defaults(fn=cmd_rank)

    sp = sub.add_parser("apply", help="fill applications in a browser")
    with_llm(sp)
    sp.add_argument("jobs", nargs="*", help="job numbers from `jobbot jobs`, or posting URLs")
    sp.add_argument("--top", type=int, help="apply to the N best-ranked roles, one after another")
    sp.add_argument("--resume", help="resume key from your profile (default: the ranked best match)")
    sp.add_argument("--dry-run", action="store_true", help="fill forms but never submit or record")
    sp.add_argument("--no-upload", action="store_true", help="do not attach a resume")
    sp.add_argument("--force", action="store_true", help="reopen roles already marked applied")
    sp.set_defaults(fn=cmd_apply)

    sp = sub.add_parser("dismiss", help="hide roles you do not want")
    sp.add_argument("jobs", nargs="+")
    sp.set_defaults(fn=cmd_dismiss)

    sp = sub.add_parser("track", help="application tracker",
                        description="actions: list (default), add, update <id>, show <id>, stats, export [file], import <csv>, "
                                    "import-gmail <json>")
    sp.add_argument("action", nargs="?", choices=("list", "add", "update", "show", "stats", "export", "import", "import-gmail"))
    sp.add_argument("ref", nargs="?", help="application id or URL (update/show), or file path (export/import)")
    sp.add_argument("--status", choices=tracker.STATUSES)
    sp.add_argument("--company")
    sp.add_argument("--title")
    sp.add_argument("--url")
    sp.add_argument("--location")
    sp.add_argument("--resume")
    sp.add_argument("--source")
    sp.add_argument("--date", help="applied date, YYYY-MM-DD")
    sp.add_argument("--note")
    sp.set_defaults(fn=cmd_track)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
