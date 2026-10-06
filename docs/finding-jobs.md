# Finding and ranking jobs

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
requirement (or a range in the title, such as "(1 to 4 Years)"). It drops roles that ask for more
years than your `max_yoe`, roles at excluded companies, and roles you have already applied to. New
roles are stored in the tracker.

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
