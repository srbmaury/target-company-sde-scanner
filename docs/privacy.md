# Privacy and safety

- **Everything runs on your machine.** Your profile (`profile.yaml`, git-ignored) lives in the
  repository folder. The tracker database (`applications.db`) and browser profile live in
  `~/.jobbot/`. The only network traffic is to the job boards themselves, to Google's Gmail API if
  you connect Gmail, and to Ollama on localhost.
- **Your data folder is private.** `~/.jobbot` (tracker, logs with the values filled into forms, Gmail token,
  browser profile) is readable by your user account only.
- **Reviewed automatic submits.** Automatic mode requires explicit Ollama approval before every Next and Submit. Use `--no-auto-submit` or uncheck automatic submission in the dashboard for manual review.
- **One job-site password, in your Keychain.** If you store one with `jobbot password` and set
  `automation.create_accounts: true`, jobbot signs in to job sites with it, and when a site has no account
  for you it signs up with it, then verifies by email. The password goes from the macOS Keychain straight
  into the site's password box: never into profile.yaml, logs, the dashboard, or the local model. A
  rejected password is not retried; CAPTCHAs and password resets are left to you. Without a stored
  password, jobbot waits for you to sign in in the browser.
- **Gmail: a job-hunting mailbox.** jobbot asks for full mailbox access on Google's own sign-in page
  (the mailbox is meant for job hunting only). It reads application emails and verification codes and
  links, labels the ones it used "jobbot" and marks them read; it never sends or deletes mail. Revoke it
  with `jobbot gmail logout`.
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
