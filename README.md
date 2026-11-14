# Target-Company SDE Scanner

[![tests](https://github.com/srbmaury/target-company-sde-scanner/actions/workflows/tests.yml/badge.svg)](https://github.com/srbmaury/target-company-sde-scanner/actions/workflows/tests.yml)

Jobbot finds software engineering roles across 300+ target companies, ranks them against your resume variants, fills application forms, and tracks your applications.

| Start here | Use it for | Where your data lives |
| --- | --- | --- |
| [Local CLI](#local-cli-quick-start) | Scan, rank, track, and fill applications in a browser on your machine | Local profile, PDFs, tracker, and browser session |
| [Hosted dashboard](#hosted-dashboard) | Run the same workflow from a browser with one private Google account per deployment | Encrypted account data in MongoDB. Chromium runs on the host |
| [AI-assistant skill](docs/skill.md) | Search for and verify openings with Codex or Claude Code | See the skill's setup and workflow |

## Local CLI quick start

You need **Python 3.11+** and **Git**. Scanning job-board APIs and tracking applications work without Gmail or an LLM.

**1. Install Jobbot and create a profile.**

```bash
git clone https://github.com/srbmaury/target-company-sde-scanner.git
cd target-company-sde-scanner
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./jobbot.sh init
```

**2. Edit `profile.yaml`.** Add your contact details, experience, target locations, company exclusions, and resume variants. The saved scan range defaults to **1–3 years**. This example targets **4–7 years**:

```yaml
preferences:
  min_yoe: 4
  max_yoe: 7

resumes:
  backend:
    path: /absolute/path/to/backend.pdf
    focus: Java, Spring Boot, distributed systems
  fullstack:
    path: /absolute/path/to/fullstack.pdf
    focus: React, TypeScript, product engineering
```

Use PDF paths on the machine running Jobbot. Download Drive PDFs first. Both `profile.yaml` and the Codespaces folder `output/resumes/` are Git-ignored. See the [profile guide](docs/profile.md) for the available fields.

**3. Scan, rank, and review jobs.**

```bash
./jobbot.sh doctor
./jobbot.sh scan
./jobbot.sh rank --llm none
./jobbot.sh jobs --why
```

The scanner matches postings whose stated experience range overlaps yours. Use `./jobbot.sh scan --min-yoe 4 --max-yoe 7` to override the saved range for one run. The example uses keyword ranking. See [job sources and filtering](docs/finding-jobs.md) and [model setup below](#optional-model-setup).

**4. Try a dry run before applying.** Install Chrome or run `.venv/bin/python -m playwright install chromium`. On Linux, add `--with-deps` if system libraries are missing.

```bash
./jobbot.sh apply --top 1 --no-auto-submit --dry-run
./jobbot.sh track
```

A dry run can fill fields and upload a resume. It never submits. Add `--no-upload` to skip the attachment. To apply with manual approval, remove `--dry-run` and keep `--no-auto-submit`. Plain `apply` defaults to automatic submission after the required checks and model approval. Add `--no-auto-next` to pause at every page.

<details>
<summary>Application targets, overrides, and review details</summary>

- Select job IDs from `jobs` with `apply 12 15` or `apply 12-20`, pass a posting URL, or use `--top N` or `--all --min-fit 80`.
- Use `--resume KEY` to override the ranked resume and `--exclude "Company A,Company B"` to add company exclusions for the run.
- Jobbot uses form labels, options, and help text to choose answers from your profile, rules, or model. It reads filled values back, including dropdown selections, and leaves unclear questions for review. It identifies the final step from the form controls. Empty intermediate steps can advance without a model field review. Automatic Submit still requires model approval.
- In the dashboard, expand a page revision in **Runs** to see the question, answer source, and browser readback. **Applications** shows the recorded resume or **Not recorded**. Local and hosted trackers are separate.

See [the application workflow and supported sites](docs/apply.md).

</details>

## Hosted dashboard

Use a **Render Web Service** or **GitHub Codespace**. The dashboard requires a hosted account. Follow the [hosted account guide](docs/accounts.md) for platform setup, storage limits, and secrets.

**1. Prepare the host and database.** Install Jobbot's dependencies on the host. Provision MongoDB with TLS and network access for the host. Give the database user write and index permissions on the Jobbot database.

**2. Set up Google sign-in.** Create a Google OAuth **Web application** client. Register `https://YOUR-DASHBOARD-HOST/auth/google/callback` using the exact dashboard URL. Jobbot gets the HTTPS URL from the hosting platform.

**3. Configure the dashboard.** Set the variables below using host settings or the repo's Git-ignored `.env` in Codespaces. Start from [`.env.example`](.env.example).

| Variable | Value |
| --- | --- |
| `JOBBOT_MONGODB_URI` | MongoDB connection string |
| `JOBBOT_MONGODB_DB` | Optional database name. Defaults to `jobbot` |
| `JOBBOT_DATA_KEY` | Fernet key used to encrypt account data |
| `JOBBOT_ACCOUNT_EMAIL` | Google email allowed to sign in and connect Gmail |
| `JOBBOT_GOOGLE_CLIENT_ID` | Web application OAuth client ID |
| `JOBBOT_GOOGLE_CLIENT_SECRET` | Web application OAuth client secret |
| `JOBBOT_BIND` | Use `0.0.0.0` behind the host's HTTPS proxy |
| `PORT` | Host-provided port, or `8765` by default |

Generate the Fernet key once with `.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`. Back it up securely and keep the same key and owner email when redeploying. The proxy must preserve the public Host header.

**4. Start the dashboard.** Install Chromium on the host if you want browser filling, then start the dashboard.

```bash
.venv/bin/python -m playwright install --with-deps chromium
./jobbot.sh ui
```

The launcher loads the repository's `.env` when present, and file assignments take precedence. On deployments configured through host settings, leave the file absent. If startup still reports a MongoDB error, check the connection URI and database user's permissions in the [account guide](docs/accounts.md).

**5. Sign in and set up your profile.** Open the printed HTTPS URL and choose **Continue with Google**. Open **Profile** to enter your details and scan preferences. Save a resume key for each variant, then upload its PDF under that key. Hosted mode reads the uploaded PDFs.

In **Jobs**, try **Dry run** first. **Fill for review** asks for approval to submit. Enable **Auto-apply to selected roles** for verified submissions with a configured model. In **Runs**, choose **Take control** when a live run pauses, then **Return control and recheck** to resume review. You can handle employer sign-in or CAPTCHA on that same page if the site supports the hosted browser. Dry-run previews are read-only. See the [dashboard guide](docs/dashboard.md).

## Optional model setup

| Choice | Setup | Options |
| --- | --- | --- |
| Keyword ranking | `./jobbot.sh rank --llm none` | No API key or model download |
| Ollama | Start Ollama and run `ollama pull qwen2.5:7b` | Default provider. Set `JOBBOT_MODEL` or `OLLAMA_HOST` to override the local defaults |
| OpenAI | Set `JOBBOT_LLM_PROVIDER=openai` and `OPENAI_API_KEY` | Defaults to `gpt-4.1-mini`. Override with `OPENAI_MODEL` |

Automatic submission requires a working configured model to approve each required step. If ranking fails with the selected model, Jobbot can fall back to keywords. OpenAI mode sends candidate facts, resume text, and relevant application questions or review values to the API. Jobbot extracts relevant fields from the form before sending them. See [privacy and data handling](docs/privacy.md).

<details>
<summary>Installing Ollama, configuring OpenAI, and checking the connection</summary>

On macOS with Homebrew:

```bash
brew install ollama
brew services start ollama
ollama pull qwen2.5:7b
```

For OpenAI, create an [API key](https://platform.openai.com/api-keys) and configure API billing separately from ChatGPT. Use the host's secret settings or a Codespaces secret named `OPENAI_API_KEY`. Restart the Codespace after adding a secret. Set `JOBBOT_LLM_PROVIDER=openai` in the environment or `.env`. For a local shell, run `export JOBBOT_LLM_PROVIDER=openai`. The CLI also supports `--llm openai`, `--llm ollama`, and `--model` on model-enabled commands.

To load settings from a private file for a **local CLI** command, copy and edit [`.env.example`](.env.example). Keep MongoDB settings commented for local CLI use.

```bash
cp -n .env.example .env
chmod 600 .env
# Edit .env, then load it for this shell.
set -a
source ./.env
set +a
./jobbot.sh doctor
```

For OpenAI, `doctor` checks that the key is configured. To test an API request, scan and add a resume, then run `./jobbot.sh rank --limit 1` with an unranked role available. Choose the provider explicitly to switch between Ollama and OpenAI.

</details>

## Optional Gmail sync

| Workflow | Setup | Gmail access |
| --- | --- | --- |
| Hosted dashboard | Enable the Gmail API for the hosted OAuth project, sign in, then choose **Actions → Connect Gmail** | Read-only access. No local port forward |
| Local CLI | Enable the Gmail API and create a Google **Desktop app** OAuth client | Full mailbox access. Jobbot can label used verification emails and mark them read |

For a Google OAuth app in Testing, add your Gmail address as a test user. For an external hosted app in Testing, Gmail refresh tokens expire after seven days. Reconnect when prompted.

<details>
<summary>Local Gmail commands and Codespaces port forwarding</summary>

Keep the Desktop app JSON outside Git.

```bash
./jobbot.sh gmail login --client "$HOME/.jobbot/gmail_client.json"
./jobbot.sh gmail status
./jobbot.sh track sync-gmail
```

If running the CLI in a Codespace, leave the sign-in command running. Privately forward the loopback port shown in the current Google link to the same port on the machine running your browser. Use VS Code Desktop or run `gh codespace ports forward PORT:PORT -c CODESPACE_NAME` on that machine. Get the name with `echo "$CODESPACE_NAME"` inside the Codespace. If the local port is busy, check whether VS Code is already forwarding it.

Run `./jobbot.sh gmail logout` to disconnect the CLI. See [Gmail tracking](docs/tracking.md) for imports, scopes, and duplicate matching.

</details>

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

The CLI and tracker live in `jobbot/`, browser automation in `jobbot/apply/`, and the dashboard in `jobbot/ui/`. Job sources live in [the ATS registry](references/ats-registry.json) and [the target company list](target-companies.md). Read [CONTRIBUTING.md](CONTRIBUTING.md) before changing the registry or form-filling code.

```bash
.venv/bin/python -m pip install pyflakes mongomock
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pyflakes jobbot tests
.venv/bin/python -m unittest discover -s tests -v
```

Browser tests use local fixture forms and dashboard responses. Set `JOBBOT_REQUIRE_BROWSER_TESTS=1` to make a missing Chromium installation fail the suite, as it does in CI. On Linux, install with `python -m playwright install --with-deps chromium` if system libraries are missing. Account tests use mocked Google and MongoDB.

## License

[MIT](LICENSE) © 2026 Saurabh Maurya
