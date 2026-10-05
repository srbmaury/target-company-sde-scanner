# Target-Company SDE Scanner

A reusable Codex skill for finding currently open software-engineering roles suited to candidates
with roughly 1–3 years of experience. It searches a curated, tiered employer list and returns a
deduplicated shortlist of roles with direct, verified application links.

## What it does

- Prioritizes companies by relevance, beginning with the Tier 0 target list.
- Searches official career sites and employer-hosted applicant-tracking systems.
- Keeps roles whose experience requirements overlap the 1–3 YOE range.
- Verifies that each role is currently open and has an active application path before reporting it.
- Reports location, experience requirement (or level-based assumption), direct apply link, and
  coverage notes for companies checked without a matching role.
- Tailors a factual, ATS-conscious resume version for each selected verified role when you provide
  your resume.

## Repository contents

| File | Purpose |
| --- | --- |
| `SKILL.md` | The complete operational instructions for Codex. |
| `target-companies.md` | Curated company tiers and known official career-site entry points. |
| `references/ats-registry.json` | Public job-board API identifiers (Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Microsoft) for 220+ companies, with the verification date. |
| `jobbot/` | Command-line tool: scan, rank against your resumes, fill applications in a browser, and track every application. |
| `scripts/ats_scan.py` | Standard-library wrapper around `jobbot.scan` that prints 1–3 YOE engineering candidates with the stated experience requirement. |
| `profile.example.yaml` | Template for your private jobbot profile (copied to `~/.jobbot/profile.yaml`). |
| `references/job-platforms.md` | Supplemental job boards, recruiters, and how to treat each as a lead. |

## jobbot: search, apply, and track from the terminal

jobbot runs locally and is free. The optional local model runs through [Ollama](https://ollama.com).

```bash
# one-time setup
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
brew install ollama && brew services start ollama && ollama pull qwen2.5:7b   # optional
./jobbot.sh init      # creates ~/.jobbot/profile.yaml; fill in your details and resume paths
./jobbot.sh doctor    # checks profile, resumes, browser, and Ollama
```

Daily loop:

```bash
./jobbot.sh scan                 # sweep 220+ company boards; new roles go into the tracker
./jobbot.sh rank                 # score new roles against each resume (local model, or keywords)
./jobbot.sh jobs --why           # best fits first, with the reason and the resume to use
./jobbot.sh apply 12 15          # fill those applications in Chrome; you approve each submit
./jobbot.sh apply --top 5        # or work through the five best-ranked roles
```

How `apply` behaves:

- It opens the posting in a real Chrome window with its own persistent profile, attaches the
  ranked resume, and fills every field it can answer from your profile.
- Questions listed under `always_ask` (signatures, legal and sanctions questions) and anything it
  cannot answer are asked in the terminal. With Ollama it drafts free-text answers for you to
  accept or edit; it never invents facts beyond your profile and resume.
- Consent and privacy boxes are listed and ticked only after you say yes.
- It never submits on its own. You review the browser, then choose submit, next step, refill,
  done, or quit. CAPTCHAs and logins are always left to you, and jobbot never handles passwords.
- `--dry-run` fills without submitting or recording anything.

Supported forms: Greenhouse, Lever, and Ashby fill end to end. SmartRecruiters and Workday are
best effort: multi-step pages, and Workday may ask you to sign in first. Other sites open in the
browser for you to fill, and jobbot still records the result.

Tracking every application, including ones made outside jobbot:

```bash
./jobbot.sh track                                   # list, newest first, with totals
./jobbot.sh track add --company Acme --title "SDE II" --url https://... --status applied
./jobbot.sh track update 42 --status interview --note "system design on Friday"
./jobbot.sh track show 42                           # details and status history
./jobbot.sh track stats                             # response and interview rates
./jobbot.sh track export applications.csv           # spreadsheet export
./jobbot.sh track import old.csv                    # bulk import (company,title,status,...)
./jobbot.sh track import-gmail emails.json          # rows from application emails
```

Statuses: shortlisted, applied, assessment, interview, offer, rejected, withdrawn, ghosted.
Your profile, tracker database, and browser profile live in `~/.jobbot/` (override with
`JOBBOT_HOME`), never in the repository.

## Use in Codex

Install this directory as a Codex skill, then ask a matching request such as:

```text
Scan my target companies for India-based SDE-2 roles.
```

For a quick first pass, the skill defaults to Tier 0 and interprets “1–3 years” as roles whose
stated requirements overlap that range. You can specify a different tier scope, location, or
experience interpretation in your request.

To tailor your resume after a scan, attach or paste it and say, for example:

```text
Tailor my resume for the Stripe and Datadog roles you found.
```

The skill creates a separate targeted PDF for each role. It highlights genuine evidence and
reorders relevant content, but never invents skills, metrics, experience, or credentials. Each PDF
is rendered and visually checked for a balanced, readable one-page layout before delivery, while
preserving the source resume's clickable contact, portfolio, project, and coding-profile links.

## Run the scanner directly

The scanner works without Codex and needs only Python 3:

```bash
python3 scripts/ats_scan.py --companies "Stripe,MongoDB,Adobe,ServiceNow"
python3 scripts/ats_scan.py --all --exclude "Salesforce" --max-yoe 3
python3 scripts/ats_scan.py --all --locations "hyderabad|bengaluru|bangalore|remote" --json
```

It prints a Markdown table of candidate roles plus per-company coverage. Every row still needs the
live-listing check described in `SKILL.md` before it is treated as an open role.

## Important behavior

This is a live search-and-compile skill, not a persistent job crawler. Openings are checked at the
time of each run; a previously returned link is never assumed to remain open. Only exact,
employer-hosted postings that show an active apply flow should be returned.

## Updating the company list

Career sites and company ownership change often. When changing `target-companies.md`, prefer
official employer career pages, record the verification date and any caveats, and avoid treating a
career-site URL as proof that a specific job is open.

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull
request.

## License

No license has been selected yet. Add one before distributing or accepting contributions under
specific reuse terms.
