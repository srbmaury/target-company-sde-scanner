# How `apply` works

Automatic applications are the default. `./jobbot.sh apply --top 20` runs without user
prompts, requires Ollama approval covering every field before each Next and Submit, and
records confirmed submissions. Jobs blocked by missing facts, sign-in, CAPTCHA, rejected
review, or unavailable verification codes are listed with a reason; the batch moves on.
A Submit click with no recognised confirmation is reported for checking and is never
blindly repeated. Ollama must be running with the selected model installed.

The dashboard runs `automation.parallel_workers` independent application browsers (default 1,
limited to the selected batch size). All browsers and review batches share at most two concurrent Ollama calls. An optional daily application cap also applies to parallel batches. CLI applications are
sequential. To use the interactive workflow below, pass `--no-auto-submit`.

For each job in the interactive workflow:

1. **Opens the posting** in a separate Chrome window with its own profile, so it never touches your
   everyday browser. Site sign-ins you make there are remembered for next time.
2. **Starts the application**, for example by clicking Apply or "Autofill with Resume" on Workday,
   and attaches the resume chosen by `rank`.
3. **Fills every field it can** from your profile: name, contact details, links, current company
   and title, CTC, notice period, education, work authorization, sponsorship, EEO answers, and
   your own fixed answers. With Ollama running, the local model reads **every** question in full
   and decides the answer. Your fixed answers, remembered answers and jobbot's keyword rules only
   suggest a value: the model keeps it (exactly as written in your profile) when it really answers
   the question, and overrules it when the words match but the meaning doesn't. For example,
   "please state the reason for each gap" is not the State field. That costs a few seconds per
   field. Without Ollama (`--llm none`), the rules answer on their own.
4. **Asks you only when it has to**, in the terminal or, when you apply from the dashboard, in its
   Runs tab:
   - questions matching your `always_ask` list, such as signatures and legal or sanctions questions
   - required questions the model can't answer. Facts (tools, certifications, years, education)
     come only from your profile and resumes, a tool or certification your resumes don't show is
     "No", and preference questions (on-call, hybrid work, a fast-paced team, learning a new
     language) may be inferred when nothing in your profile contradicts them. For citizenship,
     visas, clearances, criminal history and similar questions the model may only use a fact
     stated in your profile, never an inference. Drafts are used without asking by default (`automation.auto_accept_drafts`);
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
(override the ranked resume), `--no-auto-submit --llm none` (interactive mode without Ollama), `--no-upload`, `--force` (reopen a role
already marked applied).

> Try your first application on any new site with `--dry-run`.

## Unattended mode

```bash
./jobbot.sh apply --top 20 --no-auto-submit --unattended
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
already" check: those roles are skipped. In this manual submission mode, jobbot waits for your Submit.

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
(unlimited by default; a positive value enables a cap). Many job sites discourage high-volume applying; a modest
daily number keeps your accounts in good standing.

## Dry run

`--dry-run` does everything a real run does (opens the posting, clicks Apply, attaches your resume,
fills and checks every page, reads codes from email, moves through multi-page forms) but never
clicks Submit and records nothing in the tracker. Your details are still typed into the employer's
form, and accounts you create are real. Use it on a new site first.

---

[← Docs index](README.md) · [Project README](../README.md)
