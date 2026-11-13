"""Private hosted mode. MongoDB is the durable store, not the host filesystem."""

import datetime as dt
import hashlib
import json
import os
import secrets
from functools import lru_cache
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

MAX_PDF = 5 * 1024 * 1024
MAX_TRACKER = 9 * 1024 * 1024  # leaves room for encryption overhead and BSON's 16 MiB cap


class AccountError(RuntimeError):
    pass


def enabled():
    return bool(os.getenv("JOBBOT_MONGODB_URI"))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Account:
    def __init__(self, db, key, email, origin, oauth_client):
        self.db, self.cipher = db, Fernet(key)
        self.email, self.origin, self.oauth_client = email, origin, oauth_client
        self.owner = digest(email)
        self.callback = origin + "/auth/google/callback"

    def initialize(self):
        for name in ("sessions", "oauth_flows"):
            self.db[name].create_index("expires", expireAfterSeconds=0)

    def _seal(self, name, value):
        return self.cipher.encrypt((self.owner + ":" + name + "\0").encode() + value)

    def _unseal(self, name, value):
        try:
            decoded = self.cipher.decrypt(value)
            prefix = (self.owner + ":" + name + "\0").encode()
            if not decoded.startswith(prefix):
                raise InvalidToken()
            return decoded[len(prefix):]
        except InvalidToken as exc:
            raise AccountError("Stored account data could not be decrypted. Check the data encryption key.") from exc

    def read(self, name):
        row = self.db.account_data.find_one({"_id": self.owner + ":" + name})
        return (self._unseal(name, row["value"]), row["version"]) if row else (None, "")

    def write(self, name, value, expected=None):
        key = self.owner + ":" + name
        version = secrets.token_hex(16)
        row = {"_id": key, "version": version, "value": self._seal(name, value)}
        if expected == "":
            try:
                self.db.account_data.insert_one(row)
            except DuplicateKeyError as exc:
                raise AccountError("Account data changed. Reload and try again.") from exc
        elif expected is not None:
            result = self.db.account_data.replace_one({"_id": key, "version": expected}, row)
            if not result.matched_count:
                raise AccountError("Account data changed. Reload and try again.")
        else:
            self.db.account_data.replace_one({"_id": key}, row, upsert=True)
        return version

    def remove(self, name, expected=None):
        query = {"_id": self.owner + ":" + name}
        if expected is not None:
            query["version"] = expected
        return bool(self.db.account_data.delete_one(query).deleted_count)

    def get_json(self, name):
        value, _ = self.read(name)
        return json.loads(value) if value is not None else None

    def put_json(self, name, value):
        self.write(name, json.dumps(value).encode())

    def session(self, token):
        return bool(token and self.db.sessions.find_one({"_id": digest(token), "owner": self.owner,
                                                          "expires": {"$gt": dt.datetime.now(dt.timezone.utc)}}))

    def new_session(self):
        token = secrets.token_urlsafe(32)
        self.db.sessions.insert_one({"_id": digest(token), "owner": self.owner,
                                     "expires": dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7)})
        return token

    def logout(self, token):
        if token:
            self.db.sessions.delete_one({"_id": digest(token), "owner": self.owner})

    def begin(self, mode, session=""):
        from . import gmail

        state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        verifier, challenge = gmail.pkce_pair()
        self.db.oauth_flows.insert_one({"_id": digest(state), "browser": digest(browser), "owner": self.owner,
                                        "mode": mode, "session": digest(session),
                                        "verifier": self._seal("oauth:" + state, verifier.encode()),
                                        "expires": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)})
        scope = "openid email" + (" " + gmail.READ_SCOPE if mode == "gmail" else "")
        return gmail.auth_url(self.oauth_client, self.callback, challenge, state, scope=scope,
                              offline=mode == "gmail"), browser

    def finish(self, state, browser, code, session):
        from . import gmail

        if not (state and browser and code):
            raise AccountError("Google sign-in did not complete. Please try again.")
        row = self.db.oauth_flows.find_one_and_delete({"_id": digest(state), "browser": digest(browser),
                                                        "owner": self.owner, "session": digest(session),
                                                        "expires": {"$gt": dt.datetime.now(dt.timezone.utc)}})
        if not row or (row["mode"] == "gmail" and not self.session(session)):
            raise AccountError("Google sign-in expired or does not match this browser. Please try again.")
        verifier = self._unseal("oauth:" + state, row["verifier"]).decode()
        token = gmail.exchange(self.oauth_client, self.callback, verifier, code)
        identity = gmail.google_identity(token["access_token"])
        if identity.get("email_verified") is not True or identity.get("email", "").casefold() != self.email:
            raise AccountError("This Google account is not the configured Jobbot owner.")
        if row["mode"] == "gmail":
            if gmail.READ_SCOPE not in token.get("scope", "").split() or not token.get("refresh_token"):
                raise AccountError("Google did not grant offline Gmail access. Reconnect and approve Gmail access.")
            self.put_json("gmail", token)
            return None
        return self.new_session()


@lru_cache(maxsize=1)
def current():
    def required(name):
        value = os.getenv(name, "").strip()
        if not value:
            raise AccountError(f"Set {name} for hosted account mode.")
        return value

    origin = required("JOBBOT_PUBLIC_URL").rstrip("/")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment
            or parsed.username or parsed.password or parsed.netloc != parsed.hostname):
        raise AccountError("JOBBOT_PUBLIC_URL must be an HTTPS origin with no port or path.")
    client = MongoClient(required("JOBBOT_MONGODB_URI"), serverSelectionTimeoutMS=5000)
    db = client[os.getenv("JOBBOT_MONGODB_DB", "jobbot")]
    try:
        return Account(db, required("JOBBOT_DATA_KEY"), required("JOBBOT_ACCOUNT_EMAIL").casefold(), origin,
                       {"client_id": required("JOBBOT_GOOGLE_CLIENT_ID"),
                        "client_secret": required("JOBBOT_GOOGLE_CLIENT_SECRET")})
    except ValueError as exc:
        raise AccountError("Invalid hosted account configuration. Check the encryption key and database name.") from exc


def import_local():
    """Seed empty hosted records from this trusted CLI machine; never overwrite saved data."""
    import sqlite3
    from pathlib import Path

    import yaml

    from . import paths, profile

    account = current()
    source = paths.PROFILE if paths.PROFILE.exists() else paths.LEGACY_PROFILE
    files = {}
    if source.exists():
        raw = source.read_bytes()
        if len(raw) > 2_000_000:
            raise AccountError("The local profile is too large.")
        data = yaml.safe_load(raw)
        if not isinstance(data, dict) or not isinstance(data.get("personal"), dict):
            raise AccountError("The local profile must contain a personal section.")
        for key, spec in (data.get("resumes") or {}).items():
            if not profile.valid_resume_key(key):
                raise AccountError("A local resume key is invalid. Use letters, numbers, underscores or dashes.")
            path = Path(os.path.expanduser(str(spec.get("path", "") if isinstance(spec, dict) else spec)))
            if not path.is_absolute():
                path = source.parent / path
            if not path.is_file():
                raise AccountError(f"Local resume '{key}' was not found. Fix its profile path before importing.")
            if path.stat().st_size > MAX_PDF:
                raise AccountError(f"Local resume '{key}' exceeds 5 MiB.")
            pdf = path.read_bytes()
            if not pdf.startswith(b"%PDF-"):
                raise AccountError(f"Local resume '{key}' is not a PDF.")
            files["resume:" + key] = pdf
        files["profile"] = raw
    if paths.DB.is_file():
        with sqlite3.connect(":memory:") as snapshot:
            local = sqlite3.connect(paths.DB.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                local.backup(snapshot)
                data = snapshot.serialize()
            finally:
                local.close()
        if len(data) > MAX_TRACKER:
            raise AccountError("The local tracker exceeds the hosted tracker limit.")
        files["tracker"] = data
    imported, skipped = [], []
    for name, value in files.items():
        if account.read(name)[1]:
            skipped.append(name)
        else:
            account.write(name, value, expected="")
            imported.append(name)
    return imported, skipped
