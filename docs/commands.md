# Command reference

| Command | What it does |
| --- | --- |
| `init [--force]` | Create `profile.yaml` (git-ignored) from the template |
| `doctor` | Check profile, resume files, Playwright, Ollama, and the tracker |
| `scan [--companies A,B] [--exclude C] [--locations REGEX] [--max-yoe N] [--show-all] [--no-careers-pages]` | Find matching roles and store new ones |
| `rank [--limit N] [--rerank] [--llm none] [--model NAME]` | Score unranked roles against your resumes |
| `jobs [--why] [--urls] [--limit N] [--include-applied]` | List tracked roles, best fit first |
| `apply <n, x-y or URL>... [--top N] [--all] [--min-fit N] [--exclude A,B] [-y] [--dry-run] [--resume KEY] [--no-auto-next] [--no-upload] [--force] [--llm none]` | Fill applications in Chrome |
| `dismiss <n>...` | Hide roles you are not interested in |
| `logs [--date YYYY-MM-DD] [-n N]` | Show what `apply` filled, corrected and checked |
| `answers [ok N \| fix N "text"] [--all]` | Review the local model's answers; mark them right or correct them |
| `ui [--port N] [--no-open]` | Open the local dashboard |
| `track [list\|add\|update\|show\|stats\|export\|import\|import-gmail\|sync-gmail]` | Manage the application tracker |
| `gmail login [--client FILE] \| logout \| status` | Connect Gmail (job-hunting mailbox) for `track sync-gmail`, codes and links |
| `password [--delete]` | Store the password jobbot uses to sign in to, or sign up on, job sites (macOS Keychain; it prompts for it) |
| `resumes` | Read every resume now and list the skills each shows (questions about tools none name are answered 0 / No) |

Every command explains its options with `--help`, for example `./jobbot.sh apply --help`.

Environment variables: `JOBBOT_PROFILE` (default `./profile.yaml`), `JOBBOT_HOME` (default
`~/.jobbot`), `JOBBOT_MODEL` (default `qwen2.5:7b`), and `OLLAMA_HOST`.

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

[← Docs index](README.md) · [Project README](../README.md)
