# Private Jobbot account with MongoDB

The dashboard requires a hosted account. It supports one configured owner per deployment. Open the same
HTTPS dashboard from any browser and sign in with Google. Your profile, uploaded resume PDFs,
Gmail authorization, job list, and application tracker survive host restarts and replacement.
Local CLI commands are still available without hosted settings.

## Set up the hosted dashboard

1. Create a MongoDB database and a database user with read/write access to that database. Use a
   TLS-enabled connection and restrict database network access to the machines that need it.
2. Run the dashboard on a Render Web Service or in GitHub Codespaces. Jobbot uses Render's
   built-in `RENDER_EXTERNAL_URL` or the HTTPS URL for the Codespace's forwarded dashboard port.
   On Render, use the service's default `onrender.com` URL. In a Codespace, keep the port private
   and use its GitHub forwarded HTTPS URL. In Google Cloud, enable the Gmail API and create a
   **Web application** OAuth client. Register the exact dashboard URL plus
   `/auth/google/callback` as the redirect URI. If you replace the Codespace or change its port,
   update that URI in Google Cloud. The Desktop app JSON is only for local CLI sign-in.
   Add your account as a test user if your OAuth app is in Testing.
3. Set these variables on the host. See [the environment template](../.env.example) for the variable names. Keep the URI, OAuth client secret, and data key in the host's
   secret settings. Never put them in the repository or your candidate profile.

   | Variable | What to set |
   | --- | --- |
   | `JOBBOT_MONGODB_URI` | MongoDB connection URI |
   | `JOBBOT_MONGODB_DB` | Database name, defaults to `jobbot` |
   | `JOBBOT_DATA_KEY` | A Fernet key. Generate once with the command below and keep a secure backup |
   | `JOBBOT_ACCOUNT_EMAIL` | The one verified Google email allowed to sign in and connect Gmail |
   | `JOBBOT_GOOGLE_CLIENT_ID` | Web application OAuth client ID |
   | `JOBBOT_GOOGLE_CLIENT_SECRET` | Web application OAuth client secret |
   | `JOBBOT_BIND` | Set to `0.0.0.0` behind your HTTPS hosting proxy |
   | `OPENAI_API_KEY` and `JOBBOT_LLM_PROVIDER=openai` | Optional hosted ranking with OpenAI |

   ```bash
   python -m pip install -r requirements.txt
   python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
   ./jobbot.sh ui
   ```

   In a Codespace, put the settings in the repository's Git-ignored `.env`. `./jobbot.sh ui` loads
   the file automatically and its assignments take precedence. Hosted services can supply settings
   through the deployment environment when the file is absent.
   Run with Python 3.11 or newer. The app listens on the host's `PORT` variable when set, or
   `8765` otherwise. Use an HTTPS reverse proxy that preserves the dashboard's public Host
   header. Don't expose the backend port directly. Redeploy with the **same data key and owner
   email**. Changing the email selects a different account, and losing the key means losing access
   to encrypted data. Use the same HTTPS URL from each device.

4. Open the dashboard and select **Continue with Google**. Dashboard sign-in does not request
   Gmail permission. For mail imports, open **Actions → Connect Gmail** and grant read-only Gmail
   access. There is no localhost callback or port forwarding in hosted mode. If Google expires
   or revokes the authorization, reconnect from the dashboard. For External OAuth apps in
   **Testing**, Google expires Gmail refresh tokens after seven days.
5. Fill in your details under **Profile**. New accounts start with a blank profile. To add a resume, save its key under `resumes:`, then upload
   the PDF using that key. Hosted mode ignores local YAML file paths. For example:

   ```yaml
   resumes:
     backend:
       focus: Java, Spring Boot, distributed systems
   ```

### Manage uploaded resumes

Open **Profile → Resume library**. **Upload PDF** suggests a display name and key from the
filename, lets you use it for ranking immediately, and asks before replacing an existing file.
**View PDF** previews it inside Jobbot with a download fallback. Under **⋯**, use **Rename** to
change the display name or key. A key change moves the profile entry and preserves its focus.
**Remove from ranking** keeps the file. **Delete PDF** asks for confirmation and removes it from
ranking if necessary, without changing past applications. YAML remains under **Advanced settings**.

## What's local and what's hosted

Hosted Jobbot can scan, rank, import Gmail, track applications, and fill forms using the
account's profile and uploaded resumes. Install the browser in the Codespace or deployment:

```bash
.venv/bin/python -m playwright install --with-deps chromium
./jobbot.sh ui
```

Select a role in **Jobs** and choose **Dry run** or **Fill for review**. Follow the page preview,
filled answers, and prompts in **Runs**. Dry runs never submit. Live runs require manual approval
before Jobbot submits. In a live run, **Take control** opens the current Chromium page when
Jobbot pauses for review, sign-in, or CAPTCHA. Click, scroll, or type in the view. **Return control
and recheck** reads the current page without overwriting manual edits. During takeover you are
operating the employer page directly, so actions you take there can send data to the employer.
Dry runs provide a read-only live view and cannot send clicks or keystrokes to the employer page.
If the employer blocks the hosted browser or requires an unsupported interaction, finish on the
employer site.

Browser sessions are temporary. MongoDB keeps run outcomes, but not screenshots or field audit
history. Learned answers from hosted runs are not saved back to the profile. The **Logs** tab is
for local browser logs. Use **Runs** for hosted browser progress and **Actions** for task output.
The local tracker remains separate, and hosted browser runs start from the dashboard.

MongoDB stores encrypted account data and refresh tokens. The app keeps the key outside MongoDB.
Session IDs are stored as hashes and expire after seven days. Signing out ends that browser session.
Disconnecting Gmail revokes the stored grant and removes it from the account.

The tracker uses its existing SQLite queries against a temporary in-memory database. MongoDB holds
the durable snapshots, and version checks reject stale writes rather than replacing newer updates.
This private single-owner mode supports a tracker up to 9 MiB and PDFs up to 5 MiB each. Retry
a rejected update after reloading the latest data. This is not a shared multi-user deployment.
