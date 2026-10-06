# Your profile

`profile.yaml` in the repository folder holds everything jobbot answers with. It is created from
[`profile.example.yaml`](../profile.example.yaml). It is **git-ignored**, because it contains your
contact details and CTC, so it is never committed. The main sections:

| Section | What it holds |
| --- | --- |
| `personal` | name, email, phone, country code and phone type, city, state, address, languages besides English |
| `links` | LinkedIn (use the `www.` form), GitHub, website |
| `work` | current company and title, start month, years of experience, past employers, notice period, current and expected CTC, reason for change, outside business activities |
| `education` | school, degree, field, GPA, years |
| `eligibility` | work authorization, sponsorship, relocation, background check, military service |
| `eeo` | gender, ethnicity, veteran and disability answers (`Decline` picks the decline option) |
| `preferences` | location regex, `max_yoe`, excluded companies, "how did you hear about us", preferred work locations (for location dropdowns) |
| `resumes` | each resume variant: a key, the PDF path, and a short focus hint for ranking |
| `answers` | your fixed answers: a regex matched against the question, and the answer to give |
| `always_ask` | regexes for questions jobbot must always ask you about |
| `automation` | `auto_accept_drafts` (use model drafts for free-text questions without asking; on by default), `auto_consent` (tick consent boxes without asking; off by default), `auto_sign` (type your full name into signature fields; off by default), `read_codes_from_email` (on), `confirm_batches` (ask before more than 3 roles; on) |
| `learned_answers` | answers you gave during applications, which jobbot fills in itself (see below) |

**jobbot learns as you go.** When you answer a question, in the terminal or the dashboard, jobbot
saves it under `learned_answers` and reuses it for the same or a very similar question at any
company, so you're asked once. Answers that name the employer ("Why do you want to join Acme?") are not saved. You
can edit or delete entries in the file.

**Teaching jobbot new answers by hand.** If a question keeps coming up, add a rule under `answers`. These
rules take priority over everything else, including `always_ask`:

```yaml
answers:
  - match: "years of experience (with|in) java"
    answer: "2"
  - match: "\\breferr(ed|al)\\b"       # \b avoids matching "Preferred Start Date"
    answer: "No"
```

---

[← Docs index](README.md) · [Project README](../README.md)
