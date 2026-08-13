---
name: target-company-sde-scanner
description: Use this whenever the user wants to find currently open Software Engineer / SDE roles requiring roughly 1-3 years of experience (SDE II, SDE-2, Software Engineer II, mid-level, L2/L3, "1-3 years") across target MNCs, Indian startups, and the expanded employer pool in the bundled reference. Also use it when the user asks to tailor their resume for one or more of these roles. Trigger on "scan my target companies," "check my company list for jobs," "any SDE-2 openings," "find mid-level roles at [company]," "run my job search," "update my target list job search," "tailor my resume for these roles," or a bare "more" / "check for new jobs" once this search has been established. Use direct employer application pages and verify each listing still exists before returning it.
---

# Target-Company SDE Scanner (1-3 YOE)

Finds real, currently open Software Engineer roles requiring **roughly 1-3 years of experience**
across a fixed universe of target companies (see `target-companies.md`), and returns a
ranked, deduplicated shortlist with direct apply links. This is a search-and-compile skill — it
runs live web searches each time it's invoked, not a background crawler.

## Step 0: Load the company list

Read `target-companies.md` for the full tiered company list before starting. Don't
re-type or summarize the whole list back to the user — just use it to drive searches.

## Step 1: Scope the run

Given the list has 100+ companies, a full sweep every time isn't practical or useful. Confirm scope
quickly (skip if already answered earlier in the conversation):

- **Which tiers to cover this run**: Tier 0 (profile-priority, ~25 companies) only, or Tier 0 + Tier 1
  (global MNCs), or everything including Tier 2 (India startups)? Default to **Tier 0 only** for a
  first/quick run if the user doesn't specify — it's the group they said matters most.
- **Location**: India-based roles specifically, remote, or open to any (many of these companies hire
  for both US and India offices for the same title).
- **Experience framing**: confirm "1-3 years" means they want roles explicitly labeled SDE-2 /
  Software Engineer II / mid-level, OR any listing whose stated range (e.g. "2-4 years", "1+ years")
  overlaps 1-3 years. Default to the overlap interpretation — it catches more real listings, since
  many companies don't use a clean "1-3 years" band.

## Step 2: Search company-by-company, using the right query pattern

**For Tier 0 and Tier 1 companies, start from the verified URL table in
`target-companies.md`** — open or fetch that URL directly instead of searching for the
portal. Prefer a listed direct ATS board over a marketing careers page when both are available. This
is faster and more reliable than a fresh search for the ~80 companies already verified there. If a
listed URL 404s, looks stale, or doesn't turn up an engineering section, don't just give up on that
company — fall back to the search pattern below for it. Entries marked "not independently
re-verified" or "spot-check" in the table are slightly lower-confidence; treat a bad fetch on those as
expected, not a sign of a broken skill.

**For Tier 2/3 companies (and any Tier 0/1 fallback)**, run one to two targeted searches per company:

**Direct careers-site pattern** (use first for any company without a table entry):
`"<company>" careers software engineer II`
`"<company>" jobs "1-3 years" OR "2 years" software engineer`

**If the direct search is thin or the careers page requires JS to browse**, fall back to ATS
site-search, since most companies' real listings live on one of these under the hood:
`site:boards.greenhouse.io "<company>" software engineer`
`site:job-boards.greenhouse.io "<company>" software engineer`
`site:jobs.lever.co "<company>" software engineer`
`site:myworkdayjobs.com "<company>" software engineer`
`site:jobs.ashbyhq.com "<company>" software engineer`

Open or fetch the actual careers/listings page once found — search snippets alone are often
stale, missing the experience range, or missing the direct apply link. Prioritize postings that look
recently updated; drop anything you can't confirm is still open.

Work through companies in tier order (Tier 0 fully before moving to Tier 1, etc.) so that if the run
gets cut short for time, the highest-priority companies are the ones covered.

When the user asks for **"more"**, move to unused companies in Tier 2 and the expanded pool before
repeating a company. Broaden to all employer types only when the user permits it; keep the India and
YOE filters unless they explicitly relax them.

### Required live-listing verification

Do not return a role based on a search snippet, job-board search result, cached result, or an ATS
index alone. Open the exact employer-hosted posting during the current run and retain it only when:

1. the page shows the role title and location (or remote region);
2. it exposes an active **Apply**, **Apply now**, **Submit application**, or equivalent application
   form/button; and
3. the page has not redirected to a generic jobs board, an `error=true` URL, or a "job not found" page.

Use the posting's canonical employer URL in the result. A localized ATS path is acceptable only when
it is the active application route; do not invent or preserve locale variants merely because they
appeared in a search result. Keep a board URL in the reference only after opening it in the browser
and confirming that it belongs to the employer. Add exact posting URLs to a user response only after
the same-run verification above; do not store them as evergreen openings.

For JavaScript-only Greenhouse/Lever/Ashby/Workday pages, render the posting in the browser and
inspect the visible page before accepting it. A JavaScript shell or a search-engine cache is not
verification. For Amazon, use the official India search page to discover job IDs, then open the
exact `amazon.jobs/en/jobs/<id>/...` page and confirm its **Apply now** control.

Never recycle a URL merely because it appeared in a previous batch. Re-check it every run. If a
candidate disappears while verifying, exclude it without mentioning it as an opening.

## Step 3: Filter for the 1-3 YOE band

Keep a listing only if the posting's stated experience requirement plausibly overlaps 1-3 years:
titles/levels like SDE-2, SDE II, Software Engineer II, L2/L3, "Engineer II", or an explicit stated
range such as "1-3 years," "2+ years," "1-4 years." Discard:

- New-grad-only or intern listings (0 YOE, explicitly "new college graduate")
- Senior/staff/principal-only listings (5+ years, "Senior," "Staff," "Lead," "Principal")
- Duplicate postings for the same role at the same company — keep one, prefer the direct company
  ATS/careers link over an aggregator mirror
- Anything you can't confirm is a real, currently-open listing

If a company's posting doesn't state a range but the title strongly implies mid-level (e.g. "Software
Engineer II"), keep it and note the assumption rather than dropping it.

## Step 4: Present results

Present as a table or grouped list in chat (not a file, unless the user asks to save it), grouped by
tier, with per listing:

- **Company — Role title**
- Location
- Stated experience range (or "implied by title" if not explicit)
- Direct apply link

State that the roles were verified on the employer page in the current run. Do not say "verified"
for a role that only has a current-looking search result. For a narrow search, return fewer than the
requested count rather than padding with stale listings.

End with a short coverage note: which companies in scope came back empty (either nothing open at that
level, or search didn't surface anything), so the user knows what wasn't covered rather than assuming
silence means nothing exists. Offer to continue into the next tier, or re-run later for fresh
postings.

## Step 5: Tailor resumes when requested

When the user provides a resume and asks for tailoring, first obtain the exact, currently verified
job postings to target. If the user has not identified them, use the shortlisted postings from the
current search and ask which roles to prioritize when there are more than three; otherwise tailor
for every requested role.

For each job, compare the resume against the employer-posted title, responsibilities, and required
qualifications. Produce a separate, ATS-conscious version that:

- uses the role's terminology only where it truthfully reflects the candidate's background;
- adjusts the headline, professional summary, skills ordering, and experience-bullet ordering to
  emphasize the most relevant real evidence;
- preserves employer names, dates, titles, education, credentials, scope, and measurable outcomes
  unless the candidate explicitly supplies a factual correction; and
- keeps the resume concise, readable, and specific to the job instead of merely keyword stuffing.

Never invent experience, skills, certifications, projects, metrics, employers, dates, or work
authorization. Do not claim proficiency from a keyword alone. Surface material gaps briefly so the
candidate can decide whether to add truthful context or apply as-is.

Return a short match note and one tailored resume per role. Default to a separate, ATS-friendly
PDF for each role; return Markdown only when the user explicitly requests text, and create `.docx`
only when they request an editable document. Keep the base resume and tailored versions private to
the conversation and do not store them in this skill or in the company list.

For each PDF, use the PDF workflow to render and visually inspect the final file before delivery.
Aim for a balanced, professional one-page layout: make good use of the vertical page area without
inventing filler, excessive whitespace, oversized headings, or artificially inflated margins. If
the rendered resume leaves a large unused lower portion of the page (roughly a quarter or more of
the content area), revise the layout before delivery by tightening unnecessary spacing, using a
compact skills presentation, or restoring truthful, relevant detail from the source resume. Confirm
that the final PDF is one page unless the source content genuinely requires more, with no clipped,
overlapping, or unreadably dense text. Use a descriptive per-role filename and do not commit the
candidate's resume or generated PDF to the skill repository.

Preserve every usable link from the source resume, including email, LinkedIn, portfolio, project,
GitHub, and coding-profile URLs. Inspect the source PDF's link annotations when applicable, copy
the same destinations into the tailored PDF, and reopen the output to confirm every expected
hyperlink annotation is present and active. Do not replace real URLs with plain-text labels.

## Notes

- Don't fabricate postings, companies, career-page URLs, or experience ranges. If coverage was thin
  for a company, say so — don't fill the gap with a plausible-sounding but unverified listing.
- This isn't a standing background job. There's no persistent crawler between sessions — to check for
  new postings later, the user just re-runs this in a future conversation (e.g. "check my target
  companies again").
- If the user's stack/profile (Salesforce, metadata systems, caching, GraphQL/SQLite, RAG/dev-agent
  work) comes up, weight Tier 0 companies and infra/dev-tools roles (backend, platform, developer
  infra) slightly higher when ranking, but don't exclude other SDE roles just because they're not an
  exact stack match.
- Resume tailoring improves relevance; it cannot guarantee an interview, ATS outcome, or hiring
  decision.
