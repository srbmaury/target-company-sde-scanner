# Privacy and safety

- **Everything runs on your machine.** Your profile (`profile.yaml`, git-ignored) lives in the
  repository folder. The tracker database (`applications.db`) and browser profile live in
  `~/.jobbot/`. The only network traffic is to the job boards themselves, to Google's Gmail API if
  you connect Gmail, and to Ollama on localhost.
- **Your data folder is private.** `~/.jobbot` (tracker, logs with the values filled into forms, Gmail token,
  browser profile) is readable by your user account only.
- **No automatic submits.** The final Submit always needs your keypress, or your click in the dashboard.
- **No passwords.** jobbot never reads, stores, or types passwords, and skips password fields.
  Gmail uses Google's own sign-in page with read-only access, and you can revoke it with
  `jobbot gmail logout`.
  When a site needs you to sign in, it waits for you to do it in the browser.
- **No CAPTCHA solving.** CAPTCHAs are left to you.
- **No made-up answers.** Answers come from your profile, your resumes, or you. Model drafts are
  grounded in those facts. They are used without asking only if `auto_accept_drafts` is on (the
  default), and every one is listed in the page report and the logs; review them before you submit.
- **Hidden trap fields are skipped.** Some forms include invisible fields that only bots fill in;
  jobbot leaves them empty so the application isn't flagged as automated.

Many job sites' terms discourage automated applications. Use jobbot as an assistant for
applications you would make anyway, not to send them in bulk.

---

[← Docs index](README.md) · [Project README](../README.md)
