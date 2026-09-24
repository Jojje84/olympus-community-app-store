#!/usr/bin/env python3
"""release destination publisher for ForgeCore v2.

Publishes a prepared Phase 3 release bundle to the configured GitHub Releases
repository. All local verification happens before the first remote mutation.
"""

import base64
import hashlib
import json
import os
import platform
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


COSIGN_VERSION = "v3.1.3"
COSIGN_ASSETS = {
    "amd64": (
        "cosign-linux-amd64",
        "4629c757b7618056f8ddd7e2625ae9fdd94c0372a65049520bc7d9df9efc7f71",
    ),
    "arm64": (
        "cosign-linux-arm64",
        "c5d324e091826b0d7a78eb16fef316450b4eb9aaec045611c08ba06f5e73220a",
    ),
}


def _cosign_arch():
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "amd64"
    if machine in {"aarch64", "arm64"}:
        return "arm64"
    raise ReleasePublishError(
        f"Unsupported native architecture for pinned cosign {COSIGN_VERSION}: {machine}; "
        "ForgeCore currently supports amd64 and arm64"
    )


def ensure_cosign(cancel_check=None):
    _check_cancel(cancel_check)
    arch = _cosign_arch()
    asset, expected = COSIGN_ASSETS[arch]
    storage = Path(os.environ.get("FORGECORE_STORAGE_ROOT", "/forgecore/storage"))
    root = storage / "cache" / "toolcache" / "cosign" / COSIGN_VERSION
    root.mkdir(parents=True, exist_ok=True)
    target = root / asset

    if target.is_file():
        if sha256_file(target) == expected:
            try:
                os.chmod(target, 0o700)
            except OSError:
                pass
            return str(target)
        target.unlink()

    url = f"https://github.com/sigstore/cosign/releases/download/{COSIGN_VERSION}/{asset}"
    tmp = target.with_name("." + target.name + ".tmp")
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": "ForgeCore-v2"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response, tmp.open("wb") as handle:
            while True:
                _check_cancel(cancel_check)
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                handle.write(chunk)
        _check_cancel(cancel_check)
        if digest.hexdigest() != expected:
            raise ReleasePublishError(f"Downloaded cosign {COSIGN_VERSION} checksum mismatch for {arch}")
        os.chmod(tmp, 0o700)
        os.replace(tmp, target)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    return str(target)


class ReleasePublishError(RuntimeError):
    pass


class ReleasePublishCancelled(ReleasePublishError):
    pass


def _check_cancel(cancel_check):
    if cancel_check is not None and cancel_check():
        raise ReleasePublishCancelled("Release publication cancelled")


def write_private_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def secret_from_ref(ref):
    ref = str(ref or "")
    prefix = "secret://env/"
    if not ref.startswith(prefix):
        raise ReleasePublishError(
            "Release publishing currently requires secret://env/<NAME> auth references"
        )
    name = ref[len(prefix):]
    if not name or not name.replace("_", "A").isalnum() or name[0].isdigit():
        raise ReleasePublishError("Release auth reference contains an invalid environment variable name")
    value = os.environ.get(name)
    if not value:
        raise ReleasePublishError(f"Required release credential is missing or empty: {name}")
    return value


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_release_plan(release_root):
    path = Path(release_root) / "release-plan.json"
    if not path.is_file():
        raise ReleasePublishError(f"Release plan is missing: {path}")
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("kind") != "ForgeCoreReleasePlan":
        raise ReleasePublishError("Release plan kind is invalid")
    return plan


def verify_sha256sums(release_root, plan):
    root = Path(release_root)
    checksum_path = root / "SHA256SUMS"
    if not checksum_path.is_file():
        raise ReleasePublishError("SHA256SUMS is missing")

    expected_assets = set(plan.get("assets") or [])
    if "SHA256SUMS" not in expected_assets:
        raise ReleasePublishError("Release plan does not include SHA256SUMS")

    covered = set()
    for raw in checksum_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            expected, name = line.split(None, 1)
        except ValueError as exc:
            raise ReleasePublishError(f"Invalid SHA256SUMS line: {line}") from exc
        name = name.lstrip("*").strip()
        if "/" in name or "\\" in name or name in {".", ".."}:
            raise ReleasePublishError(f"Unsafe checksum asset name: {name}")
        path = root / name
        if not path.is_file():
            raise ReleasePublishError(f"Checksummed release asset is missing: {name}")
        actual = sha256_file(path)
        if actual != expected.lower():
            raise ReleasePublishError(f"Checksum mismatch for release asset: {name}")
        covered.add(name)

    required = expected_assets - {"SHA256SUMS"}
    missing = required - covered
    if missing:
        raise ReleasePublishError(
            "SHA256SUMS does not cover release assets: " + ", ".join(sorted(missing))
        )
    return True


def _decode_signing_material(value, encoding, label):
    raw = str(value or "")
    if encoding == "base64":
        try:
            return base64.b64decode(raw, validate=True)
        except Exception as exc:
            raise ReleasePublishError(f"{label} is not valid base64") from exc
    if encoding == "plain":
        return raw.encode("utf-8")
    raise ReleasePublishError(f"Unsupported signing material encoding: {encoding}")


def _terminate_subprocess(proc):
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _run_cosign(cosign, args, env, cancel_check=None):
    proc = subprocess.Popen(
        [cosign, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    deadline = time.monotonic() + 180
    output = ""
    while True:
        if cancel_check is not None and cancel_check():
            _terminate_subprocess(proc)
            raise ReleasePublishCancelled("Release publication cancelled during Sigstore operation")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_subprocess(proc)
            raise ReleasePublishError(f"cosign {' '.join(args[:2])} timed out after 180 seconds")
        try:
            output, _ = proc.communicate(timeout=min(0.25, remaining))
            break
        except subprocess.TimeoutExpired:
            continue
    if proc.returncode != 0:
        raise ReleasePublishError(f"cosign {' '.join(args[:2])} failed: {output.strip()[:500]}")
    return output


def prepare_sigstore_assets(job, release_root, plan, cosign=None, cancel_check=None):
    _check_cancel(cancel_check)
    if not (plan.get("verification") or {}).get("sigstore"):
        plan.pop("verificationAssets", None)
        plan.pop("signing", None)
        return []

    snapshot = job.get("snapshot") or {}
    releases = (snapshot.get("global") or {}).get("releases") or {}
    signing = releases.get("signing") or {}
    if signing.get("provider") != "sigstore-key":
        raise ReleasePublishError(
            "Publish preset requires Sigstore but global.releases.signing.provider is not sigstore-key"
        )

    required = ("privateKeyRef", "publicKeyRef", "passwordRef", "encoding")
    missing = [key for key in required if not signing.get(key)]
    if missing:
        raise ReleasePublishError("Sigstore signing config is incomplete: " + ", ".join(missing))

    private_key = _decode_signing_material(
        secret_from_ref(signing["privateKeyRef"]), signing["encoding"], "Sigstore private key"
    )
    public_key = _decode_signing_material(
        secret_from_ref(signing["publicKeyRef"]), signing["encoding"], "Sigstore public key"
    )
    password = secret_from_ref(signing["passwordRef"])

    root = Path(release_root)
    cosign = cosign or ensure_cosign(cancel_check=cancel_check)
    _check_cancel(cancel_check)
    env = os.environ.copy()
    env["COSIGN_PASSWORD"] = password

    with tempfile.TemporaryDirectory(prefix="forgecore-cosign-") as tmp:
        tmp_root = Path(tmp)
        private_path = tmp_root / "cosign.key"
        public_path = tmp_root / "cosign.pub"
        private_path.write_bytes(private_key)
        public_path.write_bytes(public_key)
        os.chmod(private_path, 0o600)
        os.chmod(public_path, 0o600)

        derived = _run_cosign(
            cosign,
            ["public-key", "--key", str(private_path)],
            env,
            cancel_check=cancel_check,
        ).strip()
        configured = public_key.decode("utf-8", "strict").strip()
        if derived != configured:
            raise ReleasePublishError("Configured Sigstore public key does not match the private signing key")

        public_asset = root / "cosign.pub"
        public_asset.write_text(configured + "\n", encoding="utf-8")
        try:
            os.chmod(public_asset, 0o600)
        except OSError:
            pass

        verification_assets = ["cosign.pub"]
        for name in plan.get("assets") or []:
            _check_cancel(cancel_check)
            artifact = root / name
            if not artifact.is_file():
                raise ReleasePublishError(f"Cannot sign missing release asset: {name}")
            bundle = root / f"{name}.sigstore.json"
            _run_cosign(
                cosign,
                [
                    "sign-blob",
                    "--yes",
                    "--key",
                    str(private_path),
                    "--bundle",
                    str(bundle),
                    str(artifact),
                ],
                env,
                cancel_check=cancel_check,
            )
            _run_cosign(
                cosign,
                [
                    "verify-blob",
                    str(artifact),
                    "--bundle",
                    str(bundle),
                    "--key",
                    str(public_path),
                ],
                env,
                cancel_check=cancel_check,
            )
            verification_assets.append(bundle.name)

    plan["verificationAssets"] = verification_assets
    plan["signing"] = {
        "provider": "sigstore-key",
        "cosignVersion": COSIGN_VERSION,
        "publicKeyAsset": "cosign.pub",
        "publicKeySha256": sha256_file(root / "cosign.pub"),
        "bundleSuffix": ".sigstore.json",
    }
    write_private_json(root / "release-plan.json", plan)
    return verification_assets


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
            status, response_headers, body = self.transport(method, url, data, headers)
        else:
            request = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    status = response.status
                    response_headers = dict(response.headers.items())
                    body = response.read()
            except urllib.error.HTTPError as exc:
                status = exc.code
                response_headers = dict(exc.headers.items()) if exc.headers else {}
                body = exc.read()

        if status not in expected:
            message = body.decode("utf-8", "replace")[:500] if isinstance(body, (bytes, bytearray)) else str(body)[:500]
            raise ReleasePublishError(f"GitHub API {method} {url} returned {status}: {message}")
        return status, response_headers, bytes(body)

    def json(self, method, url, payload=None, expected=(200,)):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        status, response_headers, body = self.request(
            method, url, data=data, headers=headers, expected=expected
        )
        if not body:
            return status, response_headers, None
        return status, response_headers, json.loads(body.decode("utf-8"))


def _api_url(repository, suffix):
    return f"https://api.github.com/repos/{repository}{suffix}"


def _find_or_create_release(api, plan, app_name):
    repository = plan["repository"]
    release_tag = plan["releaseTag"]
    encoded_tag = urllib.parse.quote(release_tag, safe="")
    lookup = _api_url(repository, f"/releases/tags/{encoded_tag}")
    status, _, existing = api.json("GET", lookup, expected=(200, 404))

    payload = {
        "tag_name": release_tag,
        "target_commitish": "main",
        "name": f"{app_name} {plan['sourceTag']}",
        "body": (
            f"Published by ForgeCore job {plan['jobId']}.\n\n"
            f"Source revision: {plan['sourceRevision']}\n"
        ),
        "draft": False,
        "prerelease": bool(plan.get("prerelease")),
    }

    if status == 404:
        _, _, created = api.json(
            "POST",
            _api_url(repository, "/releases"),
            payload,
            expected=(201,),
        )
        return created

    release_id = existing["id"]
    _, _, updated = api.json(
        "PATCH",
        _api_url(repository, f"/releases/{release_id}"),
        payload,
        expected=(200,),
    )
    return updated


def _list_assets(api, repository, release_id):
    _, _, assets = api.json(
        "GET",
        _api_url(repository, f"/releases/{release_id}/assets?per_page=100"),
        expected=(200,),
    )
    return assets or []


def _upload_asset(api, repository, release_id, path):
    name = Path(path).name
    query = urllib.parse.urlencode({"name": name})
    url = f"https://uploads.github.com/repos/{repository}/releases/{release_id}/assets?{query}"
    data = Path(path).read_bytes()
    _, _, asset = api.request(
        "POST",
        url,
        data=data,
        headers={"Content-Type": "application/octet-stream"},
        expected=(201,),
    )
    return json.loads(asset.decode("utf-8"))


def _replace_asset(api, repository, release_id, local_path, existing_assets):
    name = Path(local_path).name
    existing = next((item for item in existing_assets if item.get("name") == name), None)
    if existing is not None:
        api.request(
            "DELETE",
            _api_url(repository, f"/releases/assets/{existing['id']}"),
            expected=(204,),
        )
    return _upload_asset(api, repository, release_id, local_path)


def _download_and_verify(api, asset, local_path):
    url = asset.get("url") or asset.get("browser_download_url")
    if not url:
        raise ReleasePublishError(f"Published asset has no download URL: {asset.get('name')}")
    _, _, body = api.request(
        "GET",
        url,
        headers={"Accept": "application/octet-stream"},
        expected=(200,),
    )
    expected = sha256_file(local_path)
    actual = hashlib.sha256(body).hexdigest()
    if actual != expected:
        raise ReleasePublishError(f"Published asset verification failed: {asset.get('name')}")
    if len(body) != Path(local_path).stat().st_size:
        raise ReleasePublishError(f"Published asset size mismatch: {asset.get('name')}")


def _channel_file(api, repository, path, ref="main"):
    encoded_path = urllib.parse.quote(path, safe="/")
    query = urllib.parse.urlencode({"ref": ref})
    status, _, item = api.json(
        "GET",
        _api_url(repository, f"/contents/{encoded_path}?{query}"),
        expected=(200, 404),
    )
    if status == 404:
        return None, None
    content = base64.b64decode(item.get("content") or "").decode("utf-8")
    return json.loads(content), item.get("sha")


def _release_channel_payload(job, plan, current):
    payload = dict(current or {})
    app = (job.get("snapshot") or {}).get("app") or {}
    app_name = (app.get("identity") or {}).get("name") or plan["appId"]
    repository = plan["repository"]
    release_tag = plan["releaseTag"]
    channel = str(plan.get("channel") or "stable")
    package_name = next(
        (name for name in plan.get("assets") or [] if name.endswith(".tar.gz")),
        None,
    )
    if not package_name:
        raise ReleasePublishError("Release plan has no package archive")

    payload.update({
        "schema_version": 1,
        "product": app_name,
        "product_id": plan["appId"],
        "channel": channel,
        "status": channel,
        "releases_url": f"https://github.com/{repository}/releases",
    })
    payload["latest"] = {
        "version": plan["version"],
        "tag": plan["sourceTag"],
        "release_tag": release_tag,
        "url": f"https://github.com/{repository}/releases/tag/{release_tag}",
        "published_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_revision": plan["sourceRevision"],
        "package": package_name,
        "checksums": "SHA256SUMS",
    }
    if (plan.get("verification") or {}).get("sigstore"):
        signing = plan.get("signing") or {}
        payload["latest"]["signing"] = {
            "format": "sigstore-bundle",
            "provider": signing.get("provider"),
            "bundle_suffix": signing.get("bundleSuffix", ".sigstore.json"),
            "public_key_asset": signing.get("publicKeyAsset"),
            "public_key_sha256": signing.get("publicKeySha256"),
            "cosign_version": signing.get("cosignVersion"),
        }
    return payload


def _stable_channel_payload(job, plan, current):
    """Phase 3 compatibility wrapper for stable-channel tests/consumers."""
    stable_plan = dict(plan)
    stable_plan["channel"] = "stable"
    return _release_channel_payload(job, stable_plan, current)


def _open_channel_pr(api, repository, branch_name):
    owner = repository.split("/", 1)[0]
    query = urllib.parse.urlencode({
        "state": "open",
        "head": f"{owner}:{branch_name}",
        "base": "main",
        "per_page": 100,
    })
    _, _, pulls = api.json(
        "GET",
        _api_url(repository, f"/pulls?{query}"),
        expected=(200,),
    )
    return (pulls or [None])[0]


def _merge_channel_pr(api, repository, pr):
    number = pr["number"]
    status, _, result = api.json(
        "PUT",
        _api_url(repository, f"/pulls/{number}/merge"),
        {
            "merge_method": "squash",
            "commit_title": pr.get("title") or "Publish release channel via ForgeCore",
        },
        expected=(200, 405, 409),
    )
    if status == 200 and result and result.get("merged"):
        return result
    url = pr.get("html_url") or f"https://github.com/{repository}/pull/{number}"
    message = (result or {}).get("message") if isinstance(result, dict) else None
    raise ReleasePublishError(
        f"Release channel PR is waiting for required checks or mergeability: {url}"
        + (f" ({message})" if message else "")
    )


def _plan_updates_channel(plan):
    if "updateChannel" in plan:
        return bool(plan.get("updateChannel"))
    # Plans created before Phase 8 may only carry the Phase 3 stable flag.
    return bool(plan.get("updateStableChannel")) and str(plan.get("channel") or "stable") == "stable"


def _plan_channel_path(plan):
    path = plan.get("channelPath")
    if path:
        return path
    if str(plan.get("channel") or "stable") == "stable":
        return plan.get("stableChannelPath")
    return None


def update_release_channel(api, job, plan, cancel_check=None):
    channel = str(plan.get("channel") or "stable")
    if channel not in {"stable", "beta", "prerelease"}:
        raise ReleasePublishError(f"Unsupported release channel: {channel}")
    if not _plan_updates_channel(plan):
        return {"status": "not-required", "channel": channel}

    _check_cancel(cancel_check)
    repository = plan["repository"]
    channel_path = _plan_channel_path(plan)
    if not channel_path:
        raise ReleasePublishError(f"{channel} release plan is missing channelPath")

    expected_path = f"channels/{plan['appId']}/{channel}.json"
    if channel_path != expected_path:
        raise ReleasePublishError(
            f"Release channel path must be {expected_path}, got {channel_path}"
        )

    current, current_sha = _channel_file(api, repository, channel_path, "main")
    if ((current or {}).get("latest") or {}).get("release_tag") == plan["releaseTag"]:
        return {
            "status": "updated",
            "channel": channel,
            "path": channel_path,
            "alreadyCurrent": True,
        }

    # Keep the historical stable branch name so retries can reuse Phase 3 PRs.
    if channel == "stable":
        branch_name = f"release/{plan['appId']}-{plan['sourceTag']}"
    else:
        branch_name = f"release/{plan['appId']}-{channel}-{plan['sourceTag']}"
    existing_pr = _open_channel_pr(api, repository, branch_name)
    if existing_pr is not None:
        _check_cancel(cancel_check)
        _merge_channel_pr(api, repository, existing_pr)
        verified, _ = _channel_file(api, repository, channel_path, "main")
        if ((verified or {}).get("latest") or {}).get("release_tag") != plan["releaseTag"]:
            raise ReleasePublishError(
                f"{channel} channel PR merged but main does not contain the expected release"
            )
        return {
            "status": "updated",
            "channel": channel,
            "path": channel_path,
            "pullRequest": existing_pr.get("html_url"),
            "alreadyCurrent": False,
        }

    _, _, main_ref = api.json(
        "GET",
        _api_url(repository, "/git/ref/heads/main"),
        expected=(200,),
    )
    main_sha = main_ref["object"]["sha"]
    encoded_branch = urllib.parse.quote(branch_name, safe="")
    status, _, branch_ref = api.json(
        "GET",
        _api_url(repository, f"/git/ref/heads/{encoded_branch}"),
        expected=(200, 404),
    )
    if status == 404:
        api.json(
            "POST",
            _api_url(repository, "/git/refs"),
            {"ref": f"refs/heads/{branch_name}", "sha": main_sha},
            expected=(201,),
        )
    else:
        api.json(
            "PATCH",
            _api_url(repository, f"/git/refs/heads/{encoded_branch}"),
            {"sha": main_sha, "force": True},
            expected=(200,),
        )

    _check_cancel(cancel_check)
    updated_payload = _release_channel_payload(job, plan, current)
    encoded_path = urllib.parse.quote(channel_path, safe="/")
    put_payload = {
        "message": f"Publish {plan['sourceTag']} {channel} channel",
        "content": base64.b64encode(
            (json.dumps(updated_payload, indent=2) + "\n").encode("utf-8")
        ).decode("ascii"),
        "branch": branch_name,
    }
    if current_sha:
        put_payload["sha"] = current_sha
    api.json(
        "PUT",
        _api_url(repository, f"/contents/{encoded_path}"),
        put_payload,
        expected=(200, 201),
    )

    _check_cancel(cancel_check)
    title = f"Publish {plan['sourceTag']} {channel} channel"
    status, _, pr = api.json(
        "POST",
        _api_url(repository, "/pulls"),
        {
            "title": title,
            "body": (
                f"Updates {channel_path} after ForgeCore verified "
                f"{plan['releaseTag']} release assets."
            ),
            "head": branch_name,
            "base": "main",
        },
        expected=(201, 422),
    )
    if status == 422:
        pr = _open_channel_pr(api, repository, branch_name)
        if pr is None:
            raise ReleasePublishError(
                "GitHub rejected release channel PR creation and no open PR was found"
            )
    _check_cancel(cancel_check)
    _merge_channel_pr(api, repository, pr)

    verified, _ = _channel_file(api, repository, channel_path, "main")
    if ((verified or {}).get("latest") or {}).get("release_tag") != plan["releaseTag"]:
        raise ReleasePublishError(
            f"{channel} channel merge completed but verification of main failed"
        )
    return {
        "status": "updated",
        "channel": channel,
        "path": channel_path,
        "pullRequest": pr.get("html_url"),
        "alreadyCurrent": False,
    }


def update_stable_channel(api, job, plan, cancel_check=None):
    """Compatibility entry point retained for Phase 3 callers."""
    if str(plan.get("channel") or "stable") != "stable":
        return {"status": "not-required"}
    result = update_release_channel(api, job, plan, cancel_check=cancel_check)
    if result.get("status") == "not-required":
        return {"status": "not-required"}
    return result

def publish_release(job, artifact_root, api=None, cancel_check=None):
    artifact_root = Path(artifact_root)
    release_root = artifact_root / "release"
    _check_cancel(cancel_check)
    plan = load_release_plan(release_root)

    if plan.get("jobId") != job.get("id") or plan.get("appId") != job.get("appId"):
        raise ReleasePublishError("Release plan does not belong to this job/app")

    snapshot = job.get("snapshot") or {}
    global_config = snapshot.get("global") or {}
    releases = global_config.get("releases") or {}
    repository = str(releases.get("repository") or "")
    if repository != plan.get("repository"):
        raise ReleasePublishError("Release plan repository differs from immutable job snapshot")

    if (plan.get("verification") or {}).get("sha256"):
        verify_sha256sums(release_root, plan)
    verification_assets = prepare_sigstore_assets(
        job,
        release_root,
        plan,
        cancel_check=cancel_check,
    )

    _check_cancel(cancel_check)
    if api is None:
        token = secret_from_ref(releases.get("authRef"))
        api = GitHubAPI(token)

    app = snapshot.get("app") or {}
    app_name = (app.get("identity") or {}).get("name") or job.get("appId")
    release = _find_or_create_release(api, plan, app_name)
    release_id = release["id"]

    publish_assets = list(plan.get("assets") or []) + list(verification_assets)
    existing_assets = _list_assets(api, repository, release_id)
    uploaded = []
    for name in publish_assets:
        _check_cancel(cancel_check)
        path = release_root / name
        if not path.is_file():
            raise ReleasePublishError(f"Planned release asset is missing: {name}")
        asset = _replace_asset(api, repository, release_id, path, existing_assets)
        uploaded.append(asset)
        existing_assets = [item for item in existing_assets if item.get("name") != name]
        existing_assets.append(asset)

    final_assets = _list_assets(api, repository, release_id)
    by_name = {item.get("name"): item for item in final_assets}
    for name in publish_assets:
        _check_cancel(cancel_check)
        asset = by_name.get(name)
        if asset is None:
            raise ReleasePublishError(f"Published release is missing expected asset: {name}")
        _download_and_verify(api, asset, release_root / name)

    _check_cancel(cancel_check)
    release_channel = update_release_channel(api, job, plan, cancel_check=cancel_check)
    channel_name = str(plan.get("channel") or "stable")
    updates_channel = _plan_updates_channel(plan)
    updates_stable = updates_channel and channel_name == "stable"

    result = {
        "repository": repository,
        "releaseId": release_id,
        "releaseTag": plan["releaseTag"],
        "channel": channel_name,
        "prerelease": bool(plan.get("prerelease")),
        "verifiedAssets": publish_assets,
        "updateChannel": updates_channel,
        "releaseChannel": release_channel,
        # Legacy receipt fields remain available to Phase 3 readers.
        "updateStableChannel": updates_stable,
        "stableChannel": release_channel if channel_name == "stable" else {"status": "not-required"},
        "publishedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    write_private_json(release_root / "publication.json", {
        "schemaVersion": 1,
        "kind": "ForgeCorePublicationReceipt",
        "jobId": job.get("id"),
        "appId": job.get("appId"),
        **result,
    })
    return result
