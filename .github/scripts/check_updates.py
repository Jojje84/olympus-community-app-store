#!/usr/bin/env python3
"""Automatically discover and update every Umbrel app in this store.

No app list is hard-coded. Any top-level directory containing umbrel-app.yml and
docker-compose.yml is discovered automatically.

Supported upstream release sources:
- GitHub repositories
- GitLab repositories

Update rules:
- repo: in umbrel-app.yml identifies the upstream project.
- Stable packages follow stable GitHub releases; prerelease packages can follow
  prereleases too. GitLab releases are treated as published releases.
- App Docker image tags that match the currently packaged app version are bumped
  to the new release.
- Sidecar images with unrelated versions (Postgres, Redis, etc.) are untouched.
"""

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
USER_AGENT = "olympus-umbrel-app-store-updater"


def read_scalar(text: str, key: str) -> str | None:
    match = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", text, re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip()
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        value = value[1:-1]
    return value.strip()


def upstream_from_url(url: str | None) -> tuple[str, str] | None:
    if not url:
        return None

    value = url.strip().removesuffix(".git").rstrip("/")

    github = re.match(r"https://github\.com/([^/]+/[^/#]+)$", value)
    if github:
        return ("github", github.group(1))

    gitlab = re.match(r"https://gitlab\.com/(.+)$", value)
    if gitlab:
        return ("gitlab", gitlab.group(1))

    return None


def fetch_json(url: str) -> object:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_releases(provider: str, project: str) -> list[dict]:
    if provider == "github":
        data = fetch_json(
            f"https://api.github.com/repos/{project}/releases?per_page=50"
        )
        releases = []
        for item in data:
            releases.append(
                {
                    "tag_name": item["tag_name"],
                    "draft": bool(item.get("draft")),
                    "prerelease": bool(item.get("prerelease")),
                }
            )
        return releases

    if provider == "gitlab":
        encoded = urllib.parse.quote(project, safe="")
        data = fetch_json(
            f"https://gitlab.com/api/v4/projects/{encoded}/releases?per_page=50"
        )
        releases = []
        for item in data:
            releases.append(
                {
                    "tag_name": item["tag_name"],
                    "draft": False,
                    "prerelease": False,
                }
            )
        return releases

    raise ValueError(f"Unsupported release provider: {provider}")


def normalize_version(value: str) -> str:
    value = value.strip()
    return value[1:] if value.startswith("v") else value


def is_prerelease_tag(value: str) -> bool:
    normalized = normalize_version(value).lower()
    return bool(re.search(r"(?:^|[.\-_])(alpha|beta|rc|pre|preview|dev)(?:[.\-_]|\d|$)", normalized))


def latest_release(releases: list[dict], allow_prerelease: bool) -> dict | None:
    for release in releases:
        if release.get("draft"):
            continue
        if release.get("prerelease") and not allow_prerelease:
            continue
        return release
    return None


def current_tag_for_version(releases: list[dict], version: str) -> str:
    for release in releases:
        tag = release.get("tag_name", "")
        if normalize_version(tag) == normalize_version(version):
            return tag
    return f"v{version}"


def replacement_tag(
    image_tag: str,
    current_tag: str,
    current_version: str,
    latest_tag: str,
) -> str | None:
    current_normalized = normalize_version(current_tag)
    version_normalized = normalize_version(current_version)
    latest_normalized = normalize_version(latest_tag)

    if image_tag == current_tag:
        return latest_tag
    if image_tag == current_normalized:
        return latest_normalized
    if image_tag == current_version:
        return latest_normalized
    if image_tag == f"v{version_normalized}":
        return f"v{latest_normalized}"
    return None


def replace_versioned_images(
    compose: str,
    current_tag: str,
    current_version: str,
    latest_tag: str,
) -> tuple[str, int, list[str]]:
    warnings: list[str] = []
    changed = 0

    pattern = re.compile(
        r"^(?P<prefix>\s*image:\s*)(?P<image>[^\s:@]+(?:/[^\s:@]+)*):"
        r"(?P<tag>[^\s@]+)(?P<digest>@sha256:[0-9a-fA-F]{64})?(?P<suffix>\s*(?:#.*)?)$",
        re.MULTILINE,
    )

    def repl(match: re.Match) -> str:
        nonlocal changed

        new_tag = replacement_tag(
            match.group("tag"),
            current_tag=current_tag,
            current_version=current_version,
            latest_tag=latest_tag,
        )
        if not new_tag:
            return match.group(0)

        if match.group("digest"):
            warnings.append(
                f"{match.group('image')} is digest-pinned; digest must be refreshed manually."
            )
            return match.group(0)

        changed += 1
        return (
            f"{match.group('prefix')}{match.group('image')}:{new_tag}"
            f"{match.group('suffix')}"
        )

    return pattern.sub(repl, compose), changed, warnings


def discover_apps() -> list[Path]:
    apps = []
    for path in sorted(ROOT.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        if (path / "umbrel-app.yml").is_file() and (path / "docker-compose.yml").is_file():
            apps.append(path)
    return apps


def update_app(app_dir: Path) -> bool:
    manifest_path = app_dir / "umbrel-app.yml"
    compose_path = app_dir / "docker-compose.yml"
    tracking_path = app_dir / "upstream-release.txt"

    manifest = manifest_path.read_text(encoding="utf-8")
    name = read_scalar(manifest, "name") or app_dir.name
    version = read_scalar(manifest, "version")
    repo_url = read_scalar(manifest, "repo")
    upstream = upstream_from_url(repo_url)

    if not version:
        print(f"{name}: skipped — manifest has no version")
        return False
    if not upstream:
        print(f"{name}: skipped — repo is not a supported GitHub/GitLab URL")
        return False

    provider, project = upstream
    releases = fetch_releases(provider, project)
    current_tag = (
        tracking_path.read_text(encoding="utf-8").strip()
        if tracking_path.exists()
        else current_tag_for_version(releases, version)
    )
    allow_prerelease = is_prerelease_tag(current_tag)
    latest = latest_release(releases, allow_prerelease)
    if not latest:
        print(f"{name}: skipped — no suitable upstream release found")
        return False

    latest_tag = latest["tag_name"]
    if normalize_version(latest_tag) == normalize_version(current_tag):
        if not tracking_path.exists():
            tracking_path.write_text(current_tag + "\n", encoding="utf-8")
            print(f"{name}: tracking initialized at {current_tag}")
            return True
        print(f"{name}: already current ({current_tag})")
        return False

    compose = compose_path.read_text(encoding="utf-8")
    new_compose, image_changes, warnings = replace_versioned_images(
        compose,
        current_tag=current_tag,
        current_version=version,
        latest_tag=latest_tag,
    )

    if warnings:
        print(f"{name}: update detected ({current_tag} -> {latest_tag})")
        for warning in warnings:
            print(f"  WARNING: {warning}")

    if image_changes == 0:
        print(
            f"{name}: update detected ({current_tag} -> {latest_tag}) but no app image "
            "tag matched the current version; leaving package unchanged for manual review."
        )
        return False

    new_version = normalize_version(latest_tag)
    manifest = re.sub(
        r'^version:\s*["\']?[^"\'\n]+["\']?\s*$',
        f'version: "{new_version}"',
        manifest,
        count=1,
        flags=re.MULTILINE,
    )

    packaged_line = f"Packaged from upstream {name} {latest_tag}."
    if re.search(r"Packaged from upstream [^\n]+", manifest):
        manifest = re.sub(
            r"Packaged from upstream [^\n]+",
            packaged_line,
            manifest,
            count=1,
        )

    manifest_path.write_text(manifest, encoding="utf-8")
    compose_path.write_text(new_compose, encoding="utf-8")
    tracking_path.write_text(latest_tag + "\n", encoding="utf-8")

    print(
        f"{name}: {current_tag} -> {latest_tag} "
        f"({image_changes} Docker image tag(s) updated)"
    )
    return True


def main() -> None:
    apps = discover_apps()
    if not apps:
        raise SystemExit("No Umbrel app packages found.")

    print(f"Discovered {len(apps)} app package(s):")
    for app in apps:
        print(f"  - {app.name}")

    changed = False
    for app in apps:
        try:
            changed = update_app(app) or changed
        except Exception as exc:
            print(f"{app.name}: ERROR — {exc}")

    if not changed:
        print("No package changes required.")


if __name__ == "__main__":
    main()