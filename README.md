# Target-Company SDE Scanner

[![tests](https://github.com/srbmaury/target-company-sde-scanner/actions/workflows/tests.yml/badge.svg)](https://github.com/srbmaury/target-company-sde-scanner/actions/workflows/tests.yml)

**Find, rank, and track software-engineering jobs across 300+ target companies. Fill applications in your own browser when you're ready.**

Jobbot scans company job boards and career sites, filters roles using your profile, and ranks them
against your resume variants. It's tuned for candidates with roughly 1–3 years of experience, but
locations, experience limits, and company exclusions are configurable. Use the CLI, the dashboard,
or the [AI-assistant skill](docs/skill.md).

## Choose how to run it

| Mode | Best for | Where data lives |
| --- | --- | --- |
| **Local** | Scanning, ranking, tracking, and filling applications in Chrome | Profile, resumes, tracker, and browser sessions on your machine |
| **GitHub Codespaces** | Running scans, ranking, and using the dashboard without installing Jobbot on your Mac | Inside that Codespace. Opening it from another device preserves the same files, but a new Codespace starts fresh |
| **Hosted private account** | Signing in from any device with persistent profile, resumes, Gmail, and history | Encrypted account data in MongoDB. Browser-based application filling stays local |

## Quick start

Use **Python 3.11+** and Git. For browser-based application filling, install Google Chrome or
Playwright Chromium. Neither Gmail nor an LLM is needed to scan jobs or use the tracker.

```bash
git clone https://github.com/srbmaury/target-company-sde-scanner.git
cd target-company-sde-scanner
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./jobbot.sh init
```

Edit the generated, Git-ignored `profile.yaml`. Set your real contact details, preferences, and
resume paths. Give each resume a short key and a description of the roles it fits:

```yaml
resumes:
  backend:
    path: /absolute/path/to/backend.pdf
    focus: Java, Spring Boot, distributed systems
  fullstack:
    path: /absolute/path/to/fullstack.pdf
    focus: React, TypeScript, product engineering
```

Use paths that exist **on the machine running Jobbot**. If your PDFs are in Google Drive, download
or upload them to that machine first. A Drive share link isn't a local PDF path. In a Codespace,
`output/resumes/` is already Git-ignored and can hold private copies of your PDFs.

```bash
./jobbot.sh doctor
./jobbot.sh ui
```

The local dashboard defaults to `http://127.0.0.1:8765/`. In Codespaces, run
`./jobbot.sh ui --no-open`, then forward the printed port privately through VS Code Desktop
or run `gh codespace ports forward 8765:8765 -c CODESPACE_NAME` on your computer. Open the
local forwarded address in your browser. The local dashboard expects a localhost Host header.
If Chrome is not installed and you need to run the browser suite or fill applications, install
the fallback browser with `.venv/bin/python -m playwright install chromium`. On supported Linux
systems, add `--with-deps` if system libraries are missing.

## Configure the model

| Choice | Setup | Notes |
| --- | --- | --- |
| **Ollama** | Start Ollama and run `ollama pull qwen2.5:7b` | Default. Runs inference locally. Set `JOBBOT_MODEL` to change the model or `OLLAMA_HOST` to use another Ollama server |
| **OpenAI** | Set `JOBBOT_LLM_PROVIDER=openai` and `OPENAI_API_KEY` | Defaults to `gpt-4.1-mini`. Set `OPENAI_MODEL` to override. No Ollama installation or model download required |
| **No model** | Use `./jobbot.sh rank --llm none` | Keyword ranking. Automatic application submission requires a working configured model |

On macOS with Homebrew, the Ollama setup is:

```bash
brew install ollama
brew services start ollama
ollama pull qwen2.5:7b
```

For OpenAI, create an [API key](https://platform.openai.com/api-keys) and configure API billing
separately from your ChatGPT subscription. In Codespaces, use a Codespaces secret named
`OPENAI_API_KEY` and restart the Codespace after adding it. On a host, use its secret settings.
Then run:

```bash
export JOBBOT_LLM_PROVIDER=openai
# export OPENAI_MODEL=gpt-4.1-mini  # Optional. This is the default.
./jobbot.sh doctor
```

If you prefer a local `.env` file, exclude it from Git **before** saving the key
(`printf '/.env\n' >> .git/info/exclude`). Put the variable assignments there, run
`chmod 600 .env`, then load your trusted file with `set -a; source ./.env; set +a`.
Jobbot does not load it automatically. Start `./jobbot.sh ui` from that same shell so its
background workers inherit the settings.

`doctor` checks whether the OpenAI key is configured, not whether it can make a successful
request. After scanning and adding a resume, try `./jobbot.sh rank --limit 1` on an unranked job.
The CLI also accepts `--llm openai`, `--llm ollama`, and `--model` on model-enabled commands.
Jobbot doesn't automatically switch from Ollama to OpenAI. Ranking can fall back to keyword
matching, but a failed required model review blocks automatic submission. OpenAI mode sends
candidate facts, resume text, and relevant application questions or review values to the API.
See [privacy and safety](docs/privacy.md).

## Scan, rank, apply, and track

```bash
./jobbot.sh scan
./jobbot.sh rank
./jobbot.sh jobs --why
./jobbot.sh apply --top 1 --no-auto-submit --dry-run
./jobbot.sh track
```

Start with a **dry run**. It can fill forms and upload a resume but does not submit the
application. Add `--no-upload` to skip the attachment. When you're ready to submit with manual
approval, remove `--dry-run` but keep `--no-auto-submit`. Without that flag, `apply` defaults
to automatic submission after the required checks and model review. Use `--no-auto-next` if
you want to stop at each page.

Pass job IDs from `jobs` (for example `apply 12 15` or `apply 12-20`), a posting URL,
`--top N`, or `--all --min-fit 80`. `--resume KEY` overrides the ranked resume, and
`--exclude "Company A,Company B"` adds to the profile's company exclusions for that run.

Jobbot reads the live form's labels, options, and relevant help text. It fills what it can using
profile facts, rules, or the configured model, then reads the values back. It leaves unclear
questions for review, checks what a dropdown actually retained, and uses the form controls
rather than page text to identify the final Submit step. Empty intermediate steps can
continue without a model field review. Required approval still applies at Submit in automatic
mode. Jobbot doesn't send raw page HTML to the model.

In **Runs**, expand a page revision to see the extracted question, answer source, and what the
browser read back. The **Applications** table and detail view show which resume was recorded.
If a record has no resume, the dashboard says **Not recorded**. See [the application workflow
and supported sites](docs/apply.md).

## Connect Gmail

**Local or Codespaces.** Enable the Gmail API in a Google Cloud project, configure the OAuth
consent screen, and create a **Desktop app** OAuth client. Add your Gmail address as a test
user if the project is External and in Testing. Keep the downloaded client JSON outside Git.

```bash
./jobbot.sh gmail login --client "$HOME/.jobbot/gmail_client.json"
./jobbot.sh gmail status
./jobbot.sh track sync-gmail
```

You can also use **Actions → Connect Gmail** after saving the JSON at
`~/.jobbot/gmail_client.json`. In Codespaces this uses the same loopback callback as the CLI.
Keep the sign-in command running, then privately forward the port from the **current** Google
link to the same port on your computer before approving. Use VS Code Desktop or run
`gh codespace ports forward PORT:PORT -c CODESPACE_NAME` on the computer running your browser,
not inside the Codespace. Get the exact name with `echo "$CODESPACE_NAME"` inside the Codespace.
If the local port is already in use, check whether VS Code is already forwarding it.

The desktop flow requests full mailbox access, even if an older CLI message says “read-only.”
It can label and mark used verification emails as read. The hosted flow below requests
read-only Gmail access. `./jobbot.sh gmail logout` disconnects the CLI connection.
See [Gmail tracking](docs/tracking.md).

## Set up the hosted MongoDB account

Hosted mode is optional and supports **one configured owner per deployment**. It can scan,
rank, track, and import Gmail. It does not host the browser used to fill applications.

1. Provision MongoDB and choose a stable HTTPS dashboard URL. Configure a TLS-enabled database
   connection with access restricted to your deployment.
2. Create a Google **Web application** OAuth client with the exact redirect URI
   `https://YOUR-DASHBOARD-HOST/auth/google/callback`. The Desktop app JSON is for the local flow.
3. Set these variables in the hosting environment:

   | Variable | Value |
   | --- | --- |
   | `JOBBOT_MONGODB_URI` | MongoDB connection string |
   | `JOBBOT_MONGODB_DB` | Optional database name, default `jobbot` |
   | `JOBBOT_DATA_KEY` | Fernet encryption key. Generate once and back it up securely |
   | `JOBBOT_ACCOUNT_EMAIL` | Google email allowed to sign in and connect Gmail |
   | `JOBBOT_PUBLIC_URL` | The dashboard's HTTPS origin, no subpath |
   | `JOBBOT_GOOGLE_CLIENT_ID` | Web application OAuth client ID |
   | `JOBBOT_GOOGLE_CLIENT_SECRET` | Web application OAuth client secret |
   | `JOBBOT_BIND` | `0.0.0.0` behind the host's HTTPS proxy |
   | `PORT` | Hosting port if provided, otherwise Jobbot defaults to `8765` |

   After installing dependencies, generate the key with
   `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`.
   Keep the database URI, data key, and OAuth secret in the host's secret settings. Keep the
   **same owner email and data key** when redeploying. The proxy must preserve the public Host
   header. Start the dashboard with `./jobbot.sh ui --no-open`.

4. Open the HTTPS dashboard and choose **Continue with Google**. Then select
   **Actions → Connect Gmail** to grant read-only access separately. This flow needs no local
   port forward. External Google OAuth apps in Testing issue Gmail refresh tokens that expire after
   seven days, so you'll need to reconnect.
5. Open **Profile** to fill in your details. Save a key for each resume, then upload its PDF
   using that key. A new account starts blank. Hosted mode uses those uploads, not local paths.

The sign-in page appears at the configured HTTPS URL. If you only see the local dashboard,
check that the process was started with the hosted environment variables.
See the [hosted account guide](docs/accounts.md) for storage limits and configuration details.
Local browser runs and the local tracker remain separate.

## Documentation

| Guide | Covers |
| --- | --- |
| [Finding and ranking jobs](docs/finding-jobs.md) | Sources, filters, ranking, choosing roles |
| [Applying](docs/apply.md) | Form filling, review checks, dry runs, supported sites |
| [Dashboard](docs/dashboard.md) | Jobs, Runs, Applications, Actions, Profile |
| [Hosted accounts](docs/accounts.md) | MongoDB, Google sign-in, deployment |
| [Candidate profile](docs/profile.md) | Resume variants, rules, preferences, learned answers |
| [Tracking and Gmail](docs/tracking.md) | Status history, duplicates, email imports |
| [Command reference](docs/commands.md) | CLI commands and options |
| [Privacy and safety](docs/privacy.md) | Local storage, model data, browser behavior |
| [Troubleshooting](docs/troubleshooting.md) | Common issues and fixes |
| [AI-assistant skill](docs/skill.md) | Using the repository with Codex or Claude Code |

## Contributing

The CLI and tracker live in `jobbot/`, browser automation in `jobbot/apply/`, and the dashboard
in `jobbot/ui/`. See `references/ats-registry.json` and `target-companies.md` for job sources.
Read [CONTRIBUTING.md](CONTRIBUTING.md) before changing the registry or form-filling code.

```bash
.venv/bin/python -m pip install pyflakes mongomock
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pyflakes jobbot tests
.venv/bin/python -m unittest discover -s tests -v
```

The browser tests use fixture forms. The account tests use mocked Google and MongoDB.

## License

[MIT](LICENSE) © 2026 Saurabh Maurya
