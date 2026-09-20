#!/usr/bin/env python3
"""Validate the structure and safety invariants of the Olympus Umbrel store."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
STORE_FILE = ROOT / "umbrel-app-store.yml"

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
URL_RE = re.compile(r"^https://", re.IGNORECASE)
VARIABLE_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")
EXPORTED_RE = re.compile(r"^\s*export\s+([A-Z_][A-Z0-9_]*)=", re.MULTILINE)

REQUIRED_MANIFEST_KEYS = {
    "manifestVersion",
    "id",
    "category",
    "name",
    "version",
    "tagline",
    "icon",
    "description",
    "developer",
    "website",
    "dependencies",
    "repo",
    "support",
    "port",
    "submitter",
    "submission",
}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_yaml(path: Path):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        fail(f"{path.relative_to(ROOT)} is not valid YAML: {exc}")


def normalize_version(value: str) -> str:
    value = str(value).strip()
    return value[1:] if value.startswith("v") else value


def discover_apps() -> list[Path]:
    apps: list[Path] = []
    for path in sorted(ROOT.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        if (path / "umbrel-app.yml").is_file() and (path / "docker-compose.yml").is_file():
            apps.append(path)
    return apps


def validate_store() -> None:
    if not STORE_FILE.is_file():
        fail("umbrel-app-store.yml is missing")

    store = load_yaml(STORE_FILE)
    if not isinstance(store, dict):
        fail("umbrel-app-store.yml must contain a mapping")

    store_id = store.get("id")
    store_name = store.get("name")
    if not isinstance(store_id, str) or not ID_RE.fullmatch(store_id):
        fail("store id must contain only lowercase letters, numbers and hyphens")
    if not isinstance(store_name, str) or not store_name.strip():
        fail("store name is missing")

    apps = discover_apps()
    if not apps:
        fail("no app packages were discovered")

    seen_ids: set[str] = set()
    seen_ports: dict[int, str] = {}

    for app_dir in apps:
        manifest_path = app_dir / "umbrel-app.yml"
        compose_path = app_dir / "docker-compose.yml"
        tracking_path = app_dir / "upstream-release.txt"

        manifest = load_yaml(manifest_path)
        compose = load_yaml(compose_path)

        if not isinstance(manifest, dict):
            fail(f"{manifest_path.relative_to(ROOT)} must contain a mapping")
        if not isinstance(compose, dict):
            fail(f"{compose_path.relative_to(ROOT)} must contain a mapping")

        missing = sorted(REQUIRED_MANIFEST_KEYS - set(manifest))
        if missing:
            fail(f"{app_dir.name}: manifest is missing required keys: {', '.join(missing)}")

        app_id = manifest.get("id")
        if not isinstance(app_id, str) or not ID_RE.fullmatch(app_id):
            fail(f"{app_dir.name}: invalid app id")
        if app_id != app_dir.name:
            fail(f"{app_dir.name}: directory name must match manifest id '{app_id}'")
        if not app_id.startswith(f"{store_id}-"):
            fail(f"{app_id}: app id must start with store prefix '{store_id}-'")
        if app_id in seen_ids:
            fail(f"{app_id}: duplicate app id")
        seen_ids.add(app_id)

        if manifest.get("manifestVersion") != 1:
            fail(f"{app_id}: manifestVersion must be 1")

        version = manifest.get("version")
        if not isinstance(version, str) or not version.strip():
            fail(f"{app_id}: version must be a non-empty string")

        port = manifest.get("port")
        if not isinstance(port, int) or not (1 <= port <= 65535):
            fail(f"{app_id}: port must be an integer between 1 and 65535")
        if port in seen_ports:
            fail(f"{app_id}: port {port} is already used by {seen_ports[port]}")
        seen_ports[port] = app_id

        for key in ("icon", "website", "repo", "support", "submission"):
            value = manifest.get(key)
            if not isinstance(value, str) or not URL_RE.match(value):
                fail(f"{app_id}: {key} must be an https URL")

        repo = manifest["repo"]
        if not (repo.startswith("https://github.com/") or repo.startswith("https://gitlab.com/")):
            fail(f"{app_id}: repo must point to GitHub or GitLab for automatic updates")

        services = compose.get("services")
        if not isinstance(services, dict) or not services:
            fail(f"{app_id}: docker-compose.yml must define services")

        for service_name, service in services.items():
            if not isinstance(service, dict):
                fail(f"{app_id}: service '{service_name}' must be a mapping")
            if service_name == "app_proxy":
                continue

            image = service.get("image")
            build = service.get("build")
            if not image and not build:
                fail(f"{app_id}: service '{service_name}' needs image or build")

            if isinstance(image, str):
                if image.endswith(":latest") or (":" not in image.rsplit("/", 1)[-1] and "@sha256:" not in image):
                    fail(f"{app_id}: service '{service_name}' must use an explicit image tag or digest")

        if not tracking_path.is_file():
            fail(f"{app_id}: upstream-release.txt is missing")
        tracked = tracking_path.read_text(encoding="utf-8").strip()
        if not tracked:
            fail(f"{app_id}: upstream-release.txt is empty")
        if normalize_version(tracked) != normalize_version(version):
            fail(
                f"{app_id}: upstream-release.txt ({tracked}) does not match manifest version ({version})"
            )

        compose_text = compose_path.read_text(encoding="utf-8")
        olympus_vars = {name for name in VARIABLE_RE.findall(compose_text) if name.startswith("APP_OLYMPUS_")}
        if olympus_vars:
            exports_path = app_dir / "exports.sh"
            if not exports_path.is_file():
                fail(f"{app_id}: compose uses generated Olympus variables but exports.sh is missing")
            exports_text = exports_path.read_text(encoding="utf-8")
            exported = set(EXPORTED_RE.findall(exports_text))
            missing_exports = sorted(olympus_vars - exported)
            if missing_exports:
                fail(f"{app_id}: exports.sh does not define: {', '.join(missing_exports)}")

        print(f"OK: {app_id} ({version})")

    print(f"Validated {len(apps)} Olympus app package(s).")


if __name__ == "__main__":
    validate_store()
