# Target-Company SDE Scanner

Find, rank, apply to, and track software-engineering roles for candidates with roughly 1–3 years
of experience, across 220+ target companies. Free, local, and private.

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

./jobbot.sh init       # creates ~/.jobbot/profile.yaml from the template
# edit ~/.jobbot/profile.yaml: your details, resume paths, preferences
./jobbot.sh doctor     # checks profile, resumes, browser, and Ollama
```

`doctor` should end with every line ticked:

```text
✓ profile: /Users/you/.jobbot/profile.yaml
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
./jobbot.sh scan          # 1. sweep 220+ company job boards (about 2 minutes)
./jobbot.sh rank          # 2. score new roles against each of your resumes
./jobbot.sh jobs --why    # 3. best fits first, with the reason and the resume to use
./jobbot.sh apply 12 15   # 4. apply to the roles numbered 12 and 15
./jobbot.sh track         # 5. see every application and its status
```

**`scan`** queries each company's public job-board API (Greenhouse, Lever, Ashby, Workday,
SmartRecruiters, Microsoft). It keeps engineering roles in your locations and reads each posting's
stated experience requirement. It drops roles that ask for more years than your `max_yoe`, roles
at excluded companies, and roles you have already applied to. New roles are stored in the tracker.

**`rank`** scores each new role from 0 to 100 against every resume variant and picks the best
resume for it. With Ollama this takes about 6–7 seconds per role on an Apple-silicon Mac; without
it, jobbot falls back to keyword matching. Treat scores as a sort order rather than a verdict: a
7B model sometimes misses a skill your resume does list.

**`jobs`** lists roles you have not applied to, best fit first. Add `--why` for the reason,
`--urls` for links, and `dismiss <n>` to hide roles you don't want.

**`apply`** takes job numbers from `jobs`, a posting URL, or `--top N` for the N best-ranked roles.
See the next section.

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
4. **Asks you in the terminal only when it has to**:
   - questions matching your `always_ask` list, such as signatures and legal or sanctions questions
   - required questions it has no answer for. With Ollama it drafts free-text answers from your
     profile and resume for you to accept or edit.
   - consent and privacy boxes, once per application
5. **Checks the page** before moving on:
   - reads back every value it set, including dropdowns, radios, and Workday widgets
   - looks for empty required fields
   - looks for the site's own validation errors
   - looks for CAPTCHAs

   If anything is off, it re-fills once and checks again, then shows you exactly what is still wrong.
6. **Moves through multi-page forms by itself**: when a page passes the check, it clicks
   Next / Save and Continue. Use `--no-auto-next` to stop after every page.
7. **Stops on the final page.** jobbot never submits on its own. You review the browser, then press:

   | Key | Action |
   | --- | --- |
   | `s` | jobbot clicks Submit, waits for the confirmation text, and records the application |
   | `r` | re-fill the page (after you fix something) |
   | `d` | you submitted it yourself; jobbot records it |
   | `q` | quit without submitting; nothing is recorded |

**Supported sites**

| Applicant-tracking system | Example employers | Support |
| --- | --- | --- |
| Greenhouse | MongoDB, Stripe, Datadog, Celonis | Full |
| Lever | Meesho, CRED, Zeta, HighLevel | Full |
| Ashby | Snowflake, Confluent, Anyscale, OpenAI | Full |
| Workday | Adobe, NVIDIA, Visa, Cisco, Wells Fargo | Multi-page; many employers require you to sign in first |
| SmartRecruiters | ServiceNow | Multi-page, best effort |
| Anything else | | Opens the page for you to fill; jobbot still tracks the result |

**Useful flags:** `--dry-run` (fill and check, but never submit or record), `--resume ai_engineer`
(override the ranked resume), `--llm none` (skip Ollama), `--no-upload`, `--force` (reopen a role
already marked applied).

> Try your first application on any new site with `--dry-run`.

---

## Your profile

`~/.jobbot/profile.yaml` holds everything jobbot answers with. It is created from
[`profile.example.yaml`](profile.example.yaml) and stays outside the repository. The main sections:

| Section | What it holds |
| --- | --- |
| `personal` | name, email, phone and country code, city, state, address |
| `links` | LinkedIn (use the `www.` form), GitHub, website |
| `work` | current company and title, start month, years of experience, past employers, notice period, current and expected CTC, reason for change |
| `education` | school, degree, field, GPA, years |
| `eligibility` | work authorization, sponsorship, relocation, background check |
| `eeo` | gender, ethnicity, veteran and disability answers (`Decline` picks the decline option) |
| `preferences` | location regex, `max_yoe`, excluded companies, "how did you hear about us" |
| `resumes` | each resume variant: a key, the PDF path, and a short focus hint for ranking |
| `answers` | your fixed answers: a regex matched against the question, and the answer to give |
| `always_ask` | regexes for questions jobbot must always ask you about |

**Teaching jobbot new answers.** If a question keeps coming up, add a rule under `answers`. These
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
./jobbot.sh track import-gmail emails.json           # build rows from application emails
```

Statuses: `shortlisted`, `applied`, `assessment`, `interview`, `offer`, `rejected`, `withdrawn`,
`ghosted`.

`import-gmail` reads a JSON export of messages (sender, subject, snippet, date). It treats
acknowledgements as `applied`, rejections as `rejected`, and assessment or interview invitations as
`assessment` / `interview`. The parsing is heuristic, so review the result with `track` and fix
rows with `track update`.

---

## Command reference

| Command | What it does |
| --- | --- |
| `init [--force]` | Create `~/.jobbot/profile.yaml` from the template |
| `doctor` | Check profile, resume files, Playwright, Ollama, and the tracker |
| `scan [--companies A,B] [--exclude C] [--locations REGEX] [--max-yoe N] [--show-all]` | Find matching roles and store new ones |
| `rank [--limit N] [--rerank] [--llm none] [--model NAME]` | Score unranked roles against your resumes |
| `jobs [--why] [--urls] [--limit N] [--include-applied]` | List tracked roles, best fit first |
| `apply <n or URL>... [--top N] [--dry-run] [--resume KEY] [--no-auto-next] [--no-upload] [--force] [--llm none]` | Fill applications in Chrome |
| `dismiss <n>...` | Hide roles you are not interested in |
| `track [list\|add\|update\|show\|stats\|export\|import\|import-gmail]` | Manage the application tracker |

Environment variables: `JOBBOT_HOME` (default `~/.jobbot`), `JOBBOT_MODEL` (default `qwen2.5:7b`),
and `OLLAMA_HOST`.

---

## Privacy and safety

- **Everything runs on your machine.** Your profile, tracker database (`applications.db`), and
  browser profile live in `~/.jobbot/`. The only network traffic is to the job boards themselves
  and, if enabled, to Ollama on localhost.
- **No automatic submits.** The final Submit always needs your keypress.
- **No passwords.** jobbot never reads, stores, or types passwords, and skips password fields.
  When a site needs you to sign in, it waits for you to do it in the browser.
- **No CAPTCHA solving.** CAPTCHAs are left to you.
- **No made-up answers.** Answers come from your profile, your resumes, or you. Model drafts are
  grounded in those facts and shown to you before use.
- **Hidden trap fields are skipped.** Some forms include invisible fields that only bots fill in;
  jobbot leaves them empty so the application isn't flagged as automated.

Many job sites' terms discourage automated applications. Use jobbot as an assistant for
applications you would make anyway, not to send them in bulk.

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `profile is already in use` | A jobbot Chrome window is still open from an earlier run. Quit that run (`q`) or close the window. |
| Workday stops at "Create Account/Sign In" | Expected for many employers. Sign in or create the account in the jobbot window, then press Enter. |
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

The scanner needs only Python 3, with no dependencies:

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
| `jobbot/` | The command-line tool: `scan.py`, `rank.py`, `llm.py`, `answers.py`, `tracker.py`, `mailimport.py`, and `apply/` (browser filling and page checks) |
| `jobbot.sh` | Launcher that uses the project virtualenv |
| `profile.example.yaml` | Template for your private profile |
| `references/ats-registry.json` | Verified job-board API identifiers for 220+ companies |
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

No license has been selected yet. Add one before distributing the project or accepting
contributions under specific reuse terms.
