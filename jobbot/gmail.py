"""Read-only Gmail access through Google's OAuth sign-in, for syncing application emails.

You sign in on Google's own page in your browser; jobbot never sees your Google
password. It asks only for the read-only scope (gmail.readonly), keeps the token in
~/.jobbot/gmail_token.json (readable only by you), and `jobbot gmail logout` revokes it.

One-time setup (Google requires every app that reads Gmail to have its own client):
  1. https://console.cloud.google.com/ -> create a project -> enable the "Gmail API".
  2. Google Auth Platform -> Branding: app name "jobbot", your email. Audience: External,
     and add your own Gmail address as a test user.
  3. Clients -> Create client -> "Desktop app" -> download the JSON.
  4. Save it as ~/.jobbot/gmail_client.json (or pass --client FILE to `jobbot gmail login`).

Standard library only.
"""

import base64
import hashlib
import http.server
import json
import re
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from . import paths

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://gmail.googleapis.com/gmail/v1/users/me"

# Finds acknowledgements, rejections, assessments and interview invitations; job-board
# newsletters and alerts are excluded.
DEFAULT_QUERY = (
    '(subject:("thank you for applying" OR "thank you for your application" OR "thanks for applying" OR '
    '"application received" OR "your application" OR "update on your application" OR "thank you for your interest" '
    'OR interview OR assessment) OR "we have received your application" OR "not to move forward") '
    "-from:linkedin.com -from:indeed.com -from:naukri.com -from:glassdoor.com -category:promotions -in:sent"
)


class GmailError(Exception):
    pass


def client_path():
    return paths.HOME / "gmail_client.json"


def token_path():
    return paths.HOME / "gmail_token.json"


def _post(url, data):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise GmailError(f"Google returned {e.code}: {e.read().decode(errors='replace')[:300]}") from None


def load_client(path=None):
    path = Path(path or client_path())
    if not path.exists():
        raise GmailError(
            f"No OAuth client at {path}. Create a 'Desktop app' OAuth client in Google Cloud "
            "(see `jobbot gmail login --help` or the README) and save its JSON there.")
    data = json.loads(path.read_text())
    info = data.get("installed") or data.get("web") or data
    if not info.get("client_id"):
        raise GmailError(f"{path} does not look like a Google OAuth client file.")
    return {"client_id": info["client_id"], "client_secret": info.get("client_secret", "")}


def _save_token(token):
    paths.ensure_home()
    path = token_path()
    path.write_text(json.dumps(token))
    os.chmod(path, 0o600)


def is_connected():
    return token_path().exists()


def auth_url(client, redirect_uri, challenge, state):
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client["client_id"], "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "code_challenge": challenge,
        "code_challenge_method": "S256", "state": state,
    })


def pkce_pair():
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def login(client_file=None, open_browser=True, timeout=300):
    """Run Google's sign-in in the browser and store a read-only refresh token."""
    client = load_client(client_file)
    if client_file:
        paths.ensure_home()
        client_path().write_text(Path(client_file).read_text())
        os.chmod(client_path(), 0o600)
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state", [None])[0] != state:
                self.send_response(400)
                self.end_headers()
                return
            result.update({k: v[0] for k, v in query.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            ok = "code" in result
            self.wfile.write((
                "<h2>jobbot is connected to Gmail (read-only).</h2><p>You can close this tab.</p>" if ok else
                f"<h2>Gmail sign-in did not complete: {result.get('error', 'unknown error')}</h2>").encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    url = auth_url(client, redirect_uri, challenge, state)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    print("Opening Google sign-in in your browser. If it does not open, visit:\n" + url)
    if open_browser:
        webbrowser.open(url)
    thread.join(timeout)
    server.server_close()
    if "code" not in result:
        raise GmailError(f"Sign-in did not complete ({result.get('error', 'timed out')}).")
    token = _post(TOKEN_URL, {
        "client_id": client["client_id"], "client_secret": client["client_secret"], "code": result["code"],
        "code_verifier": verifier, "grant_type": "authorization_code", "redirect_uri": redirect_uri,
    })
    if "refresh_token" not in token:
        raise GmailError("Google did not return a refresh token; run `jobbot gmail logout` and log in again.")
    token["expires_at"] = time.time() + int(token.get("expires_in", 3600)) - 60
    _save_token(token)
    return profile_email()


def access_token():
    if not token_path().exists():
        raise GmailError("Gmail is not connected. Run `jobbot gmail login`.")
    token = json.loads(token_path().read_text())
    if token.get("expires_at", 0) > time.time():
        return token["access_token"]
    client = load_client()
    fresh = _post(TOKEN_URL, {"client_id": client["client_id"], "client_secret": client["client_secret"],
                              "refresh_token": token["refresh_token"], "grant_type": "refresh_token"})
    token.update(fresh)
    token["expires_at"] = time.time() + int(fresh.get("expires_in", 3600)) - 60
    _save_token(token)
    return token["access_token"]


def _get(path, params=None):
    url = f"{API}/{path}" + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token()}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise GmailError(f"Gmail API returned {e.code}: {e.read().decode(errors='replace')[:300]}") from None


def profile_email():
    return _get("profile").get("emailAddress", "")


def search(query=DEFAULT_QUERY, days=60, limit=1000, on_progress=None):
    """Metadata of matching messages: sender, subject, snippet, date. Bodies are never downloaded."""
    q = f"{query} newer_than:{int(days)}d" if days else query
    ids, page = [], None
    while len(ids) < limit:
        params = {"q": q, "maxResults": min(500, limit - len(ids))}
        if page:
            params["pageToken"] = page
        data = _get("messages", params)
        ids += [m["id"] for m in data.get("messages", [])]
        page = data.get("nextPageToken")
        if not page:
            break
    out = []
    for i, mid in enumerate(ids, 1):
        msg = _get(f"messages/{mid}", {"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]})
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        out.append({
            "id": mid, "sender": headers.get("from", ""), "subject": headers.get("subject", ""),
            "snippet": msg.get("snippet", ""), "labelIds": msg.get("labelIds", []),
            "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(msg.get("internalDate", "0")) / 1000)),
        })
        if on_progress and i % 25 == 0:
            on_progress(i, len(ids))
    return out


CODE_QUERY = 'newer_than:1d (code OR otp OR passcode OR "verification" OR verify OR "one-time" OR "one time")'
# "Your verification code is 482913", "482913 is your code", "OTP: 4829", "Use code AB3D9KQ2"
CODE_RES = [
    re.compile(r"(?:code|otp|passcode|pin|password)\b[^A-Za-z0-9]{0,40}?(?:is|:|-)?\s*\b([A-Z0-9]{4,8})\b", re.I),
    re.compile(r"\b([A-Z0-9]{4,8})\b\s+(?:is|as)\s+your\b[^.]{0,30}?(?:code|otp|passcode|pin)", re.I),
]


def extract_code(text):
    """The verification code in an email's subject or text, or None. Codes contain at least one digit."""
    for rx in CODE_RES:
        for m in rx.finditer(text or ""):
            code = m.group(1)
            if re.search(r"\d", code) and not re.fullmatch(r"(19|20)\d\d", code):
                return code
    return None


def _body_text(msg):
    """Plain text of a message (used only for the one verification email whose preview had no code)."""
    parts, out = [msg.get("payload", {})], []
    while parts:
        part = parts.pop()
        parts += part.get("parts", []) or []
        data = (part.get("body") or {}).get("data")
        if data and part.get("mimeType", "").startswith("text/"):
            text = base64.urlsafe_b64decode(data + "==").decode("utf-8", "replace")
            out.append(re.sub(r"<[^>]+>", " ", text) if "html" in part.get("mimeType", "") else text)
    return re.sub(r"\s+", " ", " ".join(out))


def latest_code(since, hint="", wait=90, poll=5):
    """Wait up to `wait` seconds for a verification email received after `since` (epoch seconds) and return
    its code. Emails whose sender mentions `hint` (e.g. the site's name) are preferred. None if none arrives.

    Reads the subject and preview first; only when those hold no code is that one email's text read.
    """
    deadline = time.time() + wait
    while True:
        ids = [m["id"] for m in _get("messages", {"q": CODE_QUERY, "maxResults": 10}).get("messages", [])]
        found = []
        for mid in ids:
            meta = _get(f"messages/{mid}", {"format": "metadata", "metadataHeaders": ["From", "Subject"]})
            if int(meta.get("internalDate", "0")) / 1000 < since:
                continue
            headers = {h["name"].lower(): h["value"] for h in meta.get("payload", {}).get("headers", [])}
            sender = headers.get("from", "")
            code = extract_code(headers.get("subject", "") + " . " + meta.get("snippet", ""))
            if not code:
                code = extract_code(_body_text(_get(f"messages/{mid}", {"format": "full"})))
            if code:
                found.append((bool(hint) and hint.lower() in sender.lower(), int(meta["internalDate"]), code))
        if found:
            return max(found)[2]   # from the site if any, newest first
        if time.time() >= deadline:
            return None
        time.sleep(poll)


def logout():
    if not token_path().exists():
        return False
    token = json.loads(token_path().read_text())
    try:
        _post(REVOKE_URL, {"token": token.get("refresh_token") or token.get("access_token", "")})
    except GmailError:
        pass  # already revoked or expired; delete locally anyway
    token_path().unlink()
    return True
