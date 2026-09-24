#!/usr/bin/env python3
"""ForgeCore v2 Olympus Community App Store publisher.

Consumes a verified immutable Umbrel package handoff and submits the package to
the configured Olympus Community App Store. Pull-request mode never bypasses the
store repository's own validation checks; success means the idempotent PR exists.
"""

import base64
import hashlib
import json
import os
import re
import stat
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

VERSION_RE = re.compile(r"^[0-9A-Za-z]+(?:[0-9A-Za-z.+-]*[0-9A-Za-z])?$")
STORE_ID_RE = re.compile(r"^olympus-[a-z0-9]+(?:-[a-z0-9]+)*$")


class StorePublishError(RuntimeError):
    pass


class StorePublishCancelled(StorePublishError):
    pass


def _check_cancel(cancel_check):
    if cancel_check and cancel_check():
        raise StorePublishCancelled("Community App Store publication cancelled")


def ensure_private_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def write_private_json(path, payload):
    path = Path(path)
    ensure_private_dir(path.parent)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_sha(data):
    data = bytes(data)
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def secret_from_ref(ref):
    ref = str(ref or "")
    prefix = "secret://env/"
    if not ref.startswith(prefix):
        raise StorePublishError(
            "Community Store publishing requires secret://env/<NAME> auth references"
        )
    name = ref[len(prefix):]
    if not name or not name.replace("_", "A").isalnum() or name[0].isdigit():
        raise StorePublishError("Community Store auth reference contains an invalid environment variable name")
    value = os.environ.get(name)
    if not value:
        raise StorePublishError(f"Required Community Store credential is missing or empty: {name}")
    return value


class GitHubAPI:
    def __init__(self, token, transport=None):
        self.token = str(token)
        self.transport = transport

    def request(self, method, url, data=None, headers=None, expected=(200,)):
        headers = dict(headers or {})
        headers.setdefault("Accept", "application/vnd.github+json")
        headers.setdefault("X-GitHub-Api-Version", "2022-11-28")
        headers.setdefault("User-Agent", "ForgeCore-v2")
        headers.setdefault("Authorization", f"Bearer {self.token}")

        if self.transport is not None:
            status_code, response_headers, body = self.transport(method, url, data, headers)
        else:
            request = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    status_code = response.status
                    response_headers = dict(response.headers.items())
                    body = response.read()
            except urllib.error.HTTPError as exc:
                status_code = exc.code
                response_headers = dict(exc.headers.items()) if exc.headers else {}
                body = exc.read()

        if status_code not in expected:
            message = (
                body.decode("utf-8", "replace")[:500]
                if isinstance(body, (bytes, bytearray))
                else str(body)[:500]
            )
            raise StorePublishError(
                f"GitHub API {method} {url} returned {status_code}: {message}"
            )
        return status_code, response_headers, bytes(body)

    def json(self, method, url, payload=None, expected=(200,)):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        status_code, response_headers, body = self.request(
            method, url, data=data, headers=headers, expected=expected
        )
        if not body:
            return status_code, response_headers, None
        return status_code, response_headers, json.loads(body.decode("utf-8"))


def _api_url(repository, suffix):
    return f"https://api.github.com/repos/{repository}{suffix}"


def _load_json(path, label):
    path = Path(path)
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            raise StorePublishError(f"{label} is too large")
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StorePublishError(f"{label} is missing: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise StorePublishError(f"{label} is invalid: {exc}") from exc


def _verify_artifact_manifest(package_root, manifest):
    package_root = Path(package_root)
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise StorePublishError("Artifact manifest files must be an array")

    expected = {}
    for entry in entries:
        entry = entry or {}
        name = str(entry.get("path") or "")
        if not name or name.startswith("/") or "\\" in name:
            raise StorePublishError(f"Unsafe artifact manifest path: {name}")
        parts = name.split("/")
        if any(part in {"", ".", "..", ".git"} for part in parts):
            raise StorePublishError(f"Unsafe artifact manifest path: {name}")
        if name in expected:
            raise StorePublishError(f"Duplicate artifact manifest path: {name}")
        expected[name] = entry

    actual = {}
    for path in sorted(package_root.rglob("*")):
        if path.is_symlink():
            raise StorePublishError(f"Artifact handoff contains a symlink: {path}")
        if path.is_file():
            actual[path.relative_to(package_root).as_posix()] = path

    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("extra=" + ",".join(extra))
        raise StorePublishError("Artifact handoff differs from manifest: " + " ".join(details))

    total = 0
    for name, path in actual.items():
        entry = expected[name]
        size = path.stat().st_size
        total += size
        if entry.get("size") != size:
            raise StorePublishError(f"Artifact size mismatch: {name}")
        if str(entry.get("sha256") or "").lower() != sha256_file(path):
            raise StorePublishError(f"Artifact checksum mismatch: {name}")

    if manifest.get("fileCount") != len(actual):
        raise StorePublishError("Artifact manifest fileCount does not match package contents")
    if manifest.get("totalBytes") != total:
        raise StorePublishError("Artifact manifest totalBytes does not match package contents")


def _yaml_scalar(path, key):
    pattern = re.compile(rf"^{re.escape(key)}\s*:\s*(.+?)\s*$")
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        match = pattern.match(raw)
        if not match:
            continue
        value = match.group(1).split(" #", 1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value.strip()
    return ""


def _resolve_directory(store, app):
    app_id = str(app.get("id") or "")
    store_id = str((app.get("identity") or {}).get("storeId") or "")
    template = str(store.get("directoryTemplate") or "")
    directory = template.replace("{app.id}", app_id).replace("{app.storeId}", store_id)
    if (
        not directory
        or "/" in directory
        or "\\" in directory
        or directory in {".", ".."}
        or not STORE_ID_RE.fullmatch(directory)
    ):
        raise StorePublishError("Store directory template resolved to an unsafe or invalid app directory")
    if directory != store_id:
        raise StorePublishError(
            f"Store directory must resolve to app identity.storeId ({store_id}), got {directory}"
        )
    return directory


def _release_proof(job, job_artifact_root):
    release_root = Path(job_artifact_root) / "release"
    plan = _load_json(release_root / "release-plan.json", "Release plan")
    receipt = _load_json(release_root / "publication.json", "Release publication receipt")
    if plan.get("kind") != "ForgeCoreReleasePlan":
        raise StorePublishError("Release plan kind is invalid")
    if receipt.get("kind") != "ForgeCorePublicationReceipt":
        raise StorePublishError("Release publication receipt kind is invalid")
    for payload, label in ((plan, "Release plan"), (receipt, "Release publication receipt")):
        if payload.get("jobId") != job.get("id") or payload.get("appId") != job.get("appId"):
            raise StorePublishError(f"{label} does not belong to this job/app")
    if receipt.get("releaseTag") != plan.get("releaseTag"):
        raise StorePublishError("Release publication receipt does not match the release plan")
    channel = str(plan.get("channel") or "")
    prerelease = bool(plan.get("prerelease"))
    if channel not in {"stable", "beta", "prerelease"}:
        raise StorePublishError(f"Unsupported verified release channel for Community App Store: {channel}")
    if channel == "stable" and prerelease:
        raise StorePublishError("Stable Community App Store release cannot be marked prerelease")
    if channel in {"beta", "prerelease"} and not prerelease:
        raise StorePublishError("Non-stable Community App Store release must be marked prerelease")
    if not receipt.get("verifiedAssets"):
        raise StorePublishError("Release publication has no verified assets")
    return plan, receipt


def _artifact_contract(job, package_artifact_root):
    package_artifact_root = Path(package_artifact_root)
    manifest = _load_json(package_artifact_root / "manifest.json", "Artifact manifest")
    package_root = package_artifact_root / "package"
    if not package_root.is_dir():
        raise StorePublishError("Artifact package directory is missing")

    source_contract = job.get("artifactSource") or {}
    expected_job_id = source_contract.get("jobId") if job.get("jobType") == "publish" else job.get("id")
    if manifest.get("kind") != "ForgeCoreArtifactManifest":
        raise StorePublishError("Artifact manifest kind is invalid")
    if manifest.get("jobId") != expected_job_id or manifest.get("appId") != job.get("appId"):
        raise StorePublishError("Artifact manifest does not belong to the selected job/app")

    source_revision = str(manifest.get("sourceRevision") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{40,64}", source_revision):
        raise StorePublishError("Artifact manifest is missing an immutable source revision")
    if source_contract:
        manifest_path = package_artifact_root / "manifest.json"
        expected_sha = str(source_contract.get("manifestSha256") or "")
        actual_sha = "sha256:" + sha256_file(manifest_path)
        if expected_sha != actual_sha:
            raise StorePublishError("Artifact manifest changed after publish job creation")
        if source_revision != str(source_contract.get("sourceRevision") or "").lower():
            raise StorePublishError("Artifact source revision differs from the publish job contract")

    _verify_artifact_manifest(package_root, manifest)
    return package_root, manifest


def build_store_plan(job, package_artifact_root, job_artifact_root):
    snapshot = job.get("snapshot") or {}
    global_config = snapshot.get("global") or {}
    preset = snapshot.get("publishPreset") or {}
    app = snapshot.get("app") or {}
    store = preset.get("store") or {}
    community = global_config.get("communityStore") or {}

    if not store.get("enabled"):
        raise StorePublishError("Community App Store publishing is disabled in the immutable preset snapshot")
    if community.get("provider") != "olympus-community-app-store":
        raise StorePublishError("Global communityStore.provider must be olympus-community-app-store")
    repository = str(community.get("repository") or "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise StorePublishError("Global communityStore.repository must look like owner/repository")
    mode = str(store.get("mode") or "")
    if mode not in {"pull-request", "direct"}:
        raise StorePublishError("Store publishing mode is invalid")
    if (app.get("package") or {}).get("format") != "umbrel":
        raise StorePublishError("Community App Store publishing currently requires an Umbrel package")

    package_root, manifest = _artifact_contract(job, package_artifact_root)
    release_plan, release_receipt = _release_proof(job, job_artifact_root)
    directory = _resolve_directory(store, app)

    required = ["umbrel-app.yml", "docker-compose.yml", "upstream-release.txt"]
    missing = [name for name in required if not (package_root / name).is_file()]
    if missing:
        raise StorePublishError("Umbrel package is missing required Store files: " + ", ".join(missing))

    store_id = str((app.get("identity") or {}).get("storeId") or "")
    package_id = _yaml_scalar(package_root / "umbrel-app.yml", "id")
    if package_id != store_id:
        raise StorePublishError(
            f"Umbrel manifest id must match app identity.storeId ({store_id}), got {package_id or 'missing'}"
        )
    version = _yaml_scalar(package_root / "umbrel-app.yml", "version")
    if not VERSION_RE.fullmatch(version):
        raise StorePublishError("Umbrel manifest version is missing or invalid")
    if version != str(release_plan.get("version") or ""):
        raise StorePublishError("Umbrel manifest version does not match the verified Olympus release")
    upstream = (package_root / "upstream-release.txt").read_text(encoding="utf-8").strip()
    if upstream not in {version, "v" + version}:
        raise StorePublishError("upstream-release.txt does not match the Umbrel manifest version")

    return {
        "schemaVersion": 1,
        "kind": "ForgeCoreStorePlan",
        "jobId": job.get("id"),
        "appId": job.get("appId"),
        "repository": repository,
        "mode": mode,
        "directory": directory,
        "version": version,
        "releaseTag": release_plan.get("releaseTag"),
        "sourceRepository": str((app.get("source") or {}).get("repository") or ""),
        "sourceRef": str((job.get("trigger") or {}).get("ref") or ""),
        "sourceRevision": str(manifest.get("sourceRevision") or "").lower(),
        "configRevision": job.get("configRevision"),
        "verifiedReleaseAssets": list(release_receipt.get("verifiedAssets") or []),
        "authRef": community.get("authRef"),
        "packageRoot": str(package_root),
    }


def _source_commit_text(plan):
    return (
        f"Source repository: {plan['sourceRepository']}\n"
        f"Source ref: {plan['sourceRef']}\n"
        f"Source commit: {plan['sourceRevision']}\n"
        f"Package version: {plan['version']}\n"
        f"ForgeCore job: {plan['jobId']}\n"
        f"ForgeCore config revision: {plan['configRevision']}\n"
        f"Olympus release tag: {plan['releaseTag']}\n"
    )


STORE_IGNORE_FILE = ".forgecore-storeignore"


def _store_ignore_rules(package_root):
    path = Path(package_root) / STORE_IGNORE_FILE
    if not path.is_file():
        return []
    rules = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        rule = raw.strip()
        if not rule or rule.startswith("#"):
            continue
        if rule.startswith("/") or "\\" in rule:
            raise StorePublishError(f"Unsafe Store ignore rule: {rule}")
        normalized = rule.rstrip("/") + ("/" if rule.endswith("/") else "")
        parts = normalized.rstrip("/").split("/")
        if any(part in {"", ".", "..", ".git"} for part in parts):
            raise StorePublishError(f"Unsafe Store ignore rule: {rule}")
        rules.append(normalized)
    return rules


def _store_path_ignored(rel, rules):
    for rule in rules:
        if rule.endswith("/"):
            if rel.startswith(rule):
                return True
        elif rel == rule:
            return True
    return False


def _desired_entries(plan):
    package_root = Path(plan["packageRoot"])
    ignore_rules = _store_ignore_rules(package_root)
    entries = {}
    for path in sorted(package_root.rglob("*")):
        if path.is_symlink():
            raise StorePublishError(f"Artifact handoff contains a symlink: {path}")
        if not path.is_file():
            continue
        rel = path.relative_to(package_root).as_posix()
        if any(part == ".git" for part in rel.split("/")):
            raise StorePublishError(f"Unsafe Store package path: {rel}")
        if rel == STORE_IGNORE_FILE or _store_path_ignored(rel, ignore_rules):
            continue
        data = path.read_bytes()
        mode = "100755" if path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH) else "100644"
        entries[f"{plan['directory']}/{rel}"] = {
            "data": data,
            "sha": git_blob_sha(data),
            "mode": mode,
        }

    provenance = _source_commit_text(plan).encode("utf-8")
    entries[f"{plan['directory']}/SOURCE_COMMIT"] = {
        "data": provenance,
        "sha": git_blob_sha(provenance),
        "mode": "100644",
    }
    return entries


def _get_ref(api, repository, branch, allow_missing=False):
    encoded = urllib.parse.quote(branch, safe="")
    expected = (200, 404) if allow_missing else (200,)
    status_code, _, payload = api.json(
        "GET", _api_url(repository, f"/git/ref/heads/{encoded}"), expected=expected
    )
    if status_code == 404:
        return None
    return payload["object"]["sha"]


def _tree_sha(api, repository, commit_sha):
    _, _, commit = api.json(
        "GET", _api_url(repository, f"/git/commits/{commit_sha}"), expected=(200,)
    )
    return commit["tree"]["sha"]


def _tree_blobs(api, repository, commit_sha):
    tree_sha = _tree_sha(api, repository, commit_sha)
    _, _, tree = api.json(
        "GET",
        _api_url(repository, f"/git/trees/{tree_sha}?recursive=1"),
        expected=(200,),
    )
    if tree.get("truncated"):
        raise StorePublishError("Community Store repository tree is too large to verify safely")
    return {
        item["path"]: {"sha": item["sha"], "mode": item["mode"]}
        for item in tree.get("tree") or []
        if item.get("type") == "blob"
    }, tree_sha


def _directory_matches(remote_blobs, directory, desired):
    prefix = directory + "/"
    current = {
        path: value
        for path, value in remote_blobs.items()
        if path.startswith(prefix)
    }
    expected = {
        path: {"sha": value["sha"], "mode": value["mode"]}
        for path, value in desired.items()
    }
    return current == expected


def _create_blob(api, repository, data):
    _, _, result = api.json(
        "POST",
        _api_url(repository, "/git/blobs"),
        {"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"},
        expected=(201,),
    )
    return result["sha"]


def _apply_directory(api, repository, branch, desired, directory, message, cancel_check=None):
    _check_cancel(cancel_check)
    head_sha = _get_ref(api, repository, branch)
    remote_blobs, base_tree_sha = _tree_blobs(api, repository, head_sha)
    if _directory_matches(remote_blobs, directory, desired):
        return {"commitSha": head_sha, "changed": False}

    tree_entries = []
    for path, value in desired.items():
        current = remote_blobs.get(path)
        if current == {"sha": value["sha"], "mode": value["mode"]}:
            continue
        _check_cancel(cancel_check)
        blob_sha = _create_blob(api, repository, value["data"])
        if blob_sha != value["sha"]:
            raise StorePublishError(f"GitHub blob SHA mismatch while preparing {path}")
        tree_entries.append({
            "path": path,
            "mode": value["mode"],
            "type": "blob",
            "sha": blob_sha,
        })

    prefix = directory + "/"
    for path in sorted(remote_blobs):
        if path.startswith(prefix) and path not in desired:
            tree_entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})

    _check_cancel(cancel_check)
    _, _, new_tree = api.json(
        "POST",
        _api_url(repository, "/git/trees"),
        {"base_tree": base_tree_sha, "tree": tree_entries},
        expected=(201,),
    )
    _, _, new_commit = api.json(
        "POST",
        _api_url(repository, "/git/commits"),
        {"message": message, "tree": new_tree["sha"], "parents": [head_sha]},
        expected=(201,),
    )
    _check_cancel(cancel_check)
    encoded = urllib.parse.quote(branch, safe="")
    api.json(
        "PATCH",
        _api_url(repository, f"/git/refs/heads/{encoded}"),
        {"sha": new_commit["sha"], "force": False},
        expected=(200,),
    )

    verified_blobs, _ = _tree_blobs(api, repository, new_commit["sha"])
    if not _directory_matches(verified_blobs, directory, desired):
        raise StorePublishError("Community Store branch verification failed after commit")
    return {"commitSha": new_commit["sha"], "changed": True}


def _default_branch(api, repository):
    _, _, metadata = api.json("GET", _api_url(repository, ""), expected=(200,))
    branch = str(metadata.get("default_branch") or "")
    if not branch:
        raise StorePublishError("Community Store repository has no default branch")
    return branch


def _ensure_branch(api, repository, base_branch, branch_name):
    existing = _get_ref(api, repository, branch_name, allow_missing=True)
    if existing:
        return existing
    base_sha = _get_ref(api, repository, base_branch)
    api.json(
        "POST",
        _api_url(repository, "/git/refs"),
        {"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        expected=(201,),
    )
    return base_sha


def _open_pr(api, repository, branch_name, base_branch):
    owner = repository.split("/", 1)[0]
    query = urllib.parse.urlencode({
        "state": "open",
        "head": f"{owner}:{branch_name}",
        "base": base_branch,
        "per_page": 100,
    })
    _, _, pulls = api.json(
        "GET", _api_url(repository, f"/pulls?{query}"), expected=(200,)
    )
    return (pulls or [None])[0]


def _publish_pull_request(api, plan, desired, cancel_check=None):
    repository = plan["repository"]
    base_branch = _default_branch(api, repository)
    base_sha = _get_ref(api, repository, base_branch)
    base_blobs, _ = _tree_blobs(api, repository, base_sha)
    if _directory_matches(base_blobs, plan["directory"], desired):
        return {
            "status": "already-current",
            "baseBranch": base_branch,
            "branch": None,
            "commitSha": base_sha,
            "pullRequestNumber": None,
            "pullRequestUrl": None,
        }

    branch_name = f"forgecore/store/{plan['appId']}/{plan['jobId']}"
    _ensure_branch(api, repository, base_branch, branch_name)
    applied = _apply_directory(
        api,
        repository,
        branch_name,
        desired,
        plan["directory"],
        f"Publish {plan['directory']} {plan['version']}",
        cancel_check=cancel_check,
    )
    _check_cancel(cancel_check)

    pr = _open_pr(api, repository, branch_name, base_branch)
    if pr is None:
        status_code, _, pr = api.json(
            "POST",
            _api_url(repository, "/pulls"),
            {
                "title": f"Publish {plan['directory']} {plan['version']}",
                "body": (
                    f"ForgeCore job {plan['jobId']} proposes {plan['directory']} "
                    f"from verified release {plan['releaseTag']} at "
                    f"{plan['sourceRevision']}."
                ),
                "head": branch_name,
                "base": base_branch,
            },
            expected=(201, 422),
        )
        if status_code == 422:
            pr = _open_pr(api, repository, branch_name, base_branch)
            if pr is None:
                raise StorePublishError(
                    "GitHub rejected Community Store PR creation and no open PR was found"
                )
    return {
        "status": "pull-request-open",
        "baseBranch": base_branch,
        "branch": branch_name,
        "commitSha": applied["commitSha"],
        "pullRequestNumber": pr.get("number"),
        "pullRequestUrl": pr.get("html_url"),
    }


def _publish_direct(api, plan, desired, cancel_check=None):
    repository = plan["repository"]
    base_branch = _default_branch(api, repository)
    applied = _apply_directory(
        api,
        repository,
        base_branch,
        desired,
        plan["directory"],
        f"Publish {plan['directory']} {plan['version']}",
        cancel_check=cancel_check,
    )
    return {
        "status": "updated" if applied["changed"] else "already-current",
        "baseBranch": base_branch,
        "branch": base_branch,
        "commitSha": applied["commitSha"],
        "pullRequestNumber": None,
        "pullRequestUrl": None,
    }


def publish_store(job, package_artifact_root, job_artifact_root, api=None, cancel_check=None):
    _check_cancel(cancel_check)
    plan = build_store_plan(job, package_artifact_root, job_artifact_root)
    desired = _desired_entries(plan)

    if api is None:
        token = secret_from_ref(plan.get("authRef"))
        api = GitHubAPI(token)

    _check_cancel(cancel_check)
    if plan["mode"] == "pull-request":
        publication = _publish_pull_request(api, plan, desired, cancel_check=cancel_check)
    else:
        publication = _publish_direct(api, plan, desired, cancel_check=cancel_check)

    result = {
        "repository": plan["repository"],
        "mode": plan["mode"],
        "directory": plan["directory"],
        "version": plan["version"],
        "releaseTag": plan["releaseTag"],
        "sourceRevision": plan["sourceRevision"],
        **publication,
        "publishedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    store_root = Path(job_artifact_root) / "store"
    write_private_json(store_root / "publication.json", {
        "schemaVersion": 1,
        "kind": "ForgeCoreStorePublicationReceipt",
        "jobId": job.get("id"),
        "appId": job.get("appId"),
        **result,
    })
    return result


def main():
    raise SystemExit("store-publisher.py is a ForgeCore runtime module and is not a standalone CLI")


if __name__ == "__main__":
    main()
