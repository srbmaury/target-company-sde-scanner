# Finding and ranking jobs

**`scan`** reads each company's jobs from where its careers site gets them:
- public job-board APIs: Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, Keka,
  Freshteam, Eightfold, and Oracle Recruiting Cloud
- the Amazon, Google, Apple, Microsoft, and Atlassian careers sites' own job feeds
- for companies with none of these, the careers page itself, opened in headless Chrome or Playwright Chromium (links and
  the job lists the page loads). This is less precise, and `--no-careers-pages` skips it.

About half of the companies in `target-companies.md` are covered this way. The rest (for example
Flipkart, Walmart, Intuit, SAP, Zomato) use sites jobbot can't read reliably yet; the AI-assistant
skill still finds those through web search.

The CLI and dashboard use `preferences.min_yoe` and `preferences.max_yoe` in your profile.
Both are inclusive, non-negative whole years. Existing profiles default to `1` and `3` for
missing settings. The filter checks for overlap with the posting's range. A role asking for
2–5 years matches a target of 4–7. A role asking for 2+ years has an open upper end.

The scanner includes entry-level titles such as new graduate when the lower bound is 0, and
considers titles such as Senior or Staff when the upper bound exceeds 3. It uses stated years
when available. Unstated roles are skipped by default, except for titles that imply mid-level
experience when your range overlaps 1–3. Use `--include-unstated` to include roles without an
experience estimate. The scanner also applies your location and company preferences, skips known
application URLs, and stores new matches in the tracker. Changing the range affects new scans.
Previously tracked jobs stay in the tracker. Several feeds query India specifically, so a different
location regex cannot broaden those feeds to other countries.

**`rank`** scores each new role from 0 to 100 against every resume variant and picks the best
resume for it. With Ollama this takes about 6–7 seconds per role on an Apple-silicon Mac; without
it, jobbot falls back to keyword matching. Treat scores as a sort order rather than a verdict: a
7B model sometimes misses a skill your resume does list.

**`jobs`** lists roles you have not applied to, best fit first. Add `--why` for the reason,
`--urls` for links, and `dismiss <n>` to hide roles you don't want.

**`apply`** takes job numbers or ranges from `jobs`, a posting URL, `--top N` for the N best-ranked
roles, or `--all`. It skips roles you have already applied to or dismissed. Before a batch of more
than 3 roles it lists them and asks you to confirm (`-y` skips this list; it never skips the "you may have
applied already" check). See the next section.

---

[← Docs index](README.md) · [Project README](../README.md)
