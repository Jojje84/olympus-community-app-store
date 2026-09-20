#!/usr/bin/env python3
import json
import re
import urllib.request
from pathlib import Path

APPS = {
    "olympus-sparkyfitness": {
        "repo": "CodeWithCJ/SparkyFitness",
        "name": "SparkyFitness",
        "allow_prerelease": False,
        "images": [
            "codewithcj/sparkyfitness_server",
            "codewithcj/sparkyfitness",
        ],
    },
    "olympus-lyftr": {
        "repo": "Cawlumm/lyftr",
        "name": "Lyftr",
        "allow_prerelease": True,
        "images": [
            "cwlumm/lyftr-backend",
            "cwlumm/lyftr-frontend",
        ],
    },
}

def latest_release(repo, allow_prerelease):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases?per_page=20",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "olympus-umbrel-app-store-updater",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        releases = json.load(response)

    for release in releases:
        if release.get("draft"):
            continue
        if not allow_prerelease and release.get("prerelease"):
            continue
        return release["tag_name"]
    raise RuntimeError(f"No suitable release found for {repo}")

def update_app(app_id, cfg):
    root = Path(app_id)
    current_file = root / "upstream-release.txt"
    current = current_file.read_text(encoding="utf-8").strip()
    latest = latest_release(cfg["repo"], cfg["allow_prerelease"])

    if latest == current:
        print(f"{cfg['name']}: already current ({current})")
        return False

    manifest_path = root / "umbrel-app.yml"
    manifest = manifest_path.read_text(encoding="utf-8")
    manifest_version = latest[1:] if latest.startswith("v") else latest
    manifest = re.sub(
        r'^version:\s*"[^"]+"',
        f'version: "{manifest_version}"',
        manifest,
        count=1,
        flags=re.MULTILINE,
    )
    manifest = re.sub(
        r"Packaged from upstream [^\n]+",
        f"Packaged from upstream {cfg['name']} {latest}.",
        manifest,
        count=1,
    )
    manifest_path.write_text(manifest, encoding="utf-8")

    compose_path = root / "docker-compose.yml"
    compose = compose_path.read_text(encoding="utf-8")
    for image in cfg["images"]:
        compose = re.sub(
            rf"(image:\s*{re.escape(image)}:)[^\s]+",
            rf"\g<1>{latest}",
            compose,
        )
    compose_path.write_text(compose, encoding="utf-8")

    current_file.write_text(latest + "\n", encoding="utf-8")
    print(f"{cfg['name']}: {current} -> {latest}")
    return True

changed = False
for app_id, cfg in APPS.items():
    changed = update_app(app_id, cfg) or changed

if not changed:
    print("No upstream updates found.")
