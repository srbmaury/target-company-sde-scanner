# How `apply` works

For each job you pass, one after another:

1. **Opens the posting** in a separate Chrome window with its own profile, so it never touches your
   everyday browser. Site sign-ins you make there are remembered for next time.
2. **Starts the application**, for example by clicking Apply or "Autofill with Resume" on Workday,
   and attaches the resume chosen by `rank`.
3. **Fills every field it can** from your profile: name, contact details, links, current company
   and title, CTC, notice period, education, work authorization, sponsorship, EEO answers, and
   your own fixed answers.
4. **Asks you only when it has to**, in the terminal or, when you apply from the dashboard, in its
   Apply tab:
   - questions matching your `always_ask` list, such as signatures and legal or sanctions questions
   - required questions nothing answers. Before asking, Ollama reasons about the question: facts
     (tools, certifications, years, education) only from your profile and resumes, a tool or
     certification your resumes don't show is "No", and preference questions (on-call, hybrid
     work, a fast-paced team, learning a new language) may be inferred when nothing in your profile
     contradicts them. Citizenship, visas, clearances, criminal history and similar questions never
     go to the model. Drafts are used without asking by default (`automation.auto_accept_drafts`);
     every answer and its source are shown in the page report and the logs.
   - consent and privacy boxes, once per application, unless `automation.auto_consent` is on
   - email verification codes: with Gmail connected, jobbot reads the code from your newest
     verification email (up to 90 s) and only asks if none arrives; Workday's separate code boxes are
     filled one character each
5. **Reviews the page until it is stable.** Each round it:
   - reads back every value it set, including dropdowns, radios, and Workday widgets
   - corrects values the site pre-filled wrongly (for example Workday's resume autofill), using only
     your profile, rules, and remembered answers, never a model guess
   - looks for empty required fields, the site's own validation errors (including Workday's
     "Errors Found"), and CAPTCHAs

   It repeats until a whole round changes nothing and every check passes (up to 5 rounds). If
   problems remain that it can't fix, it shows you exactly what is wrong.
6. **Moves through multi-page forms by itself**: when a page passes the check, it clicks
   Next / Save and Continue. Use `--no-auto-next` to stop after every page.
7. **Stops on the final page.** jobbot never submits on its own. You review the browser, then press:

   | Key | Action |
   | --- | --- |
   | `s` | jobbot clicks Submit, waits for the confirmation text, and records the application |
   | `r` | re-fill the page (after you fix something) |
   | `d` | you submitted it yourself; jobbot records it |
   | `q` | quit without submitting; nothing is recorded |

   In the dashboard the same choices are buttons: **Submit application**, **Re-fill this page**,
   **I submitted it myself**, and **Quit without submitting**.

**Supported sites**

| Applicant-tracking system | Example employers | Support |
| --- | --- | --- |
| Greenhouse | MongoDB, Stripe, Datadog, Celonis | Full |
| Lever | Meesho, CRED, Zeta, HighLevel | Full |
| Ashby | Snowflake, Confluent, Anyscale, OpenAI | Full |
| Workday | Adobe, NVIDIA, Visa, Cisco, Wells Fargo | Multi-page; many employers require you to sign in first |
| SmartRecruiters | ServiceNow | Multi-page, best effort |
| Anything else | | Opens the page for you to fill; jobbot still tracks the result |

**What happened?** `./jobbot.sh logs` shows, page by page and round by round, what jobbot filled,
what it corrected (with the old value), and what the check found. Logs are in `~/.jobbot/logs/`.

**Useful flags:** `--dry-run` (fill and check, but never submit or record), `--resume ai_engineer`
(override the ranked resume), `--llm none` (skip Ollama), `--no-upload`, `--force` (reopen a role
already marked applied).

> Try your first application on any new site with `--dry-run`.

## Unattended mode

```bash
./jobbot.sh apply --top 20 --unattended
```

jobbot works through the whole batch without stopping:

- Questions nothing answers are left blank and noted, instead of stopping to ask.
- Jobs that need you (a sign-in, a question only you can answer, a verification code that didn't
  arrive by email) are set aside with the reason, and the batch moves on.
- Every application that passes all checks stays open in its own tab.

At the end jobbot lists the jobs that need you, then shows each ready application in turn: press
`s` to submit it (jobbot waits for the confirmation and records it), `d` if you submitted it
yourself, or `q` to close it without submitting. In the dashboard, tick **Don't stop for me**
before **Apply to selected**; the ready applications then come up one by one with a **Submit
application** button.

`--unattended` also skips the batch list at the start, but never the "you may have applied
already" check: those roles are skipped. jobbot never presses Submit by itself and never types
passwords.

## Checking the model's answers

Every answer the local model gives is logged with its reasoning. Review them now and then:

```bash
./jobbot.sh answers                         # unreviewed model answers, newest last
./jobbot.sh answers ok 12                   # it got #12 right
./jobbot.sh answers fix 13 "No"             # #13 was wrong; "No" is saved as a learned answer
```

The list ends with your measured accuracy (right vs corrected), so you can see whether the model is
good enough to trust with `--unattended`.

## Daily limit

jobbot stops a batch once it has submitted `automation.max_applications_per_day` applications today
(25 by default; 0 turns the limit off). Many job sites discourage high-volume applying; a modest
daily number keeps your accounts in good standing.

## Dry run

`--dry-run` does everything a real run does (opens the posting, clicks Apply, attaches your resume,
fills and checks every page, reads codes from email, moves through multi-page forms) but never
clicks Submit and records nothing in the tracker. Your details are still typed into the employer's
form, and accounts you create are real. Use it on a new site first.

---

[← Docs index](README.md) · [Project README](../README.md)
