"""jobbot command line.

    jobbot init                     create profile.yaml (git-ignored) from the example
    jobbot doctor                   check profile, resumes, browser, and Ollama
    jobbot scan [--companies ...]   sweep company job boards; new roles go into the tracker
    jobbot jobs                     list tracked roles you have not applied to, best fit first
    jobbot rank                     score unranked roles against your resumes
    jobbot apply <n|x-y|url> ...    fill applications in a browser; you approve each submit
    jobbot apply --all [--min-fit N]  work through every tracked role, best fit first
    jobbot dismiss <n>              hide a role you are not interested in
    jobbot logs                     what apply filled, corrected and checked, page by page
    jobbot ui                       open the local dashboard: jobs, applications, actions, logs, profile
    jobbot track ...                list, add, update, export, and import applications (CSV or Gmail JSON)
    jobbot gmail login              connect Gmail read-only, then `jobbot track sync-gmail`
"""

import argparse
import re
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


def expand_job_keys(keys):
    """Turn "12", "12-20", "12..20", and "12,15" into individual keys; URLs pass through."""
    out = []
    for key in keys:
        for part in ([key] if key.startswith("http") else key.split(",")):
            part = part.strip()
            m = re.fullmatch(r"(\d+)\s*(?:-|\.\.)\s*(\d+)", part)
            if m:
                lo, hi = sorted((int(m.group(1)), int(m.group(2))))
                out.extend(str(n) for n in range(lo, hi + 1))
            elif part:
                out.append(part)
    return out


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
    from . import gmail

    print("✓ gmail: connected (read-only)" if gmail.is_connected() else
          "- gmail: not connected (optional): jobbot gmail login, then jobbot track sync-gmail")
    sys.exit(0 if ok else 1)


def cmd_scan(args):
    p = _profile()
    conn = tracker.connect()
    exclude = list(p.get("preferences.exclude_companies") or []) + [x for x in args.exclude.split(",") if x]
    applied = {r["url"] for r in tracker.list_applications(conn) if r["url"]}
    print("Scanning job boards and careers pages (a few minutes)…")
    results, coverage, missing = run_scan(
        companies=args.companies.split(",") if args.companies else None,
        exclude=exclude,
        locations=args.locations or p.get("preferences.locations") or DEFAULT_LOCATIONS,
        max_yoe=args.max_yoe if args.max_yoe is not None else p.get("preferences.max_yoe", 3),
        include_unstated=args.include_unstated, skip_urls=applied, careers_pages=not args.no_careers_pages,
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
    apps = conn.execute("SELECT * FROM applications").fetchall()
    for r in rows:
        fit = "" if r["fit_score"] is None else str(r["fit_score"])
        level, _ = tracker.applied_match(conn, r["url"], r["company"], r["title"], _apps=apps, first_seen=r["first_seen"],
                                              posted=r["posted"])
        mark = {"exact": " [applied]", "likely": " [applied]", "possible": " [applied?]"}.get(level, "")
        print(f"{r['n']:>4} {fit:>3}  {_short(r['company'], 20):20s} {_short(r['title'], 52):52s} "
              f"{_short(r['location'], 24):24s} {_short(r['experience'], 16):16s} {r['fit_resume'] or ''}{mark}")
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
    from .apply.engine import Session
    from .apply.runner import run_jobs, select_targets
    from .apply.ui import TerminalUI

    p, conn, model = _profile(), tracker.connect(), _llm(args)
    if args.top and not tracker.list_jobs(conn, limit=args.top):
        sys.exit("No tracked roles. Run `jobbot scan` first.")

    def ask_url(url):
        return input(f"Company for {url}: ").strip(), input("Role title: ").strip()

    exclude = list(p.get("preferences.exclude_companies") or []) + \
        [x.strip() for x in (args.exclude or "").split(",") if x.strip()]
    targets = select_targets(conn, args.jobs, all_=args.all, top=args.top, min_fit=args.min_fit, force=args.force,
                             ask_url=ask_url, exclude=exclude)
    if not targets:
        sys.exit("Nothing to apply to. Pass job numbers or ranges from `jobbot jobs` (12 or 12-20), URLs, "
                 "--top N, or --all.")
    if len(targets) > 3 and not args.yes:
        print(f"About to work through {len(targets)} roles:")
        for t in targets:
            fit = "" if t.get("fit_score") is None else f"{t['fit_score']:>3}"
            num = f"#{t['n']}" if t.get("n") else "   "
            flag = "  (possibly applied: " + t["_possible"] + ")" if t.get("_possible") else ""
            print(f"  {num:>5} {fit:>3}  {_short(t['company'], 22):22s} {_short(t['title'], 60)}{flag}")
        if input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("Cancelled.")
    if not p.resumes():
        sys.exit("No resume files found; fix `resumes:` in your profile.")

    ui = TerminalUI()
    with Session(p, model, ui, dry_run=args.dry_run, upload=not args.no_upload,
                 auto_next=not args.no_auto_next) as session:
        try:
            run_jobs(session, conn, p, targets, ui, resume=args.resume, dry_run=args.dry_run,
                     confirm_possible=not args.yes,
                     on_job=lambda n, total, job: print(f"\n=== [{n}/{total}] {job['company']} — {job['title']} ==="))
        except KeyboardInterrupt:
            print("\nStopped.")


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
    elif action == "sync-gmail":
        sync_gmail(conn, args)
    elif action == "import-gmail":
        from . import mailimport

        if not args.ref:
            sys.exit("track import-gmail needs a JSON file of emails (see jobbot/mailimport.py)")
        rows = mailimport.rows_from(mailimport.load(args.ref))
        added, updated = mailimport.import_rows(conn, rows)
        print(f"Read {len(rows)} application emails: {added} new applications, {updated} status updates.")


def cmd_gmail(args):
    from . import gmail

    try:
        if args.action == "login":
            email = gmail.login(args.client)
            print(f"Connected to Gmail as {email} (read-only). Run `jobbot track sync-gmail` to import applications.")
        elif args.action == "logout":
            print("Disconnected and revoked jobbot's Gmail access." if gmail.logout() else "Gmail was not connected.")
        else:
            if gmail.is_connected():
                print(f"Connected (read-only) as {gmail.profile_email()}. Token: {gmail.token_path()}")
            else:
                print("Not connected. Run `jobbot gmail login`.")
    except gmail.GmailError as e:
        sys.exit(str(e))


def sync_gmail(conn, args):
    from . import gmail, mailimport

    try:
        if not gmail.is_connected():
            if not sys.stdin.isatty():
                sys.exit("Gmail is not connected. Run `jobbot gmail login` (or use Connect Gmail in the dashboard).")
            if input("Gmail is not connected. Sign in with Google now (read-only)? [Y/n] ").strip().lower() in ("n", "no"):
                sys.exit("Skipped. Run `jobbot gmail login` when you are ready.")
            print(f"Connected as {gmail.login()}.")
        query = "-in:spam -in:trash" if args.all_mail else (args.query or gmail.DEFAULT_QUERY)
        what = "all mail" if args.all_mail else "application emails"
        print(f"Reading {what} from the last {args.days} days (sender, subject, preview and date only)…")
        messages = gmail.search(query, days=args.days, limit=args.limit,
                                on_progress=lambda i, n: print(f"  {i}/{n}", end="\r"))
    except gmail.GmailError as e:
        sys.exit(str(e))
    rows = mailimport.rows_from(messages)
    added, updated = mailimport.import_rows(conn, rows)
    print(f"Read {len(messages)} emails: {len(rows)} about applications, {added} new applications, {updated} status updates.")


def cmd_ui(args):
    from .ui.server import serve

    serve(port=args.port, open_browser=not args.no_open)


def cmd_logs(args):
    import datetime as dt

    logdir = paths.HOME / "logs"
    day = args.date or dt.date.today().isoformat()
    path = logdir / f"{day}.log"
    if not path.exists():
        sys.exit(f"No log for {day} in {logdir}.")
    lines = path.read_text(encoding="utf-8").splitlines()
    print("\n".join(lines[-args.lines:]))
    print(f"\n({path})")


def build_parser():
    ap = argparse.ArgumentParser(prog="jobbot", description=textwrap.dedent(__doc__),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def with_llm(sp):
        sp.add_argument("--llm", choices=("ollama", "none"), default="ollama")
        sp.add_argument("--model", default=llm_mod.DEFAULT_MODEL)

    sp = sub.add_parser("init", help="create profile.yaml in the repo folder (git-ignored)")
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
    sp.add_argument("--no-careers-pages", action="store_true",
                    help="skip companies read from their own careers page in headless Chrome (faster)")
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
    sp.add_argument("jobs", nargs="*", help="job numbers or ranges from `jobbot jobs` (12, 12-20, 12,15), or posting URLs")
    sp.add_argument("--top", type=int, help="apply to the N best-ranked roles, one after another")
    sp.add_argument("--exclude", default="", help="comma-separated companies to skip (adds to "
                                                  "preferences.exclude_companies), e.g. \"Amazon,Google\"")
    sp.add_argument("--all", action="store_true", help="apply to every tracked role you have not applied to or dismissed")
    sp.add_argument("--min-fit", type=int, help="only roles whose fit score is at least this")
    sp.add_argument("-y", "--yes", action="store_true", help="skip the confirmation before a batch of more than 3 roles")
    sp.add_argument("--resume", help="resume key from your profile (default: the ranked best match)")
    sp.add_argument("--dry-run", action="store_true", help="fill forms but never submit or record")
    sp.add_argument("--no-upload", action="store_true", help="do not attach a resume")
    sp.add_argument("--force", action="store_true", help="reopen roles already marked applied")
    sp.add_argument("--no-auto-next", action="store_true",
                    help="stop after every page instead of moving on when the check passes")
    sp.set_defaults(fn=cmd_apply)

    sp = sub.add_parser("ui", help="open the local dashboard in your browser")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--no-open", action="store_true", help="do not open a browser tab")
    sp.set_defaults(fn=cmd_ui)

    sp = sub.add_parser("logs", help="show what apply filled, corrected, and checked")
    sp.add_argument("--date", help="YYYY-MM-DD (default: today)")
    sp.add_argument("-n", "--lines", type=int, default=80)
    sp.set_defaults(fn=cmd_logs)

    sp = sub.add_parser("dismiss", help="hide roles you do not want")
    sp.add_argument("jobs", nargs="+")
    sp.set_defaults(fn=cmd_dismiss)

    sp = sub.add_parser("track", help="application tracker",
                        description="actions: list (default), add, update <id>, show <id>, stats, export [file], import <csv>, "
                                    "import-gmail <json>, sync-gmail")
    sp.add_argument("action", nargs="?", choices=("list", "add", "update", "show", "stats", "export", "import", "import-gmail", "sync-gmail"))
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
    sp.add_argument("--days", type=int, default=60, help="sync-gmail: how far back to read (default 60)")
    sp.add_argument("--query", help="sync-gmail: Gmail search query instead of the built-in application-email query")
    sp.add_argument("--all-mail", action="store_true",
                    help="sync-gmail: read every email in the period (metadata only); the importer keeps application emails")
    sp.add_argument("--limit", type=int, default=2000, help="sync-gmail: maximum emails to read")
    sp.set_defaults(fn=cmd_track)

    sp = sub.add_parser("gmail", help="connect Gmail (read-only) to import your applications",
                        description="Sign in with Google in your browser; jobbot gets read-only access and never sees "
                                    "your password. Needs a one-time OAuth client: see jobbot/gmail.py or the README.")
    sp.add_argument("action", choices=("login", "logout", "status"))
    sp.add_argument("--client", help="path to the Google OAuth client JSON (saved to ~/.jobbot/gmail_client.json)")
    sp.set_defaults(fn=cmd_gmail)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
