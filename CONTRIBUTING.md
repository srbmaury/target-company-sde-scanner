# Contributing

Thanks for helping keep this skill useful and accurate.

## Scope

Contributions should improve one of the following:

- the skill workflow in `SKILL.md`;
- the company tiers or career-site references in `target-companies.md`; or
- the evidence-based resume-tailoring workflow; or
- documentation that makes the skill easier to install or use.

Please avoid adding job postings as persistent data. Specific openings are volatile and must be
verified during each search run.

## Updating company references

When adding or changing a career-site URL:

1. Prefer an official employer domain or its official ATS board.
2. Open the destination and confirm it belongs to the stated employer.
3. Note redirects, rebrands, acquisitions, regional limitations, or uncertainty in the table.
4. Include the date you verified a material change.
5. Do not infer a role is open solely because its career site is reachable.

Keep tier ordering intentional: Tier 0 is the highest-priority search set, Tier 1 contains major
global employers, and later tiers broaden coverage.

## Updating the ATS registry

`references/ats-registry.json` holds board identifiers, not openings. When adding or changing one:

1. Fetch the board's public API (for example `boards-api.greenhouse.io/v1/boards/<id>`,
   `api.lever.co/v0/postings/<id>`, `api.ashbyhq.com/posting-api/job-board/<id>`, or a Workday
   `/wday/cxs/<tenant>/<site>/jobs` search) and confirm it returns postings. Entry shapes by
   source (`ats`): `greenhouse`/`lever`/`ashby`/`smartrecruiters`/`workable`/`keka`/`freshteam`
   take an `id`; `workday` takes `host`, `tenant`, `site`; `oracle` takes `host`, `site`;
   `eightfold` takes `host`, `domain`; `json-feed` takes a `url` plus field paths; `careers-page`
   takes the careers `url` (and optionally `job_url`, a template like
   `https://example.com/jobs/{id}`). Prefer an API source: `careers-page` is the last resort.
2. Confirm the postings belong to the intended employer. Short slugs collide often: `capital`,
   `neon`, `circle`, `pine`, and `disney` all resolve to unrelated companies.
3. Add a `note` for rebrands or shared boards (for example Zynga on Take-Two's board).
4. Update the top-level `verified` date when you re-verify the file, and run
   `python3 scripts/ats_scan.py --all` to check that no entry errors.

## Working on jobbot

- Run `python3 -m unittest discover -s tests` before opening a pull request. `tests/test_forms.py` drives the real
  apply engine against local copies of real-site form patterns (`tests/fixtures/forms/`) in headless Chrome;
  when a site breaks jobbot, add its pattern there. `tests/test_golden.py` holds real questions and the answer
  each must get: add the question whenever you fix an answer.
- Test form-filling changes with `./jobbot.sh apply <n> --dry-run --no-upload`, which never
  submits or records anything.
- Keep jobbot conservative: no automatic submits, no password or CAPTCHA handling, and legal or
  attestation questions always go to the user unless their own profile answers them.
- Never commit `profile.yaml`, anything from `~/.jobbot/` (tracker, browser profile), or real resumes.

## Editing the skill

Keep the instructions actionable and conservative:

- Require current, employer-page verification before returning any listing.
- Preserve the 1–3 YOE filter and clearly state assumptions when a title implies level.
- Prefer direct application URLs over aggregators and search-result snippets.
- Do not introduce background monitoring or claims that a listing is evergreen.
- Preserve factual integrity in resume tailoring: never encourage fabricated skills, metrics,
  credentials, employment history, or dates.
- Preserve PDF quality: render and inspect tailored resumes, correct large unused page areas or
  layout defects, and never commit a candidate's resume or generated tailored file.
- Preserve all existing actionable resume links in tailored PDFs and verify their annotations after
  export; visible text alone is not sufficient.

## Pull requests

Before submitting a pull request:

1. Check that Markdown links and file references resolve.
2. Confirm `SKILL.md` references `target-companies.md` at its current path.
3. Summarize the source and verification date for any career-site update.
4. Keep unrelated formatting changes out of the pull request.

Use a concise title that describes the outcome, for example: `Update the Adobe careers entry point`.

## Documentation

User documentation lives in [`docs/`](docs/README.md); the README stays short (overview, quick start,
daily workflow, links). Update the matching page in the same pull request as a behaviour change.
