# Using it as an AI-assistant skill

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
are in [`SKILL.md`](../SKILL.md).

---

[← Docs index](README.md) · [Project README](../README.md)
