#!/usr/bin/env python3
import base64
import binascii
import fcntl
import hashlib
import json
import os
import re
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP = Path(os.environ.get("FORGECORE_APP_ROOT", "/forgecore/app"))
DASHBOARD_ARTIFACT = Path(os.environ.get("FORGECORE_DASHBOARD_B64", "/forgecore/runtime/dashboard-v2.b64"))
CFG = APP / "config"
V1_RUNNER_CONFIG_DIR = CFG / "runners"
V1_GLOBAL_CONFIG = CFG / "forgecore.env"
AD = CFG / "apps"
PD = CFG / "publish-presets"
ST = APP / "state"
JD = ST / "jobs"
RUNNER_REQUEST_DIR = ST / "runner-requests"
NATIVE_CAPABILITIES = ST / "native-capabilities.json"
GLOBAL_CONFIG = CFG / "global.json"
GLOBAL_MIGRATION_MARKER = ST / "global-settings-v2.migrated.json"
V1_RUNNER_APP_MIGRATION_MARKER = ST / "v1-runner-apps.migrated.json"
RUNNER_METADATA_NAME = ".forgecore-runner.json"
STORAGE = Path(os.environ.get("FORGECORE_STORAGE_ROOT", "/forgecore/storage"))
STORAGE_DISPLAY = os.environ.get("FORGECORE_STORAGE_DISPLAY", str(STORAGE))
STORAGE_HOST_PATH = os.environ.get("FORGECORE_STORAGE_HOST_PATH", STORAGE_DISPLAY)
STORAGE_RESOLUTION = os.environ.get("FORGECORE_STORAGE_RESOLUTION", "unknown")
RUNTIME_VERSION = os.environ.get("FORGECORE_RUNTIME_VERSION", "dev")
RUNNER_ENGINE = STORAGE / "runners"
MANAGER_ARTIFACT = Path("/forgecore/inspect/runner-manager.b64")
COMPOSE_VERSION = "5.5.1"
WEB_BUILD = "0.1.0-beta.54"

def current_dashboard_payload():
    encoded = DASHBOARD_ARTIFACT.read_bytes().strip()
    payload = base64.b64decode(encoded, validate=True)
    payload.decode("utf-8")
    return payload


REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
NAME = re.compile(r"^[A-Za-z0-9_.-]{0,63}$")
LABELS = re.compile(r"^[A-Za-z0-9_.-]+(?:,[A-Za-z0-9_.-]+)*$")
TOKEN = re.compile(r"^[A-Za-z0-9_-]{10,300}$")
SLUG_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
STORE_ID = re.compile(r"^olympus-[a-z0-9]+(?:-[a-z0-9]+)*$")
BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")
JOB_ID = re.compile(r"^[a-z0-9][a-z0-9-]{5,127}$")
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SECRET_ENV_REF = re.compile(r"^secret://env/[A-Za-z_][A-Za-z0-9_]*$")
EXECUTORS = {"forgecore-native", "github-actions"}
TARGETS = {"amd64", "arm64", "armv7"}
JOB_TYPES = {"build", "publish", "build-and-publish"}
JOB_STATUSES = {"queued", "preparing", "running", "succeeded", "failed", "cancelled"}
JOB_STAGE_NAMES = {"source", "build", "test", "verify", "package", "release", "store"}
JOB_STAGE_STATUSES = {"pending", "running", "succeeded", "failed", "skipped", "cancelled"}
JOB_TRANSITIONS = {
    "queued": {"preparing", "cancelled"},
    "preparing": {"running", "failed", "cancelled"},
    "running": {"succeeded", "failed", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}
JOB_LOCK = threading.RLock()
JOB_LOCK_STATE = threading.local()
JOB_LOCK_FILE = ST / ".jobs.lock"

@contextmanager
def job_state_lock():
    """Serialize job mutations across the dashboard and native worker processes."""
    with JOB_LOCK:
        depth = getattr(JOB_LOCK_STATE, "depth", 0)
        if depth == 0:
            ST.mkdir(parents=True, exist_ok=True)
            fd = os.open(JOB_LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                os.chmod(JOB_LOCK_FILE, 0o600)
            except OSError:
                pass
            fcntl.flock(fd, fcntl.LOCK_EX)
            JOB_LOCK_STATE.fd = fd
        JOB_LOCK_STATE.depth = depth + 1
        try:
            yield
        finally:
            remaining = getattr(JOB_LOCK_STATE, "depth", 1) - 1
            JOB_LOCK_STATE.depth = remaining
            if remaining == 0:
                fd = getattr(JOB_LOCK_STATE, "fd", None)
                if fd is not None:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    finally:
                        os.close(fd)
                for attr in ("fd", "depth"):
                    if hasattr(JOB_LOCK_STATE, attr):
                        delattr(JOB_LOCK_STATE, attr)


ICON_SVG = r'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 126 126" role="img" aria-labelledby="title"><title id="title">ForgeCore</title><image width="126" height="126" href="data:image/png;base64,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"/></svg>
'''


def env(path):
    out = {}
    try:
        for raw in path.read_text().splitlines():
            s = raw.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            v = v.strip()
            out[k.strip()] = v[1:-1] if len(v) > 1 and v[0] == v[-1] == '"' else v
    except OSError:
        pass
    return out

def slug(repo):
    return re.sub(r"[^a-z0-9]+", "-", repo.lower()).strip("-")

def int_setting(config, key, default):
    try:
        return int(config.get(key, default))
    except (TypeError, ValueError):
        return default

def v1_cleanup_values(config=None, fallback=None):
    config = config if isinstance(config, dict) else env(V1_GLOBAL_CONFIG)
    fallback = fallback if isinstance(fallback, dict) else {}
    return {
        "intervalHours": max(1, int_setting(config, "CLEANUP_INTERVAL_HOURS", fallback.get("intervalHours", 168))),
        "cacheMaxAgeDays": max(1, int_setting(config, "CACHE_MAX_AGE_DAYS", fallback.get("cacheMaxAgeDays", 14))),
        "workspaceMaxAgeDays": max(1, int_setting(config, "WORKSPACE_MAX_AGE_DAYS", fallback.get("workspaceMaxAgeDays", 30))),
        "diskThresholdPercent": max(50, min(99, int_setting(config, "DISK_CLEANUP_THRESHOLD_PERCENT", fallback.get("diskThresholdPercent", 85)))),
        "buildkitKeepStorageGB": max(1, min(1000, int_setting(config, "BUILDKIT_KEEP_STORAGE_GB", fallback.get("buildkitKeepStorageGB", 50)))),
    }

def default_global_config(v1_config=None):
    release_repository = os.environ.get("FORGECORE_RELEASE_REPOSITORY", "Jojje84/Olympus-Releases").strip()
    store_repository = os.environ.get("FORGECORE_COMMUNITY_STORE_REPOSITORY", "Jojje84/olympus-community-app-store").strip()
    if not REPO.fullmatch(release_repository):
        release_repository = "Jojje84/Olympus-Releases"
    if not REPO.fullmatch(store_repository):
        store_repository = "Jojje84/olympus-community-app-store"
    storage_root = str(STORAGE_HOST_PATH or STORAGE).strip() or str(STORAGE)
    return {
        "schemaVersion": 1,
        "kind": "ForgeCoreGlobal",
        "id": "global",
        "github": {
            "provider": "github",
            "actionsRunner": {"enabled": True},
        },
        "releases": {
            "provider": "olympus-releases",
            "repository": release_repository,
        },
        "communityStore": {
            "provider": "olympus-community-app-store",
            "repository": store_repository,
        },
        "runtime": {
            "defaultExecutor": "forgecore-native",
            "isolatedDocker": True,
            "buildImage": "python:3.13",
            "networkMode": "bridge",
            "memoryMiB": 4096,
            "cpus": 2,
            "pidsLimit": 512,
        },
        "storage": {"root": storage_root},
        "cleanup": v1_cleanup_values(v1_config),
        "security": {
            "trustedRepositoriesOnly": True,
            "allowUntrustedForks": False,
            "publishRequiresExplicitPermission": True,
        },
    }

def _validate_secret_ref(value, label):
    value = str(value or "").strip()
    if not SECRET_ENV_REF.fullmatch(value):
        raise ValueError(f"{label} must use secret://env/<ENV_NAME>.")
    return value

def _validate_int(value, label, lo, hi=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer.")
    if value < lo or (hi is not None and value > hi):
        upper = f" and {hi}" if hi is not None else ""
        raise ValueError(f"{label} must be between {lo}{upper}.")
    return value

def validate_global_config(data):
    require_keys(
        data,
        {"schemaVersion", "kind", "id", "github", "releases", "communityStore", "runtime", "storage", "cleanup", "security"},
        {"schemaVersion", "kind", "id", "github", "releases", "communityStore", "runtime", "storage", "cleanup", "security"},
        "Global configuration",
    )
    if data.get("schemaVersion") != 1 or data.get("kind") != "ForgeCoreGlobal" or data.get("id") != "global":
        raise ValueError("Global configuration schemaVersion/kind/id is invalid.")

    github = data["github"]
    require_keys(github, {"provider", "actionsRunner"}, {"provider", "authRef", "actionsRunner"}, "Global github")
    if github.get("provider") != "github":
        raise ValueError("Global github.provider must be github.")
    actions_runner = github["actionsRunner"]
    require_keys(actions_runner, {"enabled"}, {"enabled"}, "Global github.actionsRunner")
    if not isinstance(actions_runner.get("enabled"), bool):
        raise ValueError("Global github.actionsRunner.enabled must be true or false.")
    normalized_github = {"provider": "github", "actionsRunner": {"enabled": actions_runner["enabled"]}}
    if "authRef" in github:
        normalized_github["authRef"] = _validate_secret_ref(github["authRef"], "Global github.authRef")

    releases = data["releases"]
    require_keys(releases, {"provider", "repository"}, {"provider", "repository", "authRef", "signing"}, "Global releases")
    if releases.get("provider") != "olympus-releases":
        raise ValueError("Global releases.provider must be olympus-releases.")
    release_repository = str(releases.get("repository") or "").strip()
    if not REPO.fullmatch(release_repository):
        raise ValueError("Global releases.repository must look like owner/repository.")
    normalized_releases = {"provider": "olympus-releases", "repository": release_repository}
    if "authRef" in releases:
        normalized_releases["authRef"] = _validate_secret_ref(releases["authRef"], "Global releases.authRef")
    if "signing" in releases:
        signing = releases["signing"]
        require_keys(
            signing,
            {"provider", "privateKeyRef", "publicKeyRef", "passwordRef", "encoding"},
            {"provider", "privateKeyRef", "publicKeyRef", "passwordRef", "encoding"},
            "Global releases.signing",
        )
        if signing.get("provider") != "sigstore-key":
            raise ValueError("Global releases.signing.provider must be sigstore-key.")
        if signing.get("encoding") not in {"base64", "plain"}:
            raise ValueError("Global releases.signing.encoding must be base64 or plain.")
        normalized_releases["signing"] = {
            "provider": "sigstore-key",
            "privateKeyRef": _validate_secret_ref(signing["privateKeyRef"], "Global releases.signing.privateKeyRef"),
            "publicKeyRef": _validate_secret_ref(signing["publicKeyRef"], "Global releases.signing.publicKeyRef"),
            "passwordRef": _validate_secret_ref(signing["passwordRef"], "Global releases.signing.passwordRef"),
            "encoding": signing["encoding"],
        }

    store = data["communityStore"]
    require_keys(store, {"provider", "repository"}, {"provider", "repository", "authRef"}, "Global communityStore")
    if store.get("provider") != "olympus-community-app-store":
        raise ValueError("Global communityStore.provider must be olympus-community-app-store.")
    store_repository = str(store.get("repository") or "").strip()
    if not REPO.fullmatch(store_repository):
        raise ValueError("Global communityStore.repository must look like owner/repository.")
    normalized_store = {"provider": "olympus-community-app-store", "repository": store_repository}
    if "authRef" in store:
        normalized_store["authRef"] = _validate_secret_ref(store["authRef"], "Global communityStore.authRef")

    runtime = data["runtime"]
    require_keys(
        runtime,
        {"defaultExecutor", "isolatedDocker"},
        {"defaultExecutor", "isolatedDocker", "buildImage", "networkMode", "memoryMiB", "cpus", "pidsLimit"},
        "Global runtime",
    )
    if runtime.get("defaultExecutor") not in EXECUTORS:
        raise ValueError("Global runtime.defaultExecutor is invalid.")
    if not isinstance(runtime.get("isolatedDocker"), bool):
        raise ValueError("Global runtime.isolatedDocker must be true or false.")
    normalized_runtime = {
        "defaultExecutor": runtime["defaultExecutor"],
        "isolatedDocker": runtime["isolatedDocker"],
    }
    if "buildImage" in runtime:
        image = str(runtime.get("buildImage") or "").strip()
        if not image or len(image) > 255 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@-]*", image):
            raise ValueError("Global runtime.buildImage is invalid.")
        normalized_runtime["buildImage"] = image
    if "networkMode" in runtime:
        if runtime["networkMode"] not in {"bridge", "none"}:
            raise ValueError("Global runtime.networkMode is invalid.")
        normalized_runtime["networkMode"] = runtime["networkMode"]
    if "memoryMiB" in runtime:
        normalized_runtime["memoryMiB"] = _validate_int(runtime["memoryMiB"], "Global runtime.memoryMiB", 128, 32768)
    if "cpus" in runtime:
        cpus = runtime["cpus"]
        if isinstance(cpus, bool) or not isinstance(cpus, (int, float)) or cpus < 0.25 or cpus > 32:
            raise ValueError("Global runtime.cpus must be between 0.25 and 32.")
        normalized_runtime["cpus"] = cpus
    if "pidsLimit" in runtime:
        normalized_runtime["pidsLimit"] = _validate_int(runtime["pidsLimit"], "Global runtime.pidsLimit", 64, 4096)

    storage = data["storage"]
    require_keys(storage, {"root"}, {"root"}, "Global storage")
    storage_root = str(storage.get("root") or "").strip()
    if not storage_root:
        raise ValueError("Global storage.root must not be empty.")

    cleanup = data["cleanup"]
    require_keys(
        cleanup,
        {"intervalHours", "cacheMaxAgeDays", "workspaceMaxAgeDays", "diskThresholdPercent", "buildkitKeepStorageGB"},
        {"intervalHours", "cacheMaxAgeDays", "workspaceMaxAgeDays", "diskThresholdPercent", "buildkitKeepStorageGB"},
        "Global cleanup",
    )
    normalized_cleanup = {
        "intervalHours": _validate_int(cleanup["intervalHours"], "Global cleanup.intervalHours", 1),
        "cacheMaxAgeDays": _validate_int(cleanup["cacheMaxAgeDays"], "Global cleanup.cacheMaxAgeDays", 1),
        "workspaceMaxAgeDays": _validate_int(cleanup["workspaceMaxAgeDays"], "Global cleanup.workspaceMaxAgeDays", 1),
        "diskThresholdPercent": _validate_int(cleanup["diskThresholdPercent"], "Global cleanup.diskThresholdPercent", 50, 99),
        "buildkitKeepStorageGB": _validate_int(cleanup["buildkitKeepStorageGB"], "Global cleanup.buildkitKeepStorageGB", 1, 1000),
    }

    security = data["security"]
    require_keys(
        security,
        {"trustedRepositoriesOnly", "allowUntrustedForks", "publishRequiresExplicitPermission"},
        {"trustedRepositoriesOnly", "allowUntrustedForks", "publishRequiresExplicitPermission"},
        "Global security",
    )
    for key in ("trustedRepositoriesOnly", "allowUntrustedForks", "publishRequiresExplicitPermission"):
        if not isinstance(security.get(key), bool):
            raise ValueError(f"Global security.{key} must be true or false.")

    return {
        "schemaVersion": 1,
        "kind": "ForgeCoreGlobal",
        "id": "global",
        "github": normalized_github,
        "releases": normalized_releases,
        "communityStore": normalized_store,
        "runtime": normalized_runtime,
        "storage": {"root": storage_root},
        "cleanup": normalized_cleanup,
        "security": {
            "trustedRepositoriesOnly": security["trustedRepositoriesOnly"],
            "allowUntrustedForks": security["allowUntrustedForks"],
            "publishRequiresExplicitPermission": security["publishRequiresExplicitPermission"],
        },
    }

def ensure_global_config():
    CFG.mkdir(parents=True, exist_ok=True)
    ST.mkdir(parents=True, exist_ok=True)
    first_migration = not GLOBAL_MIGRATION_MARKER.exists()
    v1_config = env(V1_GLOBAL_CONFIG) if first_migration and V1_GLOBAL_CONFIG.exists() else {}

    if GLOBAL_CONFIG.exists():
        candidate = read_json(GLOBAL_CONFIG)
    else:
        candidate = default_global_config(v1_config)

    cleanup = candidate.get("cleanup") if isinstance(candidate, dict) else None
    if first_migration and v1_config:
        candidate["cleanup"] = v1_cleanup_values(v1_config, cleanup)
    elif isinstance(cleanup, dict) and "buildkitKeepStorageGB" not in cleanup:
        candidate["cleanup"] = dict(cleanup)
        candidate["cleanup"]["buildkitKeepStorageGB"] = 50

    normalized = validate_global_config(candidate)
    # Always persist the normalized v2 document. During the one-time v1 import
    # candidate has already been mutated in memory, so comparing it with
    # normalized cannot tell whether the on-disk global.json still needs update.
    write_json_atomic(GLOBAL_CONFIG, normalized)

    if first_migration:
        marker = {
            "schemaVersion": 1,
            "kind": "ForgeCoreV1GlobalMigration",
            "migratedAt": utc_now(),
            "globalRevision": config_revision(normalized),
            "v1Source": "config/forgecore.env" if V1_GLOBAL_CONFIG.exists() else None,
        }
        write_json_atomic(GLOBAL_MIGRATION_MARKER, marker)
        append_activity("settings", "v1 global settings migration completed")

    if V1_GLOBAL_CONFIG.exists():
        try:
            V1_GLOBAL_CONFIG.unlink()
        except OSError:
            pass
    return normalized

def olympus_releases_integration(global_config=None):
    global_config = global_config if isinstance(global_config, dict) else ensure_global_config()
    releases = global_config.get("releases") if isinstance(global_config, dict) else {}
    releases = releases if isinstance(releases, dict) else {}
    auth_ref = str(releases.get("authRef") or "")
    signing = releases.get("signing") if isinstance(releases.get("signing"), dict) else None
    return {
        "provider": "olympus-releases",
        "repository": str(releases.get("repository") or ""),
        "authRef": auth_ref,
        "credentialReferenceConfigured": bool(auth_ref and SECRET_ENV_REF.fullmatch(auth_ref)),
        "signingConfigured": signing is not None,
        "signing": dict(signing) if signing is not None else None,
        "configurationReady": bool(auth_ref and SECRET_ENV_REF.fullmatch(auth_ref)),
    }

def save_olympus_releases_integration(data):
    require_keys(
        data,
        {"repository", "authRef", "signingEnabled"},
        {"repository", "authRef", "signingEnabled", "signingEncoding", "privateKeyRef", "publicKeyRef", "passwordRef"},
        "Olympus Releases integration",
    )
    repository = str(data.get("repository") or "").strip()
    if not REPO.fullmatch(repository):
        raise ValueError("Olympus Releases repository must look like owner/repository.")
    auth_ref = str(data.get("authRef") or "").strip()
    if auth_ref:
        auth_ref = _validate_secret_ref(auth_ref, "Olympus Releases credential reference")
    signing_enabled = data.get("signingEnabled")
    if not isinstance(signing_enabled, bool):
        raise ValueError("Olympus Releases signingEnabled must be true or false.")

    releases = {"provider": "olympus-releases", "repository": repository}
    if auth_ref:
        releases["authRef"] = auth_ref
    if signing_enabled:
        encoding = str(data.get("signingEncoding") or "").strip()
        if encoding not in {"base64", "plain"}:
            raise ValueError("Olympus Releases signing encoding must be base64 or plain.")
        releases["signing"] = {
            "provider": "sigstore-key",
            "privateKeyRef": _validate_secret_ref(data.get("privateKeyRef"), "Olympus Releases private key reference"),
            "publicKeyRef": _validate_secret_ref(data.get("publicKeyRef"), "Olympus Releases public key reference"),
            "passwordRef": _validate_secret_ref(data.get("passwordRef"), "Olympus Releases password reference"),
            "encoding": encoding,
        }

    global_config = ensure_global_config()
    global_config["releases"] = releases
    global_config = validate_global_config(global_config)
    write_json_atomic(GLOBAL_CONFIG, global_config)
    append_activity("integration", f"Olympus Releases integration updated for {repository}")
    return olympus_releases_integration(global_config)

def community_app_store_integration(global_config=None):
    global_config = global_config if isinstance(global_config, dict) else ensure_global_config()
    store = global_config.get("communityStore") if isinstance(global_config, dict) else {}
    store = store if isinstance(store, dict) else {}
    auth_ref = str(store.get("authRef") or "")
    return {
        "provider": "olympus-community-app-store",
        "repository": str(store.get("repository") or ""),
        "authRef": auth_ref,
        "credentialReferenceConfigured": bool(auth_ref and SECRET_ENV_REF.fullmatch(auth_ref)),
        "configurationReady": bool(auth_ref and SECRET_ENV_REF.fullmatch(auth_ref)),
    }

def save_community_app_store_integration(data):
    require_keys(
        data,
        {"repository", "authRef"},
        {"repository", "authRef"},
        "Community App Store integration",
    )
    repository = str(data.get("repository") or "").strip()
    if not REPO.fullmatch(repository):
        raise ValueError("Community App Store repository must look like owner/repository.")
    auth_ref = str(data.get("authRef") or "").strip()
    if auth_ref:
        auth_ref = _validate_secret_ref(auth_ref, "Community App Store credential reference")

    store = {
        "provider": "olympus-community-app-store",
        "repository": repository,
    }
    if auth_ref:
        store["authRef"] = auth_ref

    global_config = ensure_global_config()
    global_config["communityStore"] = store
    global_config = validate_global_config(global_config)
    write_json_atomic(GLOBAL_CONFIG, global_config)
    append_activity("integration", f"Community App Store integration updated for {repository}")
    return community_app_store_integration(global_config)

def settings():
    global_config = ensure_global_config()
    cleanup = global_config["cleanup"]
    return {
        "cleanup_interval_days": max(1, cleanup["intervalHours"] // 24),
        "cache_max_age_days": cleanup["cacheMaxAgeDays"],
        "workspace_max_age_days": cleanup["workspaceMaxAgeDays"],
        "disk_cleanup_threshold_percent": cleanup["diskThresholdPercent"],
        "buildkit_keep_storage_gb": cleanup["buildkitKeepStorageGB"],
        "compose_version": COMPOSE_VERSION,
        "global_settings_source": "global.json",
        "global_settings_migrated": GLOBAL_MIGRATION_MARKER.exists(),
        "runtime": dict(global_config.get("runtime") or {}),
        "security": dict(global_config.get("security") or {}),
        "olympus_releases": olympus_releases_integration(global_config),
        "community_app_store": community_app_store_integration(global_config),
    }


def read_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Could not read {path.name}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} contains invalid JSON.") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object.")
    return data

def write_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    inherit_owner(tmp, path.parent)
    os.replace(tmp, path)

def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def config_revision(snapshot):
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()

def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()

def require_keys(data, required, allowed, label):
    if not isinstance(data, dict):
        raise ValueError(f"{label} must be an object.")
    missing = sorted(set(required) - set(data))
    unknown = sorted(set(data) - set(allowed))
    if missing:
        raise ValueError(f"{label} is missing: {', '.join(missing)}.")
    if unknown:
        raise ValueError(f"{label} has unknown fields: {', '.join(unknown)}.")

def validate_slug(value, label="id"):
    value = str(value or "").strip()
    if not SLUG_ID.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase slug.")
    return value

def validate_relative_path(value, label):
    value = str(value or "").strip()
    if not value or value.startswith("/") or "\\" in value:
        raise ValueError(f"{label} must be a relative POSIX path.")
    parts = [part for part in value.split("/") if part]
    if not parts or any(part in (".", "..") for part in parts):
        raise ValueError(f"{label} contains an invalid path segment.")
    return "/".join(parts)

def default_publish_preset():
    return {
        "schemaVersion": 1,
        "kind": "ForgeCorePublishPreset",
        "id": "olympus-default",
        "name": "Olympus default",
        "release": {
            "enabled": True,
            "repositoryRef": "global.releases",
            "channel": "stable",
            "tagPrefixTemplate": "{app.id}-",
            "updateChannel": True,
            "updateStableChannel": True,
        },
        "store": {
            "enabled": False,
            "repositoryRef": "global.communityStore",
            "mode": "pull-request",
            "directoryTemplate": "olympus-{app.id}",
        },
        "verification": {"sha256": True, "sigstore": True},
    }

def ensure_control_plane():
    AD.mkdir(parents=True, exist_ok=True)
    PD.mkdir(parents=True, exist_ok=True)
    JD.mkdir(parents=True, exist_ok=True)
    default_path = PD / "olympus-default.json"
    if not default_path.exists():
        write_json_atomic(default_path, default_publish_preset())

def validate_publish_preset(data):
    require_keys(
        data,
        {"schemaVersion", "kind", "id", "name", "release", "store", "verification"},
        {"schemaVersion", "kind", "id", "name", "release", "store", "verification"},
        "Publish preset",
    )
    if data.get("schemaVersion") != 1 or data.get("kind") != "ForgeCorePublishPreset":
        raise ValueError("Publish preset schemaVersion/kind is invalid.")
    preset_id = validate_slug(data.get("id"), "Publish preset id")
    name = str(data.get("name") or "").strip()
    if not name or len(name) > 100:
        raise ValueError("Publish preset name must be 1-100 characters.")

    release = data.get("release")
    require_keys(
        release,
        {"enabled", "repositoryRef", "channel", "tagPrefixTemplate"},
        {"enabled", "repositoryRef", "channel", "tagPrefixTemplate", "updateChannel", "updateStableChannel"},
        "Publish preset release",
    )
    if not isinstance(release.get("enabled"), bool):
        raise ValueError("release.enabled must be true or false.")
    if release.get("repositoryRef") != "global.releases":
        raise ValueError("release.repositoryRef must be global.releases.")
    if release.get("channel") not in {"stable", "beta", "prerelease"}:
        raise ValueError("release.channel is invalid.")
    tag_template = str(release.get("tagPrefixTemplate") or "").strip()
    if not tag_template or len(tag_template) > 120:
        raise ValueError("release.tagPrefixTemplate must be 1-120 characters.")
    if "updateChannel" in release and not isinstance(release.get("updateChannel"), bool):
        raise ValueError("release.updateChannel must be true or false.")
    if "updateStableChannel" in release and not isinstance(release.get("updateStableChannel"), bool):
        raise ValueError("release.updateStableChannel must be true or false.")
    if "updateChannel" in release:
        update_channel = release["updateChannel"]
    else:
        # Legacy Phase 3 presets may only contain updateStableChannel. Preserve
        # their stable-only behavior rather than enabling beta/prerelease feeds.
        update_channel = bool(release.get("updateStableChannel")) and release["channel"] == "stable"

    store = data.get("store")
    require_keys(
        store,
        {"enabled", "repositoryRef", "mode", "directoryTemplate"},
        {"enabled", "repositoryRef", "mode", "directoryTemplate"},
        "Publish preset store",
    )
    if not isinstance(store.get("enabled"), bool):
        raise ValueError("store.enabled must be true or false.")
    if store.get("repositoryRef") != "global.communityStore":
        raise ValueError("store.repositoryRef must be global.communityStore.")
    if store.get("mode") not in {"pull-request", "direct"}:
        raise ValueError("store.mode is invalid.")
    directory_template = str(store.get("directoryTemplate") or "").strip()
    if not directory_template or "/" in directory_template or "\\" in directory_template:
        raise ValueError("store.directoryTemplate must be a single directory template.")

    verification = data.get("verification")
    require_keys(
        verification,
        {"sha256", "sigstore"},
        {"sha256", "sigstore"},
        "Publish preset verification",
    )
    if not isinstance(verification.get("sha256"), bool) or not isinstance(verification.get("sigstore"), bool):
        raise ValueError("verification flags must be true or false.")

    return {
        "schemaVersion": 1,
        "kind": "ForgeCorePublishPreset",
        "id": preset_id,
        "name": name,
        "release": {
            "enabled": release["enabled"],
            "repositoryRef": "global.releases",
            "channel": release["channel"],
            "tagPrefixTemplate": tag_template,
            **({"updateChannel": update_channel} if "updateChannel" in release else {}),
            "updateStableChannel": (
                update_channel and release["channel"] == "stable"
                if "updateChannel" in release
                else bool(release.get("updateStableChannel", False))
            ),
        },
        "store": {
            "enabled": store["enabled"],
            "repositoryRef": "global.communityStore",
            "mode": store["mode"],
            "directoryTemplate": directory_template,
        },
        "verification": {
            "sha256": verification["sha256"],
            "sigstore": verification["sigstore"],
        },
    }

def publish_presets():
    ensure_control_plane()
    items = []
    errors = []
    for path in sorted(PD.glob("*.json")):
        try:
            items.append(validate_publish_preset(read_json(path)))
        except ValueError as exc:
            errors.append({"file": path.name, "error": str(exc)})
    return items, errors

def get_publish_preset(preset_id):
    preset_id = validate_slug(preset_id, "Publish preset id")
    path = PD / f"{preset_id}.json"
    if not path.exists():
        return None
    return validate_publish_preset(read_json(path))

def save_publish_preset(data):
    preset = validate_publish_preset(data)
    ensure_control_plane()
    write_json_atomic(PD / f"{preset['id']}.json", preset)
    append_activity("preset", f"Publish preset {preset['id']} saved")
    return preset

def delete_publish_preset(preset_id):
    preset_id = validate_slug(preset_id, "Publish preset id")
    if preset_id == "olympus-default":
        raise RunnerConflictError("The built-in olympus-default preset can be edited but not deleted.")
    if any(app.get("publish", {}).get("preset") == preset_id for app in apps()[0]):
        raise RunnerConflictError("Publish preset is still referenced by an app.")
    path = PD / f"{preset_id}.json"
    if not path.exists():
        return False
    path.unlink()
    append_activity("preset", f"Publish preset {preset_id} deleted")
    return True

def validate_app(data):
    require_keys(
        data,
        {"schemaVersion", "kind", "id", "identity", "source", "build", "package"},
        {"schemaVersion", "kind", "id", "identity", "source", "build", "package", "publish"},
        "App",
    )
    if data.get("schemaVersion") != 1 or data.get("kind") != "ForgeCoreApp":
        raise ValueError("App schemaVersion/kind is invalid.")
    app_id = validate_slug(data.get("id"), "App id")

    identity = data.get("identity")
    require_keys(identity, {"name"}, {"name", "storeId"}, "App identity")
    name = str(identity.get("name") or "").strip()
    store_id = str(identity.get("storeId") or "").strip()
    if not name or len(name) > 100:
        raise ValueError("App name must be 1-100 characters.")
    if store_id and not STORE_ID.fullmatch(store_id):
        raise ValueError("storeId must use the olympus-<slug> format when configured.")

    source = data.get("source")
    require_keys(source, {"provider", "repository", "defaultBranch", "private"}, {"provider", "repository", "defaultBranch", "private"}, "App source")
    if source.get("provider") != "github":
        raise ValueError("Only GitHub sources are supported in Phase 0.")
    repository = str(source.get("repository") or "").strip()
    if not REPO.fullmatch(repository):
        raise ValueError("Source repository must look like owner/repository.")
    default_branch = str(source.get("defaultBranch") or "").strip()
    if not BRANCH.fullmatch(default_branch) or ".." in default_branch:
        raise ValueError("Source defaultBranch is invalid.")
    if not isinstance(source.get("private"), bool):
        raise ValueError("source.private must be true or false.")

    build = data.get("build")
    require_keys(build, {"executor"}, {"executor", "targetMode", "targets", "steps"}, "App build")
    executor = str(build.get("executor") or "")
    if executor not in EXECUTORS:
        raise ValueError("App executor is invalid.")
    target_mode = str(build.get("targetMode") or "").strip()
    if target_mode and target_mode not in {"auto", "manual"}:
        raise ValueError("App build.targetMode must be auto or manual.")
    targets = build.get("targets", [])
    if not isinstance(targets, list) or len(targets) > len(TARGETS):
        raise ValueError("App targets must be an array of supported architectures.")
    clean_targets = []
    for target in targets:
        if target not in TARGETS:
            raise ValueError(f"Unsupported build target: {target}.")
        if target not in clean_targets:
            clean_targets.append(target)

    raw_steps = build.get("steps", [])
    if not isinstance(raw_steps, list) or len(raw_steps) > 64:
        raise ValueError("App build.steps must be an array with at most 64 entries.")
    clean_steps = []
    for index, step in enumerate(raw_steps, 1):
        require_keys(
            step,
            {"name", "stage", "run"},
            {"name", "stage", "run", "workingDirectory", "timeoutSeconds", "env", "secrets"},
            f"App build step {index}",
        )
        step_name = str(step.get("name") or "").strip()
        stage_name = str(step.get("stage") or "")
        command = str(step.get("run") or "")
        if not step_name or len(step_name) > 120:
            raise ValueError(f"App build step {index} name must be 1-120 characters.")
        if stage_name not in {"build", "test", "verify"}:
            raise ValueError(f"App build step {index} stage is invalid.")
        if not command.strip() or len(command) > 16384 or "\0" in command:
            raise ValueError(f"App build step {index} command is invalid.")
        clean_step = {"name": step_name, "stage": stage_name, "run": command}
        if "workingDirectory" in step:
            clean_step["workingDirectory"] = validate_relative_path(
                step.get("workingDirectory"), f"build.steps[{index - 1}].workingDirectory"
            )
        if "timeoutSeconds" in step:
            timeout = step.get("timeoutSeconds")
            if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1 or timeout > 86400:
                raise ValueError(f"App build step {index} timeoutSeconds must be 1-86400.")
            clean_step["timeoutSeconds"] = timeout
        for field in ("env", "secrets"):
            values = step.get(field, {})
            if not isinstance(values, dict) or len(values) > 64:
                raise ValueError(f"App build step {index} {field} must be an object with at most 64 entries.")
            cleaned = {}
            for key, value in values.items():
                if not ENV_NAME.fullmatch(str(key)):
                    raise ValueError(f"App build step {index} {field} contains an invalid environment variable name.")
                if field == "env":
                    if not isinstance(value, str) or len(value) > 8192 or "\0" in value:
                        raise ValueError(f"App build step {index} env value is invalid.")
                elif not isinstance(value, str) or not SECRET_ENV_REF.fullmatch(value):
                    raise ValueError(
                        f"App build step {index} secret references must use secret://env/<ENV_NAME>."
                    )
                cleaned[str(key)] = value
            if cleaned:
                clean_step[field] = cleaned
        clean_steps.append(clean_step)

    package = data.get("package")
    require_keys(package, {"format", "sourcePath"}, {"format", "sourcePath"}, "App output")
    package_format = str(package.get("format") or "")
    if package_format not in {"artifact", "umbrel"}:
        raise ValueError("App output format must be artifact or umbrel.")
    source_path = validate_relative_path(package.get("sourcePath"), "package.sourcePath")
    if package_format == "umbrel" and target_mode == "manual" and not clean_targets:
        raise ValueError("Manual Umbrel architecture selection requires at least one build target.")

    publish = data.get("publish")
    preset_id = None
    preset = None
    if publish is not None:
        require_keys(publish, {"preset"}, {"preset"}, "App publish")
        preset_id = validate_slug(publish.get("preset"), "Publish preset id")
        preset = get_publish_preset(preset_id)
        if preset is None:
            raise ValueError(f"Unknown publish preset: {preset_id}.")
        if (preset.get("store") or {}).get("enabled") and not store_id:
            raise ValueError("Olympus Store ID is required when the selected publish preset enables the Community App Store.")

    return {
        "schemaVersion": 1,
        "kind": "ForgeCoreApp",
        "id": app_id,
        "identity": {"name": name, **({"storeId": store_id} if store_id else {})},
        "source": {
            "provider": "github",
            "repository": repository,
            "defaultBranch": default_branch,
            "private": source["private"],
        },
        "build": {
            "executor": executor,
            **({"targetMode": target_mode} if target_mode else {}),
            **({"targets": clean_targets} if clean_targets else {}),
            **({"steps": clean_steps} if clean_steps else {}),
        },
        "package": {"format": package_format, "sourcePath": source_path},
        **({"publish": {"preset": preset_id}} if preset_id else {}),
    }

def apps():
    ensure_control_plane()
    items = []
    errors = []
    for path in sorted(AD.glob("*.json")):
        try:
            items.append(validate_app(read_json(path)))
        except ValueError as exc:
            errors.append({"file": path.name, "error": str(exc)})
    return items, errors

def get_app(app_id):
    app_id = validate_slug(app_id, "App id")
    path = AD / f"{app_id}.json"
    if not path.exists():
        return None
    return validate_app(read_json(path))

def apps_for_runner_repository(repository):
    return [
        app for app in apps()[0]
        if app.get("build", {}).get("executor") == "github-actions"
        and app.get("source", {}).get("repository") == repository
    ]

def save_app(data):
    app = validate_app(data)
    ensure_control_plane()
    write_json_atomic(AD / f"{app['id']}.json", app)
    append_activity("app", f"App {app['id']} saved")
    return app

def delete_app(app_id):
    app_id = validate_slug(app_id, "App id")
    path = AD / f"{app_id}.json"
    if not path.exists():
        return False
    path.unlink()
    append_activity("app", f"App {app_id} deleted")
    return True

def validate_job_record(item):
    if not isinstance(item, dict):
        raise ValueError("Job must be an object.")
    job_id = str(item.get("id") or "")
    app_id = str(item.get("appId") or "")
    if item.get("schemaVersion") != 1 or item.get("kind") != "ForgeCoreJob":
        raise ValueError("Job schemaVersion/kind is invalid.")
    if not JOB_ID.fullmatch(job_id) or not SLUG_ID.fullmatch(app_id):
        raise ValueError("Job id/appId is invalid.")
    if item.get("jobType") not in JOB_TYPES:
        raise ValueError("Job type is invalid.")
    if item.get("status") not in JOB_STATUSES:
        raise ValueError("Job status is invalid.")
    executor = item.get("executor")
    if executor is not None and executor not in EXECUTORS:
        raise ValueError("Job executor is invalid.")
    trigger = item.get("trigger")
    if not isinstance(trigger, dict) or trigger.get("type") not in {"manual", "git-ref", "github-actions"}:
        raise ValueError("Job trigger is invalid.")
    ref = str(trigger.get("ref") or "").strip()
    if not ref or len(ref) > 256 or ".." in ref or any(ch in ref for ch in "\r\n\0"):
        raise ValueError("Job trigger ref is invalid.")
    if not isinstance(item.get("configRevision"), str) or not item.get("configRevision"):
        raise ValueError("Job configRevision is invalid.")
    if not isinstance(item.get("createdAt"), str) or not item.get("createdAt"):
        raise ValueError("Job createdAt is invalid.")
    artifact_source = item.get("artifactSource")
    if artifact_source is not None:
        require_keys(
            artifact_source,
            {"jobId", "manifestSha256", "sourceRevision", "sourceConfigRevision"},
            {"jobId", "manifestSha256", "sourceRevision", "sourceConfigRevision"},
            "Job artifactSource",
        )
        if item.get("jobType") != "publish":
            raise ValueError("Job artifactSource is only valid for publish jobs.")
        if not JOB_ID.fullmatch(str(artifact_source.get("jobId") or "")):
            raise ValueError("Job artifactSource.jobId is invalid.")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(artifact_source.get("manifestSha256") or "")):
            raise ValueError("Job artifactSource.manifestSha256 is invalid.")
        if not re.fullmatch(r"[0-9a-f]{40,64}", str(artifact_source.get("sourceRevision") or "")):
            raise ValueError("Job artifactSource.sourceRevision is invalid.")
        if not str(artifact_source.get("sourceConfigRevision") or "").startswith("sha256:"):
            raise ValueError("Job artifactSource.sourceConfigRevision is invalid.")
    stages = item.get("stages")
    if not isinstance(stages, list) or not stages:
        raise ValueError("Job stages are invalid.")
    seen = set()
    for stage in stages:
        if not isinstance(stage, dict) or stage.get("name") not in JOB_STAGE_NAMES:
            raise ValueError("Job stage name is invalid.")
        if stage.get("name") in seen:
            raise ValueError("Job stages must be unique.")
        seen.add(stage.get("name"))
        if stage.get("status") not in JOB_STAGE_STATUSES:
            raise ValueError("Job stage status is invalid.")
    return item

def jobs(limit=100):
    ensure_control_plane()
    items = []
    errors = []
    for path in sorted(JD.glob("*.json")):
        try:
            items.append(validate_job_record(read_json(path)))
        except ValueError as exc:
            errors.append({"file": path.name, "error": str(exc)})
    items.sort(key=lambda item: str(item.get("createdAt", "")), reverse=True)
    return items[:max(1, min(int(limit), 500))], errors

def get_job(job_id):
    if not JOB_ID.fullmatch(str(job_id or "")):
        raise ValueError("Job id is invalid.")
    path = JD / f"{job_id}.json"
    if not path.exists():
        return None
    item = validate_job_record(read_json(path))
    if item.get("id") != job_id:
        raise ValueError("Job file id does not match its filename.")
    return item

def _job_output_json(path, job, kind, errors):
    if not path.exists():
        return None
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("output file is too large")
        item = read_json(path)
        if item.get("kind") != kind:
            raise ValueError(f"expected {kind}")
        if item.get("jobId") != job.get("id") or item.get("appId") != job.get("appId"):
            raise ValueError("job/app identity mismatch")
        return item
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append({"file": path.name, "error": str(exc)})
        return None

def job_output_summary(job):
    root = STORAGE / "artifacts" / job["appId"] / job["id"]
    release_root = root / "release"
    store_root = root / "store"
    errors = []
    artifact = _job_output_json(root / "manifest.json", job, "ForgeCoreArtifactManifest", errors)
    plan = _job_output_json(release_root / "release-plan.json", job, "ForgeCoreReleasePlan", errors)
    publication = _job_output_json(
        release_root / "publication.json", job, "ForgeCorePublicationReceipt", errors
    )
    store_publication = _job_output_json(
        store_root / "publication.json", job, "ForgeCoreStorePublicationReceipt", errors
    )
    return {
        "artifact": ({
            "format": artifact.get("format"),
            "fileCount": artifact.get("fileCount"),
            "totalBytes": artifact.get("totalBytes"),
            **({"targets": artifact.get("targets")} if artifact.get("targets") else {}),
            **({"sourceRevision": artifact.get("sourceRevision")} if artifact.get("sourceRevision") else {}),
        } if artifact else None),
        "releasePlan": ({
            "version": plan.get("version"),
            "releaseTag": plan.get("releaseTag"),
            "channel": plan.get("channel"),
            "prerelease": bool(plan.get("prerelease")),
            "updateChannel": bool(plan.get("updateChannel", plan.get("updateStableChannel"))),
            "channelPath": plan.get("channelPath") or plan.get("stableChannelPath"),
            "updateStableChannel": bool(plan.get("updateStableChannel")),
        } if plan else None),
        "publication": ({
            "repository": publication.get("repository"),
            "releaseTag": publication.get("releaseTag"),
            "channel": publication.get("channel"),
            "prerelease": bool(publication.get("prerelease")),
            "verifiedAssets": publication.get("verifiedAssets") or [],
            "releaseChannel": publication.get("releaseChannel") or publication.get("stableChannel") or {},
            "stableChannel": publication.get("stableChannel") or {},
            "publishedAt": publication.get("publishedAt"),
        } if publication else None),
        "storePublication": ({
            "repository": store_publication.get("repository"),
            "mode": store_publication.get("mode"),
            "directory": store_publication.get("directory"),
            "version": store_publication.get("version"),
            "releaseTag": store_publication.get("releaseTag"),
            "status": store_publication.get("status"),
            "branch": store_publication.get("branch"),
            "commitSha": store_publication.get("commitSha"),
            "pullRequestNumber": store_publication.get("pullRequestNumber"),
            "pullRequestUrl": store_publication.get("pullRequestUrl"),
            "publishedAt": store_publication.get("publishedAt"),
        } if store_publication else None),
        "errors": errors,
    }

def job_api_view(job):
    item = dict(job)
    item["outputs"] = job_output_summary(job)
    return item

def job_stages(job_type, preset):
    names = {
        "build": ["source", "build", "test", "verify", "package"],
        "publish": ["release", "store"],
        "build-and-publish": ["source", "build", "test", "verify", "package", "release", "store"],
    }[job_type]
    out = []
    for name in names:
        status = "pending"
        if name == "release" and not preset.get("release", {}).get("enabled", False):
            status = "skipped"
        if name == "store" and not preset.get("store", {}).get("enabled", False):
            status = "skipped"
        out.append({"name": name, "status": status})
    return out

def _new_job_id(app_id):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    for _ in range(8):
        candidate = f"{app_id}-{stamp}-{uuid.uuid4().hex[:8]}"
        if not (JD / f"{candidate}.json").exists():
            return candidate
    raise RuntimeError("Could not allocate a unique job id.")

def resolve_publish_artifact_source(app_id, data):
    require_keys(data, {"jobId"}, {"jobId"}, "Job artifact source request")
    source_job_id = str(data.get("jobId") or "")
    if not JOB_ID.fullmatch(source_job_id):
        raise ValueError("Artifact source jobId is invalid.")
    source_job = get_job(source_job_id)
    if source_job is None:
        raise ValueError("Artifact source job was not found.")
    if source_job.get("appId") != app_id:
        raise ValueError("Artifact source must belong to the same app.")
    if source_job.get("status") != "succeeded":
        raise ValueError("Artifact source job must have succeeded.")
    if source_job.get("jobType") not in {"build", "build-and-publish"}:
        raise ValueError("Artifact source must come from a build-capable job.")

    root = STORAGE / "artifacts" / app_id / source_job_id
    manifest_path = root / "manifest.json"
    package_root = root / "package"
    if not manifest_path.is_file() or not package_root.is_dir():
        raise ValueError("Artifact source job has no reusable package handoff.")
    try:
        if manifest_path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("Artifact source manifest is too large.")
        manifest = read_json(manifest_path)
    except OSError as exc:
        raise ValueError(f"Could not read artifact source manifest: {exc}") from exc
    if manifest.get("kind") != "ForgeCoreArtifactManifest":
        raise ValueError("Artifact source manifest kind is invalid.")
    if manifest.get("jobId") != source_job_id or manifest.get("appId") != app_id:
        raise ValueError("Artifact source manifest identity does not match its source job.")
    source_revision = str(manifest.get("sourceRevision") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{40,64}", source_revision):
        raise ValueError(
            "Artifact source does not contain an immutable source revision; rebuild it with the current native worker."
        )
    return {
        "jobId": source_job_id,
        "manifestSha256": file_sha256(manifest_path),
        "sourceRevision": source_revision,
        "sourceConfigRevision": source_job["configRevision"],
    }


def _resolved_store_directory(app, store):
    template = str(store.get("directoryTemplate") or "")
    app_id = str(app.get("id") or "")
    store_id = str((app.get("identity") or {}).get("storeId") or "")
    directory = template.replace("{app.id}", app_id).replace("{app.storeId}", store_id)
    if not STORE_ID.fullmatch(directory):
        raise ValueError("Store directory template must resolve to a valid olympus- app id.")
    if directory != store_id:
        raise ValueError("Store directory template must resolve exactly to app identity.storeId.")
    return directory


def validate_publish_job(app, preset, global_snapshot, job_type, ref):
    if job_type not in {"publish", "build-and-publish"}:
        return
    if app.get("build", {}).get("executor") != "forgecore-native":
        raise ValueError("Dashboard publishing currently requires the forgecore-native executor.")

    release = preset.get("release") or {}
    store = preset.get("store") or {}
    release_enabled = bool(release.get("enabled"))
    store_enabled = bool(store.get("enabled"))
    if not release_enabled and not store_enabled:
        raise ValueError("Publish jobs require release or Community App Store publishing to be enabled.")

    if (release_enabled or store_enabled) and (
        not str(ref).startswith("refs/tags/v") or len(str(ref)) <= len("refs/tags/v")
    ):
        raise ValueError("Publish jobs require a v-prefixed tag ref such as refs/tags/v1.2.3.")

    if not isinstance(global_snapshot, dict):
        raise ValueError("Publish jobs require config/global.json.")

    if release_enabled:
        releases = global_snapshot.get("releases")
        if not isinstance(releases, dict):
            raise ValueError("Global releases configuration is required.")
        if releases.get("provider") != "olympus-releases":
            raise ValueError("Global releases.provider must be olympus-releases.")
        repository = str(releases.get("repository") or "")
        if not REPO.fullmatch(repository):
            raise ValueError("Global releases.repository must look like owner/repository.")
        auth_ref = releases.get("authRef")
        if not isinstance(auth_ref, str) or not SECRET_ENV_REF.fullmatch(auth_ref):
            raise ValueError("Global releases.authRef must use secret://env/<ENV_NAME>.")

        verification = preset.get("verification") or {}
        if verification.get("sigstore"):
            signing = releases.get("signing")
            if not isinstance(signing, dict):
                raise ValueError("Sigstore-enabled publishing requires global.releases.signing.")
            require_keys(
                signing,
                {"provider", "privateKeyRef", "publicKeyRef", "passwordRef", "encoding"},
                {"provider", "privateKeyRef", "publicKeyRef", "passwordRef", "encoding"},
                "Global release signing",
            )
            if signing.get("provider") != "sigstore-key":
                raise ValueError("Global release signing.provider must be sigstore-key.")
            if signing.get("encoding") not in {"base64", "plain"}:
                raise ValueError("Global release signing.encoding must be base64 or plain.")
            for field in ("privateKeyRef", "publicKeyRef", "passwordRef"):
                value = signing.get(field)
                if not isinstance(value, str) or not SECRET_ENV_REF.fullmatch(value):
                    raise ValueError(f"Global release signing.{field} must use secret://env/<ENV_NAME>.")

    if store_enabled:
        if app.get("build", {}).get("executor") != "forgecore-native":
            raise ValueError("Phase 5 Community App Store publishing requires the forgecore-native executor.")
        if not release_enabled:
            raise ValueError("Community App Store publishing requires Olympus Releases publishing to be enabled.")
        if release.get("channel") != "stable":
            raise ValueError("Community App Store publishing accepts stable release presets only.")
        if (app.get("package") or {}).get("format") != "umbrel":
            raise ValueError("Community App Store publishing currently requires an Umbrel package.")
        _resolved_store_directory(app, store)

        community = global_snapshot.get("communityStore")
        if not isinstance(community, dict):
            raise ValueError("Global communityStore configuration is required.")
        if community.get("provider") != "olympus-community-app-store":
            raise ValueError("Global communityStore.provider must be olympus-community-app-store.")
        repository = str(community.get("repository") or "")
        if not REPO.fullmatch(repository):
            raise ValueError("Global communityStore.repository must look like owner/repository.")
        auth_ref = community.get("authRef")
        if not isinstance(auth_ref, str) or not SECRET_ENV_REF.fullmatch(auth_ref):
            raise ValueError("Global communityStore.authRef must use secret://env/<ENV_NAME>.")


def native_capabilities():
    try:
        item = read_json(NATIVE_CAPABILITIES)
    except (ValueError, OSError):
        return {}
    return item if item.get("kind") == "ForgeCoreNativeCapabilities" else {}

def publish_preflight(app_id, ref):
    app = get_app(app_id)
    if app is None:
        raise ValueError(f"Unknown app: {app_id}.")
    ref = str(ref or "").strip()
    preset_id = (app.get("publish") or {}).get("preset")
    preset = get_publish_preset(preset_id) if preset_id else None
    global_config = read_json(GLOBAL_CONFIG) if GLOBAL_CONFIG.exists() else None
    caps = native_capabilities()
    checks = []

    def add(key, label, ok, detail):
        checks.append({"key": key, "label": label, "ok": bool(ok), "detail": str(detail)})

    executor = app.get("build", {}).get("executor")
    add(
        "executor",
        "Native publish executor",
        executor == "forgecore-native",
        "ForgeCore native" if executor == "forgecore-native" else "Switch this app to ForgeCore native before dashboard publishing.",
    )

    package = app.get("package") or {}
    target_mode = (app.get("build") or {}).get("targetMode") or ("manual" if (app.get("build") or {}).get("targets") else "auto")
    if package.get("format") == "umbrel":
        add(
            "architectures",
            "Architectures",
            target_mode == "auto" or bool((app.get("build") or {}).get("targets")),
            "Auto detect at build time" if target_mode == "auto" else ", ".join((app.get("build") or {}).get("targets") or []),
        )

    add("preset", "Publish preset", bool(preset), preset_id or "No publish preset selected")
    release = (preset or {}).get("release") or {}
    store = (preset or {}).get("store") or {}
    release_enabled = bool(release.get("enabled"))
    store_enabled = bool(store.get("enabled"))
    add("publish-stages", "Publish stages", release_enabled or store_enabled, "Release + Store" if store_enabled else "Release" if release_enabled else "No publishing stage enabled")
    add(
        "version-tag",
        "Version tag",
        ref.startswith("refs/tags/v") and len(ref) > len("refs/tags/v"),
        ref or "Enter a version such as v1.2.3",
    )

    if app.get("source", {}).get("private"):
        add(
            "source-credential",
            "Source credential",
            bool(caps.get("sourceCredentialAvailable")),
            "Available in native worker" if caps.get("sourceCredentialAvailable") else "Private source token is not available to the native worker.",
        )

    releases = (global_config or {}).get("releases") or {}
    if release_enabled:
        release_configured = releases.get("provider") == "olympus-releases" and bool(REPO.fullmatch(str(releases.get("repository") or ""))) and bool(SECRET_ENV_REF.fullmatch(str(releases.get("authRef") or "")))
        add("release-config", "Olympus Releases", release_configured, str(releases.get("repository") or "Not configured"))
        add(
            "release-credential",
            "Release credential",
            bool(caps.get("releaseCredentialAvailable")),
            "Available in native worker" if caps.get("releaseCredentialAvailable") else "Configured release secret is not available to the native worker.",
        )

    verification = (preset or {}).get("verification") or {}
    if release_enabled and verification.get("sigstore"):
        signing = releases.get("signing") or {}
        signing_configured = signing.get("provider") == "sigstore-key" and all(SECRET_ENV_REF.fullmatch(str(signing.get(k) or "")) for k in ("privateKeyRef", "publicKeyRef", "passwordRef"))
        signing_available = bool(caps.get("signingPrivateKeyAvailable") and caps.get("signingPublicKeyAvailable") and caps.get("signingPasswordAvailable"))
        add("signing-config", "Sigstore configuration", signing_configured, "Signing references configured" if signing_configured else "Signing references are incomplete")
        add("signing-credentials", "Sigstore credentials", signing_available, "Signing key material available in native worker" if signing_available else "One or more signing secrets are missing in the native worker.")

    if store_enabled:
        community = (global_config or {}).get("communityStore") or {}
        store_configured = community.get("provider") == "olympus-community-app-store" and bool(REPO.fullmatch(str(community.get("repository") or ""))) and bool(SECRET_ENV_REF.fullmatch(str(community.get("authRef") or "")))
        add("store-package", "Umbrel package", package.get("format") == "umbrel", package.get("format") or "Not configured")
        add("store-channel", "Stable channel", release.get("channel") == "stable", str(release.get("channel") or "Not configured"))
        add("store-id", "Olympus Store ID", bool((app.get("identity") or {}).get("storeId")), str((app.get("identity") or {}).get("storeId") or "Not configured"))
        add("store-config", "Community Store", store_configured, str(community.get("repository") or "Not configured"))
        add(
            "store-credential",
            "Store credential",
            bool(caps.get("storeCredentialAvailable")),
            "Available in native worker" if caps.get("storeCredentialAvailable") else "Configured Store secret is not available to the native worker.",
        )
        store_mode = str(store.get("mode") or "")
        add(
            "store-mode",
            "Store publish mode",
            store_mode in {"pull-request", "direct"},
            (store_mode + (" · recommended for the first live test" if store_mode == "pull-request" else " · writes directly to the Store repository")) if store_mode else "Not configured",
        )

    try:
        validate_publish_job(app, preset or {}, global_config, "build-and-publish", ref)
    except ValueError as exc:
        add("backend-validation", "Publish contract", False, str(exc))
    else:
        add("backend-validation", "Publish contract", True, "ForgeCore publish contract accepted")

    return {
        "ready": all(item["ok"] for item in checks),
        "appId": app["id"],
        "ref": ref,
        "checks": checks,
        "capabilitiesUpdatedAt": caps.get("updatedAt"),
    }

def create_job(data):
    require_keys(data, {"appId"}, {"appId", "jobType", "trigger", "artifactSource"}, "Job request")
    app_id = validate_slug(data.get("appId"), "App id")
    app = get_app(app_id)
    if app is None:
        raise ValueError(f"Unknown app: {app_id}.")
    job_type = str(data.get("jobType") or "build")
    if job_type not in JOB_TYPES:
        raise ValueError("Job type is invalid.")
    trigger = data.get("trigger") or {
        "type": "manual",
        "ref": f"refs/heads/{app['source']['defaultBranch']}",
    }
    require_keys(trigger, {"type", "ref"}, {"type", "ref"}, "Job trigger")
    trigger_type = str(trigger.get("type") or "")
    if trigger_type not in {"manual", "git-ref", "github-actions"}:
        raise ValueError("Job trigger type is invalid.")
    ref = str(trigger.get("ref") or "").strip()
    if not ref or len(ref) > 256 or ".." in ref or any(ch in ref for ch in "\r\n\0"):
        raise ValueError("Job trigger ref is invalid.")
    preset_id = (app.get("publish") or {}).get("preset")
    preset = get_publish_preset(preset_id) if preset_id else None
    if job_type in {"publish", "build-and-publish"} and preset is None:
        raise ValueError("This app has no publishing configuration.")
    global_snapshot = read_json(GLOBAL_CONFIG) if GLOBAL_CONFIG.exists() else None
    artifact_source = None
    if job_type == "publish" and app.get("build", {}).get("executor") == "forgecore-native":
        if data.get("artifactSource") is None:
            raise ValueError(
                "Native publish-only jobs require artifactSource.jobId selecting a succeeded build artifact."
            )
        artifact_source = resolve_publish_artifact_source(app_id, data["artifactSource"])
    elif "artifactSource" in data:
        raise ValueError("artifactSource is only supported for native publish-only jobs.")
    validate_publish_job(app, preset or {}, global_snapshot, job_type, ref)
    snapshot = {
        "global": global_snapshot,
        "publishPreset": preset,
        "app": app,
    }
    now = utc_now()
    ensure_control_plane()
    with job_state_lock():
        job_id = _new_job_id(app_id)
        job = {
            "schemaVersion": 1,
            "kind": "ForgeCoreJob",
            "id": job_id,
            "appId": app_id,
            "jobType": job_type,
            "status": "queued",
            "executor": app["build"]["executor"],
            "trigger": {"type": trigger_type, "ref": ref},
            "configRevision": config_revision(snapshot),
            "createdAt": now,
            "updatedAt": now,
            "startedAt": None,
            "finishedAt": None,
            "currentStage": None,
            "cancelRequested": False,
            **({"artifactSource": artifact_source} if artifact_source else {}),
            "snapshot": snapshot,
            "stages": job_stages(job_type, preset or {}),
        }
        write_json_atomic(JD / f"{job_id}.json", job)
    append_activity("job", f"Job {job_id} queued for {app_id}")
    return job

def _save_job(job):
    job["updatedAt"] = utc_now()
    validate_job_record(job)
    write_json_atomic(JD / f"{job['id']}.json", job)
    return job

def transition_job(job_id, new_status, message=None):
    if new_status not in JOB_STATUSES:
        raise ValueError("Job status is invalid.")
    with job_state_lock():
        job = get_job(job_id)
        if job is None:
            raise ValueError("Job not found.")
        old_status = job["status"]
        if new_status == old_status:
            return job
        if new_status not in JOB_TRANSITIONS.get(old_status, set()):
            raise RunnerConflictError(f"Job cannot transition from {old_status} to {new_status}.")
        job["status"] = new_status
        if message:
            job["statusMessage"] = str(message)[:500]
        if new_status == "running" and not job.get("startedAt"):
            job["startedAt"] = utc_now()
        if new_status in {"succeeded", "failed", "cancelled"}:
            job["finishedAt"] = utc_now()
            job["currentStage"] = None
            if new_status == "cancelled":
                job["cancelRequested"] = False
                for stage in job["stages"]:
                    if stage["status"] in {"pending", "running"}:
                        stage["status"] = "cancelled"
                        stage["finishedAt"] = job["finishedAt"]
        saved = _save_job(job)
    append_activity("job", f"Job {job_id}: {old_status} -> {new_status}")
    return saved

def claim_next_job(executor):
    if executor not in EXECUTORS:
        raise ValueError("Executor is invalid.")
    with job_state_lock():
        queued = [
            item for item in jobs(limit=500)[0]
            if item.get("status") == "queued" and item.get("executor") == executor
        ]
        if not queued:
            return None
        queued.sort(key=lambda item: str(item.get("createdAt", "")))
        return transition_job(queued[0]["id"], "preparing", f"Claimed by {executor}")

def start_job(job_id):
    return transition_job(job_id, "running", "Executor started job")

def start_job_stage(job_id, stage_name):
    if stage_name not in JOB_STAGE_NAMES:
        raise ValueError("Job stage is invalid.")
    with job_state_lock():
        job = get_job(job_id)
        if job is None:
            raise ValueError("Job not found.")
        if job["status"] != "running":
            raise RunnerConflictError("Job must be running before a stage can start.")
        if job.get("cancelRequested"):
            raise RunnerConflictError("Job cancellation has been requested.")
        index = next((i for i, stage in enumerate(job["stages"]) if stage["name"] == stage_name), None)
        if index is None:
            raise ValueError("Job does not contain that stage.")
        stage = job["stages"][index]
        if stage["status"] != "pending":
            raise RunnerConflictError("Job stage is not pending.")
        for previous in job["stages"][:index]:
            if previous["status"] not in {"succeeded", "skipped"}:
                raise RunnerConflictError("Previous job stages are not complete.")
        now = utc_now()
        stage["status"] = "running"
        stage["startedAt"] = now
        job["currentStage"] = stage_name
        saved = _save_job(job)
    append_activity("job", f"Job {job_id} stage {stage_name} started")
    return saved

def finish_job_stage(job_id, stage_name, outcome="succeeded", message=None):
    if outcome not in {"succeeded", "failed", "skipped"}:
        raise ValueError("Job stage outcome is invalid.")
    with job_state_lock():
        job = get_job(job_id)
        if job is None:
            raise ValueError("Job not found.")
        stage = next((stage for stage in job["stages"] if stage["name"] == stage_name), None)
        if stage is None:
            raise ValueError("Job does not contain that stage.")
        if stage["status"] != "running" and not (outcome == "skipped" and stage["status"] == "pending"):
            raise RunnerConflictError("Job stage is not active.")
        stage["status"] = outcome
        stage["finishedAt"] = utc_now()
        if message:
            stage["message"] = str(message)[:500]
        job["currentStage"] = None
        if outcome == "failed":
            job["status"] = "failed"
            job["finishedAt"] = stage["finishedAt"]
            job["statusMessage"] = stage.get("message", f"Stage {stage_name} failed")
        elif all(item["status"] in {"succeeded", "skipped"} for item in job["stages"]):
            job["status"] = "succeeded"
            job["finishedAt"] = stage["finishedAt"]
        saved = _save_job(job)
    append_activity("job", f"Job {job_id} stage {stage_name}: {outcome}")
    return saved

def request_cancel_job(job_id):
    with job_state_lock():
        job = get_job(job_id)
        if job is None:
            raise ValueError("Job not found.")
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            return job
        if job["status"] in {"queued", "preparing"}:
            return transition_job(job_id, "cancelled", "Cancelled before execution")
        job["cancelRequested"] = True
        job["statusMessage"] = "Cancellation requested; waiting for executor acknowledgement."
        saved = _save_job(job)
    append_activity("job", f"Job {job_id} cancellation requested")
    return saved

def acknowledge_job_cancel(job_id):
    with job_state_lock():
        job = get_job(job_id)
        if job is None:
            raise ValueError("Job not found.")
        if job["status"] != "running" or not job.get("cancelRequested"):
            raise RunnerConflictError("Job is not awaiting cancellation.")
    return transition_job(job_id, "cancelled", "Executor acknowledged cancellation")

class ExecutorAdapter:
    name = None

    def claim(self):
        return claim_next_job(self.name)

    def start(self, job_id):
        return start_job(job_id)

    def start_stage(self, job_id, stage_name):
        return start_job_stage(job_id, stage_name)

    def finish_stage(self, job_id, stage_name, outcome="succeeded", message=None):
        return finish_job_stage(job_id, stage_name, outcome, message)

    def cancellation_requested(self, job_id):
        job = get_job(job_id)
        return bool(job and job.get("cancelRequested"))

    def acknowledge_cancel(self, job_id):
        return acknowledge_job_cancel(job_id)

class ForgeCoreNativeExecutorAdapter(ExecutorAdapter):
    name = "forgecore-native"

class GitHubActionsExecutorAdapter(ExecutorAdapter):
    name = "github-actions"

EXECUTOR_ADAPTERS = {
    "forgecore-native": ForgeCoreNativeExecutorAdapter(),
    "github-actions": GitHubActionsExecutorAdapter(),
}

def executor_adapter(name):
    try:
        return EXECUTOR_ADAPTERS[name]
    except KeyError as exc:
        raise ValueError("Executor is invalid.") from exc


def _runner_metadata_repositories():
    repositories = set()
    try:
        for runner_dir in RUNNER_ENGINE.iterdir():
            if not runner_dir.is_dir():
                continue
            metadata = runner_dir / RUNNER_METADATA_NAME
            try:
                data = read_json(metadata)
            except ValueError:
                continue
            repository = str(data.get("repository") or "").strip()
            if REPO.fullmatch(repository):
                repositories.add(repository)
    except OSError:
        pass
    return repositories

def _v1_runner_repositories():
    repositories = set()
    if not V1_RUNNER_CONFIG_DIR.exists():
        return repositories
    for path in sorted(V1_RUNNER_CONFIG_DIR.glob("*.env")):
        if path.name == "runner.env.example":
            continue
        repository = env(path).get("REPOSITORY", "")
        if REPO.fullmatch(repository):
            repositories.add(repository)
    return repositories

def _runner_state_repositories():
    repositories = set()
    for path in ST.glob("runner-*.repo"):
        try:
            repository = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if REPO.fullmatch(repository):
            repositories.add(repository)
    return repositories

def _migration_app_id(repository, existing_ids):
    base = slug(repository.rsplit("/", 1)[-1]) or "app"
    candidates = [base, slug(repository), base + "-runner"]
    for candidate in candidates:
        if candidate and candidate not in existing_ids and SLUG_ID.fullmatch(candidate):
            return candidate
    index = 2
    while True:
        candidate = f"{base}-{index}"
        if candidate not in existing_ids:
            return candidate
        index += 1

def migrate_v1_runner_apps():
    if V1_RUNNER_APP_MIGRATION_MARKER.exists():
        return []
    ensure_control_plane()
    existing, _ = apps()
    existing_ids = {app["id"] for app in existing}
    repositories_with_apps = {
        app.get("source", {}).get("repository")
        for app in existing
        if app.get("build", {}).get("executor") == "github-actions"
    }
    repositories = sorted(_v1_runner_repositories() | _runner_metadata_repositories() | _runner_state_repositories())
    migrated = []
    for repository in repositories:
        if repository in repositories_with_apps:
            continue
        app_id = _migration_app_id(repository, existing_ids)
        repo_name = repository.rsplit("/", 1)[-1]
        migrated_app = validate_app({
            "schemaVersion": 1,
            "kind": "ForgeCoreApp",
            "id": app_id,
            "identity": {
                "name": repo_name,
                "storeId": "olympus-" + (slug(repo_name) or app_id),
            },
            "source": {
                "provider": "github",
                "repository": repository,
                "defaultBranch": "main",
                "private": True,
            },
            "build": {
                "executor": "github-actions",
                "targets": ["amd64", "arm64"],
            },
            "package": {
                "format": "umbrel",
                "sourcePath": "umbrel",
            },
            "publish": {
                "preset": "olympus-default",
            },
        })
        write_json_atomic(AD / f"{app_id}.json", migrated_app)
        existing_ids.add(app_id)
        repositories_with_apps.add(repository)
        migrated.append({"appId": app_id, "repository": repository})
        append_activity("app", f"v1 runner repository migrated to App {app_id}")

    write_json_atomic(V1_RUNNER_APP_MIGRATION_MARKER, {
        "schemaVersion": 1,
        "kind": "ForgeCoreV1RunnerAppMigration",
        "migratedAt": utc_now(),
        "apps": migrated,
    })
    if migrated:
        (ST / "reload-runners.request").touch()
    return migrated

def runners():
    managed_apps = apps()[0]
    apps_by_repository = {}
    repositories = set(_runner_metadata_repositories())
    for app in managed_apps:
        if app.get("build", {}).get("executor") != "github-actions":
            continue
        repository = app.get("source", {}).get("repository", "")
        if repository:
            apps_by_repository.setdefault(repository, []).append(app)
            repositories.add(repository)

    for runtime_path in ST.glob("runner-*.runtime.json"):
        try:
            runtime = read_json(runtime_path)
        except ValueError:
            continue
        repository = str(runtime.get("repository") or "").strip()
        if REPO.fullmatch(repository):
            repositories.add(repository)

    out = []
    for repo in sorted(repositories):
        s = slug(repo)
        ep = ST / f"runner-{s}.error"
        np = ST / f"runner-{s}.name"
        runtime_path = ST / f"runner-{s}.runtime.json"
        runner_dir = RUNNER_ENGINE / s
        settings_file = runner_dir / ".runner"
        er = ep.read_text(encoding="utf-8", errors="replace").strip() if ep.exists() else ""
        name = repo.rsplit("/", 1)[-1]
        if np.exists():
            name = np.read_text(encoding="utf-8", errors="replace").strip()

        mode = "unregistered"
        phase = "idle"
        message = ""
        state_epoch = 0
        try:
            runtime = read_json(runtime_path)
        except ValueError:
            runtime = {}

        if isinstance(runtime, dict):
            phase = str(runtime.get("phase", phase))
            message = str(runtime.get("message", ""))
            try:
                state_epoch = int(runtime.get("epoch", 0) or 0)
            except (TypeError, ValueError):
                state_epoch = 0
            runtime_mode = str(runtime.get("mode", "")).strip()
            if runtime_mode:
                mode = runtime_mode

        if mode in ("", "unregistered", "unknown") and settings_file.exists():
            try:
                identity = json.loads(settings_file.read_text(encoding="utf-8-sig", errors="strict"))
                mode = "ephemeral" if bool(identity.get("Ephemeral", identity.get("ephemeral", False))) else "persistent"
            except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
                mode = "unreadable"

        if er:
            message = er
            if phase not in ("registering", "starting", "connecting"):
                phase = "error"

        online = (ST / f"runner-{s}.online").exists() and phase == "online"
        def read_epoch(suffix):
            try:
                return int((ST / f"runner-{s}.{suffix}").read_text().strip())
            except (OSError, ValueError):
                return 0

        linked_apps = apps_by_repository.get(repo, [])
        out.append({
            "repository": repo,
            "name": name,
            "label": repo.rsplit("/", 1)[-1],
            "mode": mode,
            "phase": phase,
            "message": message,
            "stateEpoch": state_epoch,
            "online": online,
            "error": er,
            "assigned": bool(linked_apps),
            "appIds": [app["id"] for app in linked_apps],
            "appNames": [app.get("identity", {}).get("name", app["id"]) for app in linked_apps],
            "last_job_started_epoch": read_epoch("job-started-epoch"),
            "last_job_completed_epoch": read_epoch("job-completed-epoch"),
        })
    return out

def append_activity(kind, message):
    ST.mkdir(parents=True, exist_ok=True)
    record = {"epoch": int(__import__("time").time()), "type": kind, "message": message}
    with (ST / "activity.log").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")

def activity(limit=12):
    path = ST / "activity.log"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            item = json.loads(line)
            if isinstance(item, dict) and "epoch" in item and "message" in item:
                out.append(item)
        except json.JSONDecodeError:
            continue
    return list(reversed(out))

def inspect_manager_artifact():
    result = {
        "manager_artifact_ok": False,
        "manager_artifact_build": "missing",
        "manager_artifact_error": "",
    }
    try:
        encoded = MANAGER_ARTIFACT.read_bytes()
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8", errors="strict")
        match = re.search(r'^FORGECORE_MANAGER_BUILD="([^"]+)"$', decoded, re.MULTILINE)
        build = match.group(1) if match else "unknown"
        result["manager_artifact_build"] = build
        result["manager_artifact_ok"] = build == WEB_BUILD
        if not result["manager_artifact_ok"]:
            result["manager_artifact_error"] = (
                f"Installed runner-manager build is {build}; dashboard build is {WEB_BUILD}."
            )
    except (OSError, ValueError, UnicodeError) as exc:
        result["manager_artifact_error"] = f"Runner-manager artifact could not be verified: {exc}"
    return result

def status():
    x = {
        "runner_online": False,
        "runner_name": "Runner not configured",
        "docker_online": False,
        "compose_online": False,
        "disk_used": "—",
        "disk_total": "—",
        "disk_used_percent": 0,
    }
    try:
        x.update(json.loads((ST / "status.json").read_text()))
    except (OSError, json.JSONDecodeError):
        pass
    x.update(settings())
    x["global_config_path"] = "config/global.json"
    now = int(__import__("time").time())
    try:
        status_epoch = int(x.get("status_epoch", 0))
    except (TypeError, ValueError):
        status_epoch = 0
    x["manager_alive"] = status_epoch > 0 and (now - status_epoch) <= 20
    x["manager_runtime_version"] = str(x.get("runtime_version", "unknown"))
    x["manager_build"] = str(x.get("manager_build", "unknown"))
    x["web_runtime_version"] = RUNTIME_VERSION
    x["web_build"] = WEB_BUILD
    x.update(inspect_manager_artifact())
    bootstrap_text = tail_text(ST / "runner-bootstrap.log", max_bytes=16384)
    x["bootstrap_present"] = bool(bootstrap_text.strip())
    x["bootstrap_beta54_seen"] = "ForgeCore 0.1.0-beta.54 runner bootstrap started" in bootstrap_text
    x["storage_display"] = STORAGE_DISPLAY
    x["storage_host_path"] = STORAGE_HOST_PATH
    x["storage_resolution"] = STORAGE_RESOLUTION
    storage_messages = []
    for error_path in (ST / "storage-resolution.error", ST / "runner-service.error"):
        try:
            message = error_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            message = ""
        if message and message not in storage_messages:
            storage_messages.append(message)
    x["storage_error"] = " ".join(storage_messages)
    try:
        x["dependency_error"] = (ST / "dependencies.error").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        x["dependency_error"] = ""
    x["runners"] = runners()
    x["activity"] = activity(100)
    try:
        x["last_cleanup_epoch"] = int((ST / "last-cleanup-epoch").read_text().strip())
    except (OSError, ValueError):
        x["last_cleanup_epoch"] = 0
    x["cleanup_pending"] = (ST / "cleanup-now.request").exists()
    x["cleanup_running"] = (ST / "cleanup-running").exists()
    return x

def origin_ok(handler):
    origin = handler.headers.get("Origin")
    host = handler.headers.get("Host", "")
    if not origin:
        return True
    parsed = urlparse(origin)
    return parsed.netloc == host and parsed.scheme in ("http", "https")

class RunnerConflictError(Exception):
    pass

def stored_runner_identity_mode(repo):
    settings_file = RUNNER_ENGINE / slug(repo) / ".runner"
    if not settings_file.exists():
        return "unregistered"
    try:
        identity = json.loads(settings_file.read_text(encoding="utf-8-sig", errors="strict"))
        if not isinstance(identity, dict):
            return "invalid"
        return "ephemeral" if bool(identity.get("Ephemeral", identity.get("ephemeral", False))) else "persistent"
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        return "invalid"

def inherit_owner(path, parent):
    try:
        st = parent.stat()
        os.chown(path, st.st_uid, st.st_gid)
    except OSError:
        pass

def save_settings(data):
    def bounded(key, lo, hi):
        try:
            value = int(data.get(key))
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number.")
        if value < lo or value > hi:
            raise ValueError(f"{key} must be between {lo} and {hi}.")
        return value
    cleanup_days = bounded("cleanup_interval_days", 1, 365)
    cache_days = bounded("cache_max_age_days", 1, 365)
    workspace_days = bounded("workspace_max_age_days", 1, 365)
    threshold = bounded("disk_cleanup_threshold_percent", 50, 99)
    keep_gb = bounded("buildkit_keep_storage_gb", 1, 1000)

    global_config = ensure_global_config()
    global_config["cleanup"] = {
        "intervalHours": cleanup_days * 24,
        "cacheMaxAgeDays": cache_days,
        "workspaceMaxAgeDays": workspace_days,
        "diskThresholdPercent": threshold,
        "buildkitKeepStorageGB": keep_gb,
    }
    global_config = validate_global_config(global_config)
    write_json_atomic(GLOBAL_CONFIG, global_config)
    append_activity("settings", "ForgeCore v2 global cleanup configuration updated")

def save_runner(data, app_id):
    app = get_app(app_id)
    if app is None:
        raise ValueError("Runner registration requires an existing managed App.")
    if app.get("build", {}).get("executor") != "github-actions":
        raise ValueError("Only Apps using the GitHub Actions executor can own a repository runner.")
    repo = app.get("source", {}).get("repository", "")
    supplied_repository = str(data.get("repository", "")).strip()
    if supplied_repository and supplied_repository != repo:
        raise ValueError("Runner repository must match the App source repository.")

    token = str(data.get("token", "")).strip()
    repair_existing = data.get("repair_existing") is True
    if not REPO.fullmatch(repo):
        raise ValueError("App source repository must look like owner/repository.")
    if not TOKEN.fullmatch(token):
        raise ValueError("Enter a fresh GitHub self-hosted runner registration token.")

    identity_mode = stored_runner_identity_mode(repo)
    if identity_mode != "unregistered" and not repair_existing:
        raise RunnerConflictError(
            "Runner identity already exists. No changes were made. "
            "Open Repair connection and explicitly confirm replacement first."
        )

    s = slug(repo)
    RUNNER_REQUEST_DIR.mkdir(parents=True, exist_ok=True)
    request_path = RUNNER_REQUEST_DIR / f"{s}.json"
    write_json_atomic(request_path, {
        "schemaVersion": 1,
        "kind": "ForgeCoreRunnerRequest",
        "appId": app["id"],
        "repository": repo,
        "token": token,
        "repairExisting": repair_existing,
        "requestedAt": utc_now(),
    })

    ST.mkdir(parents=True, exist_ok=True)
    write_json_atomic(ST / f"runner-{s}.runtime.json", {
        "epoch": int(__import__("time").time()),
        "repository": repo,
        "appId": app["id"],
        "phase": "queued",
        "mode": "unknown",
        "message": "Runner request saved; waiting for runner manager",
    })
    append_activity("runner", f"Runner registration requested for app {app['id']} ({repo})")
    (ST / "reload-runners.request").touch()

def tail_text(path, max_bytes=65536):
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(-max_bytes, 2)
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""

def log_sources():
    sources = []
    mapping = [
        ("startup", "Startup / storage", ST / "runner-service.error"),
        ("storage", "Storage resolution", ST / "storage-resolution.error"),
        ("bootstrap", "Runner bootstrap", ST / "runner-bootstrap.log"),
        ("runner-manager", "Runner manager", STORAGE / "logs" / "runner-manager.log"),
        ("cleanup", "Cleanup", STORAGE / "logs" / "cleanup.log"),
    ]
    for ident, label, path in mapping:
        if path.exists():
            sources.append({"id": ident, "label": label})
    for p in sorted((STORAGE / "logs").glob("registration-*.log")):
        ident = "registration:" + p.stem[len("registration-"):]
        sources.append({"id": ident, "label": "Registration · " + p.stem[len("registration-"):].replace("-", "/")})
    for p in sorted((STORAGE / "logs").glob("runner-*.log")):
        if p.name == "runner-manager.log":
            continue
        ident = "runner:" + p.stem[len("runner-"):]
        sources.append({"id": ident, "label": "Runner · " + p.stem[len("runner-"):].replace("-", "/")})
    return sources

def resolve_log(kind):
    if kind == "startup":
        return ST / "runner-service.error"
    if kind == "storage":
        return ST / "storage-resolution.error"
    if kind == "bootstrap":
        return ST / "runner-bootstrap.log"
    if kind == "runner-manager":
        return STORAGE / "logs" / "runner-manager.log"
    if kind == "cleanup":
        return STORAGE / "logs" / "cleanup.log"
    if kind.startswith("registration:"):
        slug_value = kind.split(":", 1)[1]
        if re.fullmatch(r"[a-z0-9-]+", slug_value):
            return STORAGE / "logs" / f"registration-{slug_value}.log"
    if kind.startswith("runner:"):
        slug_value = kind.split(":", 1)[1]
        if re.fullmatch(r"[a-z0-9-]+", slug_value):
            return STORAGE / "logs" / f"runner-{slug_value}.log"
    return None

class Handler(BaseHTTPRequestHandler):
    server_version = "ForgeCoreDashboard/0.2"

    def log_message(self, fmt, *args):
        print("[forgecore-web] " + fmt % args, flush=True)

    def send_json(self, code, data):
        payload = json.dumps(data, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: https://avatars.githubusercontent.com https://cdn.buymeacoffee.com; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'self'")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_svg(self):
        payload = ICON_SVG.encode()
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_html(self):
        try:
            payload = current_dashboard_payload()
        except (OSError, binascii.Error, UnicodeDecodeError):
            self.send_error(503, "ForgeCore v2 dashboard runtime unavailable")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: https://avatars.githubusercontent.com https://cdn.buymeacoffee.com; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'self'")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html()
        elif parsed.path == "/icon.svg":
            self.send_svg()
        elif parsed.path == "/api/status":
            self.send_json(200, status())
        elif parsed.path == "/api/apps":
            items, errors = apps()
            self.send_json(200, {"apps": items, "errors": errors})
        elif parsed.path.startswith("/api/apps/"):
            item = get_app(parsed.path[len("/api/apps/"):])
            self.send_json(200, {"app": item}) if item else self.send_json(404, {"error": "App not found"})
        elif parsed.path == "/api/publish-presets":
            items, errors = publish_presets()
            self.send_json(200, {"presets": items, "errors": errors})
        elif parsed.path.startswith("/api/publish-presets/"):
            item = get_publish_preset(parsed.path[len("/api/publish-presets/"):])
            self.send_json(200, {"preset": item}) if item else self.send_json(404, {"error": "Publish preset not found"})
        elif parsed.path == "/api/jobs":
            items, errors = jobs()
            self.send_json(200, {"jobs": [job_api_view(item) for item in items], "errors": errors})
        elif parsed.path.startswith("/api/jobs/"):
            item = get_job(parsed.path[len("/api/jobs/"):])
            self.send_json(200, {"job": job_api_view(item)}) if item else self.send_json(404, {"error": "Job not found"})
        elif parsed.path == "/api/integrations/olympus-releases":
            self.send_json(200, {"integration": olympus_releases_integration()})
        elif parsed.path == "/api/integrations/community-app-store":
            self.send_json(200, {"integration": community_app_store_integration()})
        elif parsed.path == "/api/logs":
            kind = parse_qs(parsed.query).get("kind", [""])[0]
            if not kind:
                self.send_json(200, {"sources": log_sources()})
                return
            path = resolve_log(kind)
            if not path:
                self.send_json(404, {"error": "Unknown log source"})
                return
            self.send_json(200, {"kind": kind, "text": tail_text(path)})
        elif parsed.path == "/health":
            current = status()
            self.send_json(200, {
                "ok": True,
                "web_runtime_version": RUNTIME_VERSION,
                "web_build": WEB_BUILD,
                "manager_alive": bool(current.get("manager_alive")),
                "manager_runtime_version": current.get("manager_runtime_version", "unknown"),
                "manager_build": current.get("manager_build", "unknown"),
                "manager_artifact_ok": bool(current.get("manager_artifact_ok")),
                "manager_artifact_build": current.get("manager_artifact_build", "unknown"),
                "bootstrap_beta54_seen": bool(current.get("bootstrap_beta54_seen")),
            })
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        if not origin_ok(self):
            self.send_json(403, {"error": "Origin rejected"})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            self.send_json(415, {"error": "JSON required"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length < 0 or length > 8192:
            self.send_json(413, {"error": "Request too large"})
            return
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Invalid JSON"})
            return
        try:
            path = urlparse(self.path).path
            if path.startswith("/api/apps/") and path.endswith("/runner"):
                app_id = path[len("/api/apps/"):-len("/runner")].rstrip("/")
                save_runner(data, app_id=app_id)
            elif path.startswith("/api/apps/") and path.endswith("/publish-preflight"):
                app_id = path[len("/api/apps/"):-len("/publish-preflight")].rstrip("/")
                self.send_json(200, publish_preflight(app_id, data.get("ref")))
                return
            elif path == "/api/jobs":
                self.send_json(201, {"ok": True, "job": create_job(data)})
                return
            elif path.startswith("/api/jobs/") and path.endswith("/cancel"):
                job_id = path[len("/api/jobs/"):-len("/cancel")].rstrip("/")
                self.send_json(202, {"ok": True, "job": request_cancel_job(job_id)})
                return
            elif path == "/api/apps":
                self.send_json(200, {"ok": True, "app": save_app(data)})
                return
            elif path == "/api/publish-presets":
                self.send_json(200, {"ok": True, "preset": save_publish_preset(data)})
                return
            elif path == "/api/integrations/olympus-releases":
                self.send_json(200, {"ok": True, "integration": save_olympus_releases_integration(data)})
                return
            elif path == "/api/integrations/community-app-store":
                self.send_json(200, {"ok": True, "integration": save_community_app_store_integration(data)})
                return
            elif path == "/api/settings":
                save_settings(data)
            elif path == "/api/reload":
                append_activity("runner", "Runner manager restart requested")
                (ST / "reload-runners.request").touch()
            elif path == "/api/cleanup":
                append_activity("cleanup", "Cleanup requested")
                (ST / "cleanup-now.request").touch()
            else:
                self.send_json(404, {"error": "Not found"})
                return
            self.send_json(202, {"ok": True})
        except RunnerConflictError as exc:
            self.send_json(409, {"error": str(exc)})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except OSError:
            self.send_json(500, {"error": "ForgeCore could not write its app data."})

    def do_DELETE(self):
        if not origin_ok(self):
            self.send_json(403, {"error": "Origin rejected"})
            return
        try:
            path = urlparse(self.path).path
            if path.startswith("/api/apps/"):
                deleted = delete_app(path[len("/api/apps/"):])
                self.send_json(200, {"ok": True, "deleted": deleted})
            elif path.startswith("/api/publish-presets/"):
                deleted = delete_publish_preset(path[len("/api/publish-presets/"):])
                self.send_json(200, {"ok": True, "deleted": deleted})
            else:
                self.send_json(404, {"error": "Not found"})
        except RunnerConflictError as exc:
            self.send_json(409, {"error": str(exc)})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except OSError:
            self.send_json(500, {"error": "ForgeCore could not write its app data."})

def main():
    ST.mkdir(parents=True, exist_ok=True)
    RUNNER_REQUEST_DIR.mkdir(parents=True, exist_ok=True)
    ensure_control_plane()
    ensure_global_config()
    migrate_v1_runner_apps()
    print("[forgecore-web] dashboard listening on :8080", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()

if __name__ == "__main__":
    main()
