# Target-Company SDE Scanner

Find, rank, apply to, and track software-engineering roles for candidates with roughly 1–3 years
of experience, across 300+ target companies. Free, local, and private.

It comes in two forms:

- **jobbot**, a command-line tool. It scans company job boards, ranks roles against your resumes
  with a local model, fills applications in Chrome while you watch, and tracks every application.
- **An AI-assistant skill** (`SKILL.md`) for Codex or Claude Code. It runs the same search
  conversationally and can tailor a resume to each role.

```text
$ ./jobbot.sh jobs --why
   # fit  company              role                                         location             exp            resume
   2  85  Abnormal Security    Software Engineer 2 - Abnormal Data Platform Hybrid - Bangalore   3+ yrs stated  backend_cloud
          Strong backend and cloud experience aligns well with the role, but lacks data-pipeline work.
   5  75  Anyscale             Software Engineer, Ray Core                  Bengaluru, Karnataka 2+ yrs stated  backend_platform
```

---

## Contents

- [Quick start](#quick-start)
- [Daily workflow](#daily-workflow)
- [How `apply` works](#how-apply-works)
- [Dashboard](#dashboard)
- [Your profile](#your-profile)
- [Tracking applications](#tracking-applications)
- [Command reference](#command-reference)
- [Privacy and safety](#privacy-and-safety)
- [Troubleshooting](#troubleshooting)
- [Using it as an AI-assistant skill](#using-it-as-an-ai-assistant-skill)
- [Running only the scanner](#running-only-the-scanner)
- [Repository layout](#repository-layout)
- [Contributing](#contributing)

---

## Quick start

**You need:** Python 3.10+ and Google Chrome. The local model needs [Ollama](https://ollama.com);
it is optional, and setup commands below assume macOS with Homebrew.

```bash
git clone https://github.com/srbmaury/target-company-sde-scanner.git
cd target-company-sde-scanner
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Optional: local model for ranking and drafting answers (about 5 GB download)
brew install ollama && brew services start ollama && ollama pull qwen2.5:7b

./jobbot.sh init       # creates profile.yaml (git-ignored) from the template
# edit profile.yaml: your details, resume paths, preferences
./jobbot.sh doctor     # checks profile, resumes, browser, and Ollama
```

`doctor` should end with every line ticked:

```text
✓ profile: /Users/you/target-company-sde-scanner/profile.yaml
✓ resumes found: backend_platform, fullstack_product, ai_engineer
✓ playwright installed
✓ ollama running; model qwen2.5:7b: ready
✓ tracker: /Users/you/.jobbot/applications.db (0 applications)
```

To run `jobbot` from any folder:

```bash
ln -s "$PWD/jobbot.sh" /opt/homebrew/bin/jobbot
```

---

## Daily workflow

```bash
./jobbot.sh scan          # 1. sweep 300+ companies' job boards and careers sites (a few minutes)
./jobbot.sh rank          # 2. score new roles against each of your resumes
./jobbot.sh jobs --why    # 3. best fits first, with the reason and the resume to use
./jobbot.sh apply --top 5 # 4. apply to the 5 best-ranked roles, one after another
./jobbot.sh track         # 5. see every application and its status
```

Prefer clicking? `./jobbot.sh ui` does all of this from a browser page, including applying (see
[Dashboard](#dashboard)).

Other ways to choose which roles `apply` works through:

```bash
./jobbot.sh apply 12 15              # specific roles by number
./jobbot.sh apply 12-20              # a range of numbers (also 12..20 or 12,15,18)
./jobbot.sh apply --top 10           # the 10 best-ranked roles
./jobbot.sh apply --all --min-fit 80 # every role you haven't applied to, with fit 80 or higher
./jobbot.sh apply --all              # every role you haven't applied to, best fit first
```

**`scan`** reads each company's jobs from where its careers site gets them:
- public job-board APIs: Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, Keka,
  Freshteam, Eightfold, and Oracle Recruiting Cloud
- the Amazon, Google, Apple, Microsoft, and Atlassian careers sites' own job feeds
- for companies with none of these, the careers page itself, opened in headless Chrome (links and
  the job lists the page loads). This is less precise, and `--no-careers-pages` skips it.

About half of the companies in `target-companies.md` are covered this way. The rest (for example
Flipkart, Walmart, Intuit, SAP, Zomato) use sites jobbot can't read reliably yet; the AI-assistant
skill still finds those through web search.

It keeps engineering roles in your locations and reads each posting's stated experience
requirement (or a range in the title, such as "(1 to 4 Years)"). It drops roles that ask for more years than your `max_yoe`, roles
at excluded companies, and roles you have already applied to. New roles are stored in the tracker.

**`rank`** scores each new role from 0 to 100 against every resume variant and picks the best
resume for it. With Ollama this takes about 6–7 seconds per role on an Apple-silicon Mac; without
it, jobbot falls back to keyword matching. Treat scores as a sort order rather than a verdict: a
7B model sometimes misses a skill your resume does list.

**`jobs`** lists roles you have not applied to, best fit first. Add `--why` for the reason,
`--urls` for links, and `dismiss <n>` to hide roles you don't want.

**`apply`** takes job numbers or ranges from `jobs`, a posting URL, `--top N` for the N best-ranked
roles, or `--all`. It skips roles you have already applied to or dismissed. Before a batch of more
than 3 roles it lists them and asks you to confirm (`-y` skips this). See the next section.

---

## How `apply` works

For each job you pass, one after another:

1. **Opens the posting** in a separate Chrome window with its own profile, so it never touches your
   everyday browser. Site sign-ins you make there are remembered for next time.
2. **Starts the application**, for example by clicking Apply or "Autofill with Resume" on Workday,
   and attaches the resume chosen by `rank`.
3. **Fills every field it can** from your profile: name, contact details, links, current company
   and title, CTC, notice period, education, work authorization, sponsorship, EEO answers, and
   your own fixed answers.
4. **Asks you only when it has to**, in the terminal or, when you apply from the dashboard, in its
   Apply tab:
   - questions matching your `always_ask` list, such as signatures and legal or sanctions questions
   - required questions it has no answer for. With Ollama it drafts free-text answers from your
     profile and resume. By default it uses them without asking (`automation.auto_accept_drafts`);
     every draft is shown in the page report and the logs.
   - consent and privacy boxes, once per application, unless `automation.auto_consent` is on
   - email verification codes, once, spread across Workday's separate code boxes
5. **Reviews the page until it is stable.** Each round it:
   - reads back every value it set, including dropdowns, radios, and Workday widgets
   - corrects values the site pre-filled wrongly (for example Workday's resume autofill), using only
     your profile, rules, and remembered answers, never a model guess
   - looks for empty required fields, the site's own validation errors (including Workday's
     "Errors Found"), and CAPTCHAs

   It repeats until a whole round changes nothing and every check passes (up to 5 rounds). If
   problems remain that it can't fix, it shows you exactly what is wrong.
6. **Moves through multi-page forms by itself**: when a page passes the check, it clicks
   Next / Save and Continue. Use `--no-auto-next` to stop after every page.
7. **Stops on the final page.** jobbot never submits on its own. You review the browser, then press:

   | Key | Action |
   | --- | --- |
   | `s` | jobbot clicks Submit, waits for the confirmation text, and records the application |
   | `r` | re-fill the page (after you fix something) |
   | `d` | you submitted it yourself; jobbot records it |
   | `q` | quit without submitting; nothing is recorded |

   In the dashboard the same choices are buttons: **Submit application**, **Re-fill this page**,
   **I submitted it myself**, and **Quit without submitting**.

**Supported sites**

| Applicant-tracking system | Example employers | Support |
| --- | --- | --- |
| Greenhouse | MongoDB, Stripe, Datadog, Celonis | Full |
| Lever | Meesho, CRED, Zeta, HighLevel | Full |
| Ashby | Snowflake, Confluent, Anyscale, OpenAI | Full |
| Workday | Adobe, NVIDIA, Visa, Cisco, Wells Fargo | Multi-page; many employers require you to sign in first |
| SmartRecruiters | ServiceNow | Multi-page, best effort |
| Anything else | | Opens the page for you to fill; jobbot still tracks the result |

**What happened?** `./jobbot.sh logs` shows, page by page and round by round, what jobbot filled,
what it corrected (with the old value), and what the check found. Logs are in `~/.jobbot/logs/`.

**Useful flags:** `--dry-run` (fill and check, but never submit or record), `--resume ai_engineer`
(override the ranked resume), `--llm none` (skip Ollama), `--no-upload`, `--force` (reopen a role
already marked applied).

> Try your first application on any new site with `--dry-run`.

---

## Dashboard

```bash
./jobbot.sh ui
```

Opens a local dashboard in your browser (`http://127.0.0.1:8765`). It uses the same tracker,
profile and logs as the commands.

| Tab | What you can do |
| --- | --- |
| **Jobs** | Ranked roles with fit scores and reasons, filters (text, minimum fit, already applied, dismissed), links to postings, dismiss/restore. Tick roles (or **Select all shown**, which follows your filters and leaves out applied and dismissed roles) and click **Apply to selected** (or **Dry run**) |
| **Apply** | The running application batch: a live activity feed (what was filled, corrected and checked on each page), the queue, and any question jobbot needs you to answer |
| **Applications** | Every application with status pills and history; click one to change its status or notes; add applications made elsewhere |
| **Actions** | Run Scan, Rank, and Gmail sync in the background and watch their output; connect Gmail |

**Refresh jobs** (top of the Jobs tab) runs `scan` and then `rank`, shows progress beside the
button, and reloads the list when it finishes.
| **Logs** | What `apply` filled, corrected and checked, page by page, with a filter |
| **Profile** | Edit `profile.yaml`, including learned answers. Invalid YAML is refused, and a backup is kept |

### Applying from the dashboard

Tick roles in **Jobs**, then click **Apply to selected**. jobbot opens its own Chrome window, as
`apply` does, and the **Apply** tab shows its progress. When it needs you (an unanswered question,
a verification code, a sign-in or CAPTCHA, or the final **Submit application**), the question
appears at the top of the Apply tab, a red dot appears on the tab, and the browser tab title shows
"● jobbot needs you". Nothing is submitted until you click Submit. **Dry run** fills and checks
every page but never submits. **Stop after this step** ends the batch without submitting the
current application. Only one run happens at a time. Skipping rules match `apply`: already-applied
and dismissed roles are skipped, and for possible matches you are asked first.

The dashboard listens only on `127.0.0.1`, and each run generates a random access token that is embedded in the page, so other
websites in your browser can't call it. Stop it with Ctrl+C.

---

## Your profile

`profile.yaml` in the repository folder holds everything jobbot answers with. It is created from
[`profile.example.yaml`](profile.example.yaml). It is **git-ignored**, because it contains your
contact details and CTC, so it is never committed. The main sections:

| Section | What it holds |
| --- | --- |
| `personal` | name, email, phone, country code and phone type, city, state, address, languages besides English |
| `links` | LinkedIn (use the `www.` form), GitHub, website |
| `work` | current company and title, start month, years of experience, past employers, notice period, current and expected CTC, reason for change, outside business activities |
| `education` | school, degree, field, GPA, years |
| `eligibility` | work authorization, sponsorship, relocation, background check, military service |
| `eeo` | gender, ethnicity, veteran and disability answers (`Decline` picks the decline option) |
| `preferences` | location regex, `max_yoe`, excluded companies, "how did you hear about us", preferred work locations (for location dropdowns) |
| `resumes` | each resume variant: a key, the PDF path, and a short focus hint for ranking |
| `answers` | your fixed answers: a regex matched against the question, and the answer to give |
| `always_ask` | regexes for questions jobbot must always ask you about |
| `automation` | `auto_accept_drafts` (use model drafts for free-text questions without asking; on by default), `auto_consent` (tick consent boxes without asking; off by default) |
| `learned_answers` | answers you gave during applications, which jobbot fills in itself (see below) |

**jobbot learns as you go.** When you answer a question, in the terminal or the dashboard, jobbot saves it under
`learned_answers` and reuses it for the same or a very similar question at any company, so you're
asked once. Answers that name the employer ("Why do you want to join Acme?") are not saved. You
can edit or delete entries in the file.

**Teaching jobbot new answers by hand.** If a question keeps coming up, add a rule under `answers`. These
rules take priority over everything else, including `always_ask`:

```yaml
answers:
  - match: "years of experience (with|in) java"
    answer: "2"
  - match: "\\breferr(ed|al)\\b"       # \b avoids matching "Preferred Start Date"
    answer: "No"
```

---

## Tracking applications

Every application jobbot submits is recorded automatically. Add the ones you make elsewhere so the
tracker stays complete:

```bash
./jobbot.sh track                                    # all applications, newest first, with totals
./jobbot.sh track --status interview                 # filter by status (or --company)
./jobbot.sh track add --company Acme --title "SDE II" --url https://... --status applied
./jobbot.sh track update 42 --status interview --note "system design on Friday"
./jobbot.sh track show 42                            # details and full status history
./jobbot.sh track stats                              # counts, response rate, interview rate
./jobbot.sh track export applications.csv            # open in a spreadsheet
./jobbot.sh track import old.csv                     # columns: company,title,status,applied_on,url,notes
./jobbot.sh track sync-gmail                         # import applications from Gmail (see below)
./jobbot.sh track import-gmail emails.json           # or build rows from an exported JSON of emails
```

Statuses: `shortlisted`, `applied`, `assessment`, `interview`, `offer`, `rejected`, `withdrawn`,
`ghosted`.

**How jobbot knows you already applied.** Applications imported from email often have no job link,
so jobbot also matches on company and title. It ignores suffixes ("Sarvam AI" = "Sarvam"), job IDs,
punctuation and Roman numerals ("Software Engineer 2" = "Software Engineer II"), but levels must
agree ("Software Engineer II" ≠ "Software Engineer").

- **Already applied** (same link, or same company and title): left out of `jobs`, and skipped by
  `apply` unless you pass `--force`.
- **Possibly applied**: shown as `[applied?]`, and `apply` asks before opening it. This covers:
  - the email didn't name the role
  - the same title was posted after you applied (big employers reuse titles for new openings)

### Importing applications from Gmail

`track sync-gmail` reads your application emails and adds them to the tracker:
- acknowledgements become `applied`
- rejections become `rejected`
- assessment and interview invitations become `assessment` / `interview`

Run it after applying through job boards, so `apply` never reopens a role you already applied to.

**Connect once.** You sign in on Google's own page in your browser. jobbot gets **read-only**
access (`gmail.readonly`) and never sees your Google password. Google requires every app that reads
Gmail to have its own OAuth client, so this takes a few minutes once:

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project and enable the
   **Gmail API**.
2. Under **Google Auth Platform**, set up branding (app name "jobbot", your email). Under
   **Audience**, choose External and add your own Gmail address as a test user.
3. Under **Clients**, create a client of type **Desktop app** and download its JSON.
4. Connect:
   ```bash
   ./jobbot.sh gmail login --client ~/Downloads/client_secret_....json
   ```
   Google shows an "unverified app" warning because the app is yours and unpublished. Choose
   Continue, then allow read-only access.

Then sync whenever you like:

```bash
./jobbot.sh track sync-gmail                  # application emails from the last 60 days
./jobbot.sh track sync-gmail --days 180       # look further back
./jobbot.sh track sync-gmail --all-mail       # read every email in the period, keep application emails
./jobbot.sh gmail status                      # which account is connected
./jobbot.sh gmail logout                      # revoke access and delete the token
```

What jobbot reads: sender, subject, a short preview, and the date of each message. It never
downloads email bodies or attachments, and never sends, labels or deletes anything. The token is
stored in `~/.jobbot/gmail_token.json`, readable only by you. If Gmail isn't connected yet,
`sync-gmail` offers to connect it.

The matching is heuristic, so review the result with `track` and fix rows with `track update`.
`import-gmail <file.json>` does the same from an exported list of messages (sender, subject,
snippet, date).

---

## Command reference

| Command | What it does |
| --- | --- |
| `init [--force]` | Create `profile.yaml` (git-ignored) from the template |
| `doctor` | Check profile, resume files, Playwright, Ollama, and the tracker |
| `scan [--companies A,B] [--exclude C] [--locations REGEX] [--max-yoe N] [--show-all] [--no-careers-pages]` | Find matching roles and store new ones |
| `rank [--limit N] [--rerank] [--llm none] [--model NAME]` | Score unranked roles against your resumes |
| `jobs [--why] [--urls] [--limit N] [--include-applied]` | List tracked roles, best fit first |
| `apply <n, x-y or URL>... [--top N] [--all] [--min-fit N] [-y] [--dry-run] [--resume KEY] [--no-auto-next] [--no-upload] [--force] [--llm none]` | Fill applications in Chrome |
| `dismiss <n>...` | Hide roles you are not interested in |
| `logs [--date YYYY-MM-DD] [-n N]` | Show what `apply` filled, corrected and checked |
| `ui [--port N] [--no-open]` | Open the local dashboard |
| `track [list\|add\|update\|show\|stats\|export\|import\|import-gmail\|sync-gmail]` | Manage the application tracker |
| `gmail login [--client FILE] \| logout \| status` | Connect Gmail read-only for `track sync-gmail` |

Environment variables: `JOBBOT_PROFILE` (default `./profile.yaml`), `JOBBOT_HOME` (default
`~/.jobbot`), `JOBBOT_MODEL` (default `qwen2.5:7b`), and `OLLAMA_HOST`.

---

## Privacy and safety

- **Everything runs on your machine.** Your profile (`profile.yaml`, git-ignored) lives in the
  repository folder. The tracker database (`applications.db`) and browser profile live in `~/.jobbot/`. The only network traffic is to the job boards themselves,
  to Google's Gmail API if you connect Gmail, and to Ollama on localhost.
- **No automatic submits.** The final Submit always needs your keypress, or your click in the dashboard.
- **No passwords.** jobbot never reads, stores, or types passwords, and skips password fields.
  Gmail uses Google's own sign-in page with read-only access, and you can revoke it with
  `jobbot gmail logout`.
  When a site needs you to sign in, it waits for you to do it in the browser.
- **No CAPTCHA solving.** CAPTCHAs are left to you.
- **No made-up answers.** Answers come from your profile, your resumes, or you. Model drafts are
  grounded in those facts. They are used without asking only if `auto_accept_drafts` is on (the
  default), and every one is listed in the page report and the logs; review them before you submit.
- **Hidden trap fields are skipped.** Some forms include invisible fields that only bots fill in;
  jobbot leaves them empty so the application isn't flagged as automated.

Many job sites' terms discourage automated applications. Use jobbot as an assistant for
applications you would make anyway, not to send them in bulk.

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `profile is already in use` | A jobbot Chrome window is still open from an earlier run. Quit that run (`q`, or **Stop** in the dashboard) or close the window. |
| Workday stops at "Create Account/Sign In" | Expected for many employers. Sign in or create the account in the jobbot window, then press Enter (or click **Done, continue** in the dashboard). |
| Sign-in or account creation is refused in the jobbot window (Microsoft, Google) | Update jobbot: its Chrome no longer identifies itself as automated, which those sign-in pages reject. If a site still refuses, use its email-link or one-time-code option, or sign in once in that window and it is remembered. |
| `Ollama is not running` | `brew services start ollama`, or pass `--llm none` |
| A question gets a wrong or missing answer | Add a rule under `answers:` in your profile (see [Your profile](#your-profile)) |
| The scanner errors on one company | That board moved or was retired. The rest of the scan continues; see [Contributing](CONTRIBUTING.md) to fix the registry entry. |
| `bad interpreter` after moving the folder | Recreate the virtualenv: `rm -rf .venv && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` |

---

## Using it as an AI-assistant skill

Install this folder as a skill in Codex or Claude Code and ask, for example:

```text
Scan my target companies for India-based SDE-2 roles.
Tailor my resume for the Stripe and Datadog roles you found.
```

The skill runs the API scan first, then falls back to career sites and job boards for companies
outside the registry. It verifies that each role is live before reporting it. When asked, it
creates one tailored, one-page PDF resume per role. Tailoring reorders and highlights your real
experience; it never invents skills, metrics, or credentials. If jobbot is set up, the skill uses
`jobbot scan`, `rank`, and `track` so its results and your tracker stay in sync. Full instructions
are in [`SKILL.md`](SKILL.md).

---

## Running only the scanner

The scanner needs only Python 3, with no dependencies (companies read from their careers page also
need Playwright and Chrome; without them they are reported as skipped, or pass `--no-careers-pages`):

```bash
python3 scripts/ats_scan.py --companies "Stripe,MongoDB,Adobe,ServiceNow"
python3 scripts/ats_scan.py --all --exclude "Salesforce" --max-yoe 3
python3 scripts/ats_scan.py --all --locations "hyderabad|bengaluru|bangalore|remote" --json
```

It prints a Markdown table of candidate roles with the stated experience, plus per-company coverage.
Rows are candidates: open each link before treating it as a live opening.

---

## Repository layout

| Path | Purpose |
| --- | --- |
| `jobbot/` | The command-line tool: `cli.py`, `scan.py`, `rank.py`, `llm.py` (Ollama), `answers.py` and `memory.py` (answering questions, learned answers), `tracker.py`, `gmail.py` and `mailimport.py` |
| `jobbot/apply/` | Browser filling: `engine.py` (pages, review rounds, Workday), `fields.py`, `verify.py` (readback and checks), `runner.py` (choosing and working through roles) |
| `jobbot/ui/` | The dashboard: `server.py` (local API), `bridge.py` (runs `apply` for the page), `static/` |
| `jobbot.sh` | Launcher that uses the project virtualenv |
| `profile.example.yaml` | Template for your private profile |
| `references/ats-registry.json` | Where each of 300+ companies' jobs are read from (job-board IDs, feeds, careers pages) |
| `target-companies.md` | Tiered company list and official career-site entry points |
| `references/job-platforms.md` | Supplemental job boards and how to treat each |
| `scripts/ats_scan.py` | Standalone scanner command |
| `SKILL.md` | Instructions for AI assistants |
| `tests/` | Unit tests: `python3 -m unittest discover -s tests` |

---

## Contributing

Contributions are welcome, especially registry fixes for companies whose job boards moved. Read
[CONTRIBUTING.md](CONTRIBUTING.md) first. It covers verifying registry entries, testing form
changes with `--dry-run`, and keeping jobbot's safety rules intact.

## License

[MIT](LICENSE) © 2026 Saurabh Maurya
