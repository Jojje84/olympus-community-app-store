#!/usr/bin/env python3
import base64
import hashlib
import hmac
import http.cookies
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "0.1.0-beta.5"
APP_ROOT = Path(os.environ.get("FORGECORE_APP_ROOT", "/data"))
STORAGE_ROOT = Path(os.environ.get("FORGECORE_STORAGE_ROOT", "/storage"))
CONFIG_DIR = APP_ROOT / "config"
STATE_DIR = APP_ROOT / "state"
SESSIONS_DIR = STATE_DIR / "sessions"
PENDING_DIR = STATE_DIR / "github-pending"
RUNNER_REQUEST_DIR = STATE_DIR / "runner-requests"
RUNNER_RESET_DIR = STATE_DIR / "runner-resets"
RUNNER_ROOT = STORAGE_ROOT / "runners"
LOG_DIR = STORAGE_ROOT / "logs"

AUTH_FILE = CONFIG_DIR / "auth.json"
AUTH_SECRET_FILE = STATE_DIR / ".auth-secret"
GITHUB_APP_FILE = CONFIG_DIR / "github-app.json"
GITHUB_ACCOUNT_FILE = CONFIG_DIR / "github-account.json"
GITHUB_TOKEN_FILE = STATE_DIR / ".github-user-token.json"
INSTANCE_FILE = STATE_DIR / "instance-id"
RUNNER_OBSERVATIONS_FILE = STATE_DIR / "runner-observations.json"
RUNNER_OBSERVATIONS_LOCK = threading.Lock()

SESSION_COOKIE = "forgecore_session"
SESSION_TTL = 7 * 24 * 3600
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RUNNER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$")

GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2026-03-10"
GITHUB_HOMEPAGE = "https://github.com/Jojje84/ForgeCore"


def now_epoch():
    return int(time.time())


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ensure_dirs():
    for path in (CONFIG_DIR, STATE_DIR, SESSIONS_DIR, PENDING_DIR, RUNNER_REQUEST_DIR, RUNNER_RESET_DIR, RUNNER_ROOT, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)
    if not INSTANCE_FILE.exists():
        write_text_private(INSTANCE_FILE, secrets.token_hex(4) + "\n")


def write_text_private(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def write_json_private(path, value):
    write_text_private(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError, TypeError):
        return default


def slug(value):
    result = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return result or "runner"


def auth_secret():
    if not AUTH_SECRET_FILE.exists():
        write_text_private(AUTH_SECRET_FILE, secrets.token_hex(32) + "\n")
    return AUTH_SECRET_FILE.read_text(encoding="utf-8").strip().encode()


def password_hash(password, salt=None):
    salt_bytes = base64.urlsafe_b64decode(salt.encode()) if salt else secrets.token_bytes(18)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt_bytes, 260000)
    return base64.urlsafe_b64encode(salt_bytes).decode(), base64.urlsafe_b64encode(digest).decode()


def verify_password(password, salt, expected):
    _, actual = password_hash(password, salt)
    return hmac.compare_digest(actual, expected)


def session_path(token):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return SESSIONS_DIR / (token_hash + ".json")


def create_session(username):
    token = secrets.token_urlsafe(32)
    write_json_private(session_path(token), {
        "username": username,
        "created": now_epoch(),
        "expires": now_epoch() + SESSION_TTL,
    })
    return token


def session_user(token):
    if not token:
        return None
    value = read_json(session_path(token))
    if not isinstance(value, dict):
        return None
    if int(value.get("expires") or 0) < now_epoch():
        session_path(token).unlink(missing_ok=True)
        return None
    return str(value.get("username") or "") or None


def github_headers(token=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ForgeCore-Clean-Beta",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def github_json(method, url, data=None, token=None, form=False):
    body = None
    headers = github_headers(token)
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            headers["Accept"] = "application/json"
        else:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
            message = payload.get("message") or payload.get("error_description") or payload.get("error")
        except ValueError:
            message = raw.strip()
        raise RuntimeError(message or ("GitHub HTTP " + str(exc.code))) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Could not reach GitHub: " + str(exc.reason)) from exc


def clean_origin(value):
    try:
        parsed = urllib.parse.urlparse(str(value))
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return parsed.scheme + "://" + parsed.netloc


def pending_path(state):
    return PENDING_DIR / (state + ".json")


def github_app_config():
    value = read_json(GITHUB_APP_FILE)
    return value if isinstance(value, dict) else {}


def github_account():
    value = read_json(GITHUB_ACCOUNT_FILE)
    return value if isinstance(value, dict) else {}


def github_token_record():
    value = read_json(GITHUB_TOKEN_FILE)
    return value if isinstance(value, dict) else {}


def save_github_token(payload):
    created = now_epoch()
    record = {
        "access_token": str(payload.get("access_token") or ""),
        "refresh_token": str(payload.get("refresh_token") or ""),
        "token_type": str(payload.get("token_type") or "bearer"),
        "scope": str(payload.get("scope") or ""),
        "created_epoch": created,
        "expires_epoch": created + int(payload.get("expires_in") or 0) if payload.get("expires_in") else 0,
        "refresh_expires_epoch": created + int(payload.get("refresh_token_expires_in") or 0) if payload.get("refresh_token_expires_in") else 0,
    }
    if not record["access_token"]:
        raise RuntimeError("GitHub did not return a user access token.")
    write_json_private(GITHUB_TOKEN_FILE, record)
    return record


def github_user_token():
    record = github_token_record()
    token = str(record.get("access_token") or "")
    if not token:
        raise RuntimeError("GitHub is not connected.")
    expires = int(record.get("expires_epoch") or 0)
    if not expires or expires - now_epoch() > 300:
        return token

    app = github_app_config()
    refresh = str(record.get("refresh_token") or "")
    if not refresh or not app.get("client_id") or not app.get("client_secret"):
        raise RuntimeError("GitHub authorization expired. Reconnect GitHub.")

    payload = github_json("POST", "https://github.com/login/oauth/access_token", {
        "client_id": app["client_id"],
        "client_secret": app["client_secret"],
        "grant_type": "refresh_token",
        "refresh_token": refresh,
    }, form=True)
    return save_github_token(payload)["access_token"]


def github_installations(token):
    result = []
    page = 1
    while page <= 10:
        payload = github_json("GET", f"{GITHUB_API}/user/installations?per_page=100&page={page}", token=token)
        items = payload.get("installations") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            break
        result.extend(items)
        if len(items) < 100:
            break
        page += 1
    return result


def github_repositories():
    token = github_user_token()
    account = github_account()
    installation_id = account.get("installation_id")
    if not installation_id:
        raise RuntimeError("GitHub App installation is missing.")
    repositories = []
    page = 1
    while page <= 10:
        payload = github_json("GET", f"{GITHUB_API}/user/installations/{installation_id}/repositories?per_page=100&page={page}", token=token)
        items = payload.get("repositories") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            break
        for item in items:
            full_name = str(item.get("full_name") or "")
            if not REPO_RE.fullmatch(full_name):
                continue
            repositories.append({
                "fullName": full_name,
                "name": str(item.get("name") or full_name.rsplit("/", 1)[-1]),
                "owner": str((item.get("owner") or {}).get("login") or full_name.split("/", 1)[0]),
                "private": bool(item.get("private")),
                "archived": bool(item.get("archived")),
                "defaultBranch": str(item.get("default_branch") or "main"),
                "htmlUrl": str(item.get("html_url") or ("https://github.com/" + full_name)),
                "runnerSettingsUrl": "https://github.com/" + full_name + "/settings/actions/runners",
            })
        if len(items) < 100:
            break
        page += 1
    repositories.sort(key=lambda item: item["fullName"].lower())
    return repositories


def update_runner_observations(repository, runners):
    with RUNNER_OBSERVATIONS_LOCK:
        observations = read_json(RUNNER_OBSERVATIONS_FILE, {})
        if not isinstance(observations, dict):
            observations = {}
        observed_at = utc_now()
        for runner in runners:
            runner_id = runner.get("id")
            if runner_id is None:
                continue
            key = repository + ":" + str(runner_id)
            previous = observations.get(key)
            if not isinstance(previous, dict):
                previous = {}
            first_seen = str(previous.get("firstSeenAt") or observed_at)
            last_online = str(previous.get("lastOnlineAt") or "")
            if runner.get("online"):
                last_online = observed_at
            record = {
                "repository": repository,
                "runnerId": runner_id,
                "name": str(runner.get("name") or ""),
                "firstSeenAt": first_seen,
                "lastSeenAt": observed_at,
                "lastOnlineAt": last_online,
                "status": str(runner.get("status") or "offline"),
            }
            observations[key] = record
            runner["firstSeenAt"] = first_seen
            runner["lastSeenAt"] = observed_at
            runner["lastOnlineAt"] = last_online
        if len(observations) > 1500:
            ordered = sorted(
                observations.items(),
                key=lambda item: str((item[1] or {}).get("lastSeenAt") or ""),
                reverse=True,
            )
            observations = dict(ordered[:1000])
        write_json_private(RUNNER_OBSERVATIONS_FILE, observations)


def github_runners(repository):
    if not REPO_RE.fullmatch(repository):
        raise ValueError("Invalid repository.")
    token = github_user_token()
    payload = github_json("GET", f"{GITHUB_API}/repos/{repository}/actions/runners?per_page=100", token=token)
    items = payload.get("runners") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        items = []
    runners = []
    for item in items:
        labels = [
            str(label.get("name"))
            for label in (item.get("labels") or [])
            if isinstance(label, dict) and label.get("name")
        ]
        status = str(item.get("status") or "offline").lower()
        runners.append({
            "id": item.get("id"),
            "name": str(item.get("name") or "GitHub runner"),
            "os": str(item.get("os") or ""),
            "status": status,
            "online": status == "online",
            "busy": bool(item.get("busy")),
            "labels": labels,
            "forgecoreRunner": any(label.lower() == "forgecore" for label in labels),
        })

    local_by_name = {
        item["name"]: item["id"]
        for item in list_runners()
        if item.get("repository") == repository and item.get("name")
    }
    forgecore_candidates = [
        runner for runner in runners
        if runner.get("forgecoreRunner") or str(runner.get("name") or "").lower().startswith("forgecore")
    ]
    duplicate_count = len(forgecore_candidates)
    for runner in runners:
        local_id = local_by_name.get(runner.get("name"))
        runner["managedByForgeCore"] = bool(local_id)
        runner["localRunnerId"] = local_id or ""
        runner["possibleDuplicate"] = bool(duplicate_count > 1 and runner in forgecore_candidates)
        runner["duplicateCount"] = duplicate_count if runner["possibleDuplicate"] else 0

    update_runner_observations(repository, runners)
    return {
        "repository": repository,
        "runners": runners,
        "settingsUrl": "https://github.com/" + repository + "/settings/actions/runners",
        "newRunnerUrl": "https://github.com/" + repository + "/settings/actions/runners/new",
        "possibleForgeCoreDuplicates": duplicate_count > 1,
        "forgeCoreCandidateCount": duplicate_count,
    }


def github_runner_token(repository, kind):
    if not REPO_RE.fullmatch(repository):
        raise ValueError("Invalid repository.")
    endpoint = "registration-token" if kind == "register" else "remove-token"
    return github_json("POST", f"{GITHUB_API}/repos/{repository}/actions/runners/{endpoint}", {}, token=github_user_token())


def validate_runner_name(value):
    name = str(value or "").strip()
    if not RUNNER_NAME_RE.fullmatch(name):
        raise ValueError("Runner name must be 1-64 characters and use letters, numbers, spaces, dots, underscores or hyphens.")
    return name


def list_runners():
    result = []
    try:
        dirs = sorted([path for path in RUNNER_ROOT.iterdir() if path.is_dir()])
    except OSError:
        dirs = []
    for directory in dirs:
        meta = read_json(directory / ".forgecore-runner.json")
        if not isinstance(meta, dict) or meta.get("kind") != "ForgeCoreRunner":
            continue
        runner_id = directory.name
        runtime = read_json(STATE_DIR / f"runner-{runner_id}.json", {})
        result.append({
            "id": runner_id,
            "repository": str(meta.get("repository") or ""),
            "name": str(meta.get("name") or ("ForgeCore-" + runner_id)),
            "phase": str(runtime.get("phase") or "offline"),
            "message": str(runtime.get("message") or ""),
            "online": bool(runtime.get("online")),
            "pid": runtime.get("pid"),
        })
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "ForgeCoreClean/0.1"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def parse_cookies(self):
        cookie = http.cookies.SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        return cookie

    def current_user(self):
        cookie = self.parse_cookies()
        morsel = cookie.get(SESSION_COOKIE)
        return session_user(morsel.value if morsel else "")

    def require_user(self):
        user = self.current_user()
        if not user:
            self.json_response(401, {"error": "Authentication required"})
            return None
        return user

    def json_body(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        if length > 2_000_000:
            raise ValueError("Request too large.")
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError):
            raise ValueError("Invalid JSON.")
        return value if isinstance(value, dict) else {}

    def json_response(self, status, value, headers=None):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        for key, val in (headers or {}).items():
            self.send_header(key, val)
        self.end_headers()
        self.wfile.write(body)

    def html_response(self, status, html, headers=None):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        for key, val in (headers or {}).items():
            self.send_header(key, val)
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def set_session_cookie(self, token):
        return f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL}"

    def clear_session_cookie(self):
        return f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        try:
            if path == "/health":
                self.json_response(200, {"ok": True, "version": VERSION})
                return
            if path == "/":
                index = Path("/runtime/index.html")
                self.html_response(200, index.read_text(encoding="utf-8"))
                return
            if path == "/api/session":
                auth = read_json(AUTH_FILE, {})
                self.json_response(200, {
                    "setupRequired": not bool(auth.get("username")),
                    "authenticated": bool(self.current_user()),
                    "username": self.current_user() or "",
                    "version": VERSION,
                })
                return
            if path == "/api/github/status":
                if not self.require_user():
                    return
                app = github_app_config()
                account = github_account()
                connected = bool(account.get("login") and GITHUB_TOKEN_FILE.exists())
                self.json_response(200, {
                    "registered": bool(app.get("client_id")),
                    "connected": connected,
                    "account": {
                        "login": account.get("login", ""),
                        "avatarUrl": account.get("avatar_url", ""),
                        "installationId": account.get("installation_id"),
                    } if connected else None,
                    "app": {
                        "slug": app.get("slug", ""),
                        "htmlUrl": app.get("html_url", ""),
                    } if app else None,
                })
                return
            if path == "/api/github/repositories":
                if not self.require_user():
                    return
                self.json_response(200, {"repositories": github_repositories()})
                return
            if path == "/api/github/runners":
                if not self.require_user():
                    return
                repository = str(params.get("repository", [""])[0])
                self.json_response(200, github_runners(repository))
                return
            if path == "/api/runners":
                if not self.require_user():
                    return
                runners = list_runners()
                self.json_response(200, {"runners": runners})
                return
            if path.startswith("/api/runners/") and path.endswith("/diagnostics"):
                if not self.require_user():
                    return
                runner_id = path[len("/api/runners/"):-len("/diagnostics")].strip("/")
                if not SLUG_RE.fullmatch(runner_id):
                    self.json_response(400, {"error": "Invalid Runner id"})
                    return
                runner = next((item for item in list_runners() if item["id"] == runner_id), None)
                if not runner:
                    self.json_response(404, {"error": "Runner not found"})
                    return
                self.json_response(200, {
                    "runner": runner,
                    "runnerLog": (LOG_DIR / f"runner-{runner_id}.log").read_text(encoding="utf-8", errors="replace")[-16000:] if (LOG_DIR / f"runner-{runner_id}.log").exists() else "",
                    "registrationLog": (LOG_DIR / f"runner-registration-{runner_id}.log").read_text(encoding="utf-8", errors="replace")[-16000:] if (LOG_DIR / f"runner-registration-{runner_id}.log").exists() else "",
                })
                return

            if path == "/github/manifest/callback":
                state = str(params.get("state", [""])[0])
                code = str(params.get("code", [""])[0])
                pending = read_json(pending_path(state))
                if not state or not code or not isinstance(pending, dict) or pending.get("kind") != "manifest":
                    self.redirect("/?github_error=manifest")
                    return
                if int(pending.get("expires") or 0) < now_epoch():
                    pending_path(state).unlink(missing_ok=True)
                    self.redirect("/?github_error=expired")
                    return

                created = github_json("POST", f"{GITHUB_API}/app-manifests/{urllib.parse.quote(code)}/conversions", {})
                config = {
                    "app_id": created.get("id"),
                    "client_id": created.get("client_id"),
                    "client_secret": created.get("client_secret"),
                    "slug": created.get("slug"),
                    "html_url": created.get("html_url"),
                    "created_at": utc_now(),
                    "origin": pending.get("origin"),
                }
                if not config["app_id"] or not config["client_id"] or not config["client_secret"] or not config["slug"]:
                    raise RuntimeError("GitHub App registration did not return the required credentials.")
                write_json_private(GITHUB_APP_FILE, config)
                pending_path(state).unlink(missing_ok=True)
                self.redirect("https://github.com/apps/" + urllib.parse.quote(str(config["slug"])) + "/installations/new")
                return

            if path == "/github/install/callback":
                app = github_app_config()
                installation_id = str(params.get("installation_id", [""])[0])
                origin = clean_origin(app.get("origin"))
                if not app.get("client_id") or not installation_id or not origin:
                    self.redirect("/?github_error=install")
                    return
                state = secrets.token_urlsafe(24)
                write_json_private(pending_path(state), {
                    "kind": "oauth",
                    "installation_id": installation_id,
                    "origin": origin,
                    "expires": now_epoch() + 3600,
                })
                redirect_uri = origin + "/github/oauth/callback"
                query = urllib.parse.urlencode({
                    "client_id": app["client_id"],
                    "redirect_uri": redirect_uri,
                    "state": state,
                })
                self.redirect("https://github.com/login/oauth/authorize?" + query)
                return

            if path == "/github/oauth/callback":
                app = github_app_config()
                state = str(params.get("state", [""])[0])
                code = str(params.get("code", [""])[0])
                pending = read_json(pending_path(state))
                if not isinstance(pending, dict) or pending.get("kind") != "oauth" or int(pending.get("expires") or 0) < now_epoch():
                    self.redirect("/?github_error=oauth_state")
                    return
                origin = clean_origin(pending.get("origin"))
                if not origin:
                    self.redirect("/?github_error=origin")
                    return
                token_payload = github_json("POST", "https://github.com/login/oauth/access_token", {
                    "client_id": app.get("client_id"),
                    "client_secret": app.get("client_secret"),
                    "code": code,
                    "redirect_uri": origin + "/github/oauth/callback",
                }, form=True)
                record = save_github_token(token_payload)
                token = record["access_token"]
                user = github_json("GET", f"{GITHUB_API}/user", token=token)
                expected_installation = int(pending.get("installation_id") or 0)
                installations = github_installations(token)
                installation = next((
                    item for item in installations
                    if int(item.get("id") or 0) == expected_installation and int(item.get("app_id") or 0) == int(app.get("app_id") or 0)
                ), None)
                if installation is None:
                    raise RuntimeError("The GitHub App installation could not be verified for this account.")
                write_json_private(GITHUB_ACCOUNT_FILE, {
                    "login": str(user.get("login") or ""),
                    "avatar_url": str(user.get("avatar_url") or ""),
                    "user_id": user.get("id"),
                    "installation_id": installation.get("id"),
                    "installation_account": (installation.get("account") or {}).get("login"),
                    "connected_at": utc_now(),
                })
                pending_path(state).unlink(missing_ok=True)
                self.redirect("/?github=connected")
                return

            self.json_response(404, {"error": "Not found"})
        except (ValueError, RuntimeError) as exc:
            if path.startswith("/github/"):
                self.redirect("/?github_error=" + urllib.parse.quote(str(exc)[:120]))
            else:
                self.json_response(400, {"error": str(exc)})
        except Exception as exc:
            print("GET error:", repr(exc), flush=True)
            self.json_response(500, {"error": "ForgeCore encountered an unexpected error."})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            data = self.json_body()

            if path == "/api/account/setup":
                existing = read_json(AUTH_FILE, {})
                if existing.get("username"):
                    self.json_response(409, {"error": "ForgeCore account already exists."})
                    return
                username = str(data.get("username") or "").strip()
                password = str(data.get("password") or "")
                if len(username) < 2 or len(username) > 40:
                    raise ValueError("Choose a username between 2 and 40 characters.")
                if len(password) < 10:
                    raise ValueError("Choose a password with at least 10 characters.")
                salt, digest = password_hash(password)
                write_json_private(AUTH_FILE, {"username": username, "salt": salt, "passwordHash": digest, "createdAt": utc_now()})
                token = create_session(username)
                self.json_response(201, {"ok": True, "username": username}, {"Set-Cookie": self.set_session_cookie(token)})
                return

            if path == "/api/login":
                auth = read_json(AUTH_FILE, {})
                username = str(data.get("username") or "").strip()
                password = str(data.get("password") or "")
                if not auth.get("username") or username != auth.get("username") or not verify_password(password, auth.get("salt", ""), auth.get("passwordHash", "")):
                    self.json_response(401, {"error": "Incorrect username or password."})
                    return
                token = create_session(username)
                self.json_response(200, {"ok": True, "username": username}, {"Set-Cookie": self.set_session_cookie(token)})
                return

            if path == "/api/logout":
                cookie = self.parse_cookies()
                morsel = cookie.get(SESSION_COOKIE)
                if morsel:
                    session_path(morsel.value).unlink(missing_ok=True)
                self.json_response(200, {"ok": True}, {"Set-Cookie": self.clear_session_cookie()})
                return

            if not self.require_user():
                return

            if path == "/api/github/manifest/start":
                origin = clean_origin(data.get("origin"))
                if not origin:
                    raise ValueError("ForgeCore could not determine its browser address.")
                existing_app = github_app_config()
                if existing_app.get("slug") and existing_app.get("client_id"):
                    existing_app["origin"] = origin
                    write_json_private(GITHUB_APP_FILE, existing_app)
                    self.json_response(200, {
                        "mode": "redirect",
                        "url": "https://github.com/apps/" + urllib.parse.quote(str(existing_app["slug"])) + "/installations/new",
                    })
                    return
                state = secrets.token_urlsafe(24)
                instance_id = INSTANCE_FILE.read_text(encoding="utf-8").strip()
                write_json_private(pending_path(state), {
                    "kind": "manifest",
                    "origin": origin,
                    "expires": now_epoch() + 3600,
                })
                manifest = {
                    "name": "ForgeCore " + instance_id[:6].upper(),
                    "url": GITHUB_HOMEPAGE,
                    "description": "Private GitHub integration for one ForgeCore Umbrel installation.",
                    "hook_attributes": {"url": origin + "/api/github/webhook", "active": False},
                    "redirect_url": origin + "/github/manifest/callback",
                    "callback_urls": [origin + "/github/oauth/callback"],
                    "setup_url": origin + "/github/install/callback",
                    "setup_on_update": True,
                    "public": False,
                    "default_permissions": {
                        "metadata": "read",
                        "contents": "read",
                        "administration": "write",
                    },
                    "default_events": [],
                }
                self.json_response(200, {
                    "action": "https://github.com/settings/apps/new?state=" + urllib.parse.quote(state),
                    "manifest": manifest,
                })
                return

            if path == "/api/github/disconnect":
                GITHUB_ACCOUNT_FILE.unlink(missing_ok=True)
                GITHUB_TOKEN_FILE.unlink(missing_ok=True)
                self.json_response(200, {"ok": True})
                return

            if path == "/api/runners":
                repository = str(data.get("repository") or "").strip()
                replace_existing = data.get("replaceExisting") is True
                if not REPO_RE.fullmatch(repository):
                    raise ValueError("Choose a valid GitHub repository.")
                runner_id = slug(repository)
                exists = any(item["id"] == runner_id for item in list_runners())
                if exists and not replace_existing:
                    self.json_response(409, {"error": "A local ForgeCore Runner already exists for this repository."})
                    return
                requested_name = str(data.get("name") or ("ForgeCore-" + runner_id)).strip()
                requested_name = validate_runner_name(requested_name)
                reg = github_runner_token(repository, "register")
                write_json_private(RUNNER_REQUEST_DIR / (runner_id + ".json"), {
                    "kind": "ForgeCoreRunnerRequest",
                    "repository": repository,
                    "registrationToken": reg.get("token"),
                    "runnerName": requested_name,
                    "replaceExisting": replace_existing,
                    "requestedAt": utc_now(),
                })
                self.json_response(202, {"ok": True, "id": runner_id, "name": requested_name})
                return

            if path.startswith("/api/runners/") and path.endswith("/rename"):
                runner_id = path[len("/api/runners/"):-len("/rename")].strip("/")
                if not SLUG_RE.fullmatch(runner_id):
                    raise ValueError("Invalid Runner id.")
                runner = next((item for item in list_runners() if item["id"] == runner_id), None)
                if not runner:
                    self.json_response(404, {"error": "Runner not found"})
                    return
                requested_name = validate_runner_name(data.get("name"))
                if requested_name == runner.get("name"):
                    self.json_response(200, {"ok": True, "id": runner_id, "name": requested_name})
                    return
                remove = github_runner_token(runner["repository"], "remove")
                reg = github_runner_token(runner["repository"], "register")
                write_json_private(RUNNER_RESET_DIR / (runner_id + ".json"), {
                    "kind": "ForgeCoreRunnerReset",
                    "repository": runner["repository"],
                    "removeToken": remove.get("token"),
                    "requestedAt": utc_now(),
                    "reason": "rename",
                })
                write_json_private(RUNNER_REQUEST_DIR / (runner_id + ".json"), {
                    "kind": "ForgeCoreRunnerRequest",
                    "repository": runner["repository"],
                    "registrationToken": reg.get("token"),
                    "runnerName": requested_name,
                    "replaceExisting": True,
                    "requestedAt": utc_now(),
                })
                self.json_response(202, {"ok": True, "id": runner_id, "name": requested_name})
                return

            self.json_response(404, {"error": "Not found"})
        except (ValueError, RuntimeError) as exc:
            self.json_response(400, {"error": str(exc)})
        except Exception as exc:
            print("POST error:", repr(exc), flush=True)
            self.json_response(500, {"error": "ForgeCore encountered an unexpected error."})

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if not self.require_user():
                return
            if path.startswith("/api/github/runners/"):
                runner_id = path[len("/api/github/runners/"):].strip("/")
                repository = str(urllib.parse.parse_qs(parsed.query).get("repository", [""])[0]).strip()
                if not runner_id.isdigit() or not REPO_RE.fullmatch(repository):
                    raise ValueError("Invalid GitHub runner or repository.")
                github_json(
                    "DELETE",
                    f"{GITHUB_API}/repos/{repository}/actions/runners/{runner_id}",
                    token=github_user_token(),
                )
                self.json_response(200, {"ok": True, "runnerId": int(runner_id)})
                return
            if path.startswith("/api/runners/"):
                runner_id = path[len("/api/runners/"):].strip("/")
                if not SLUG_RE.fullmatch(runner_id):
                    raise ValueError("Invalid Runner id.")
                runner = next((item for item in list_runners() if item["id"] == runner_id), None)
                if not runner:
                    self.json_response(404, {"error": "Runner not found"})
                    return
                remove = github_runner_token(runner["repository"], "remove")
                write_json_private(RUNNER_RESET_DIR / (runner_id + ".json"), {
                    "kind": "ForgeCoreRunnerReset",
                    "repository": runner["repository"],
                    "removeToken": remove.get("token"),
                    "requestedAt": utc_now(),
                    "reason": "remove",
                })
                self.json_response(202, {"ok": True})
                return
            self.json_response(404, {"error": "Not found"})
        except (ValueError, RuntimeError) as exc:
            self.json_response(400, {"error": str(exc)})
        except Exception as exc:
            print("DELETE error:", repr(exc), flush=True)
            self.json_response(500, {"error": "ForgeCore encountered an unexpected error."})


if __name__ == "__main__":
    ensure_dirs()
    port = int(os.environ.get("PORT", "8080"))
    print(f"ForgeCore Clean Beta {VERSION} listening on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
