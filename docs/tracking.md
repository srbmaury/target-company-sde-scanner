# Tracking applications

Every application jobbot submits is recorded automatically. Add the ones you make elsewhere so the
tracker stays complete:

```bash
./jobbot.sh track                                    # all applications, newest first, with totals
./jobbot.sh track --status interview                 # filter by status (or --company)
./jobbot.sh track add --company Acme --title "SDE II" --url https://... --status applied
./jobbot.sh track update 42 --status interview --note "system design on Friday"
./jobbot.sh track show 42                            # details and full status history
./jobbot.sh track stats                              # counts, response rate, interview rate
./jobbot.sh track export applications.csv            # open in a spreadsheet
./jobbot.sh track import old.csv                     # columns: company,title,status,applied_on,url,notes
./jobbot.sh track sync-gmail                         # import applications from Gmail (see below)
./jobbot.sh track import-gmail emails.json           # or build rows from an exported JSON of emails
```

Statuses: `shortlisted`, `applied`, `assessment`, `interview`, `offer`, `rejected`, `withdrawn`,
`ghosted`.

**How jobbot knows you already applied.** Applications imported from email often have no job link,
so jobbot also matches on company and title. It ignores suffixes ("Sarvam AI" = "Sarvam"), job IDs,
punctuation and Roman numerals ("Software Engineer 2" = "Software Engineer II"), but levels must
agree ("Software Engineer II" ≠ "Software Engineer").

- **Already applied** (same link, or same company and title): left out of `jobs`, and skipped by
  `apply` unless you pass `--force`.
- **Possibly applied**: shown as `[applied?]`, and `apply` asks before opening it. This covers:
  - the email didn't name the role
  - the same title was posted after you applied (big employers reuse titles for new openings)

## Gmail sync

`track sync-gmail` reads your application emails and adds them to the tracker:
- acknowledgements become `applied`
- rejections become `rejected`
- assessment and interview invitations become `assessment` / `interview`

Run it after applying through job boards, so `apply` never reopens a role you already applied to.

**Connect once.** You sign in on Google's own page in your browser. jobbot asks for **full mailbox**
access (use a mailbox for job hunting only): it reads application emails and verification codes and
links, labels the ones it used "jobbot" and marks them read, and never sends or deletes mail. It never
sees your Google password. A token from an older, read-only connection keeps working for reading. Google requires every app that reads
Gmail to have its own OAuth client, so this takes a few minutes once:

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project and enable the
   **Gmail API**.
2. Under **Google Auth Platform**, set up branding (app name "jobbot", your email). Under
   **Audience**, choose External and add your own Gmail address as a test user.
3. Under **Clients**, create a client of type **Desktop app** and download its JSON.
4. Connect:
   ```bash
   ./jobbot.sh gmail login --client ~/Downloads/client_secret_....json
   ```
   Google shows an "unverified app" warning because the app is yours and unpublished. Choose
   Continue, then allow access.

Then sync whenever you like:

```bash
./jobbot.sh track sync-gmail                  # application emails from the last 60 days
./jobbot.sh track sync-gmail --days 180       # look further back
./jobbot.sh track sync-gmail --all-mail       # read every email in the period, keep application emails
./jobbot.sh gmail status                      # which account is connected
./jobbot.sh gmail logout                      # revoke access and delete the token
```

What jobbot reads: sender, subject, a short preview, and the date of each message. It never
downloads attachments, and never sends, labels or deletes anything. Email bodies are read in one
case only: while `apply` waits for a verification code, if the newest verification email's preview
doesn't contain the code, that one email's text is read to find it (`read_codes_from_email: false`
turns this off). The token is
stored in `~/.jobbot/gmail_token.json`, readable only by you. If Gmail isn't connected yet,
`sync-gmail` offers to connect it.

The matching is heuristic, so review the result with `track` and fix rows with `track update`.
`import-gmail <file.json>` does the same from an exported list of messages (sender, subject,
snippet, date).

---

[← Docs index](README.md) · [Project README](../README.md)
