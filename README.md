# Target-Company SDE Scanner

[![tests](https://github.com/srbmaury/target-company-sde-scanner/actions/workflows/tests.yml/badge.svg)](https://github.com/srbmaury/target-company-sde-scanner/actions/workflows/tests.yml)

**Find, rank, apply to, and track software-engineering roles: free, local, and private.**

Built for candidates with roughly 1–3 years of experience. It reads open roles from 300+ target
companies, ranks them against each of your resumes, fills applications in Chrome while you watch,
and keeps every application in one tracker. Automatic applications require Ollama approval before each Next and Submit; manual mode is available.

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

| | What jobbot does |
| --- | --- |
| **Find** | Reads open roles from 300+ companies' job boards and careers sites, filtered to your locations and experience |
| **Rank** | Scores each role 0–100 against every resume variant with a local model (Ollama), and picks the resume to send |
| **Apply** | Fills forms in its own Chrome window, re-checks every value, moves through multi-page forms, and requires Ollama approval before every Next and Submit; runs without prompts and skips blocked applications |
| **Learn** | Remembers your answers to new questions and reuses them at other companies |
| **Track** | Records every application, imports the rest from Gmail, and never reopens a role you applied to |
| **Dashboard** | Does all of the above from a local web page: `./jobbot.sh ui` |

---

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
[Dashboard](docs/dashboard.md)).

Other ways to choose which roles `apply` works through:

```bash
./jobbot.sh apply 12 15              # specific roles by number
./jobbot.sh apply 12-20              # a range of numbers (also 12..20 or 12,15,18)
./jobbot.sh apply --top 10           # the 10 best-ranked roles
./jobbot.sh apply --all --min-fit 80 # every role you haven't applied to, with fit 80 or higher
./jobbot.sh apply --all              # every role you haven't applied to, best fit first
./jobbot.sh apply --top 10 --exclude "Amazon,Google"   # the 10 best roles at other companies
```

`apply` always skips companies in `preferences.exclude_companies`; `--exclude` adds more for one run.

More: [finding and ranking jobs](docs/finding-jobs.md) · [how `apply` works](docs/apply.md) ·
[unattended mode](docs/apply.md#unattended-mode) · [dashboard](docs/dashboard.md)

---

## Documentation

| | |
| --- | --- |
| [Finding and ranking jobs](docs/finding-jobs.md) | Sources, filters, ranking, choosing roles |
| [How `apply` works](docs/apply.md) | Filling, checks, final step, unattended mode, dry run |
| [Dashboard](docs/dashboard.md) | Every tab and applying from the browser |
| [Your profile](docs/profile.md) | `profile.yaml` reference, learned answers, rules |
| [Tracking applications](docs/tracking.md) | Tracker, duplicates, Gmail sync setup |
| [Command reference](docs/commands.md) | Every command and option |
| [Privacy and safety](docs/privacy.md) | What stays local, what jobbot never does |
| [Troubleshooting](docs/troubleshooting.md) | Common problems and fixes |
| [AI-assistant skill](docs/skill.md) | Using the repo as a Codex / Claude Code skill |

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
| `docs/` | Documentation pages |
| `tests/` | Unit tests: `python3 -m unittest discover -s tests` |

---

## Contributing

Contributions are welcome, especially registry fixes for companies whose job boards moved. Read
[CONTRIBUTING.md](CONTRIBUTING.md) first. It covers verifying registry entries, testing form
changes with `--dry-run`, and keeping jobbot's safety rules intact.

## License

[MIT](LICENSE) © 2026 Saurabh Maurya
