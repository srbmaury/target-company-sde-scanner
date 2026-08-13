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

The skill creates a separate targeted version for each role. It highlights genuine evidence and
reorders relevant content, but never invents skills, metrics, experience, or credentials.

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
