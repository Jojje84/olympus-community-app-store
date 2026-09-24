#!/usr/bin/env python3
"""Deterministic ForgeCore v2 release packaging.

Consumes the immutable Phase 2 artifact handoff and creates the files required by
an release destination publication. Network publication is deliberately separate so
release assets can be verified before any remote mutation occurs.
"""

import gzip
import hashlib
import json
import os
import re
import tarfile
from pathlib import Path

NORMALIZED_MTIME = 1577836800  # 2020-01-01T00:00:00Z
VERSION_RE = re.compile(r"^[0-9A-Za-z]+(?:[0-9A-Za-z.+-]*[0-9A-Za-z])?$")


class ReleasePackagingError(RuntimeError):
    pass


def ensure_private_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def write_private_text(path, value):
    path = Path(path)
    ensure_private_dir(path.parent)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(value, encoding="utf-8", newline="\n")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def write_private_json(path, payload):
    write_private_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifact_manifest(package_root, manifest):
    package_root = Path(package_root)
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ReleasePackagingError("Artifact manifest files must be an array")

    expected = {}
    for entry in entries:
        name = str((entry or {}).get("path") or "")
        if not name or name.startswith("/") or "\\" in name:
            raise ReleasePackagingError(f"Unsafe artifact manifest path: {name}")
        parts = name.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ReleasePackagingError(f"Unsafe artifact manifest path: {name}")
        if name in expected:
            raise ReleasePackagingError(f"Duplicate artifact manifest path: {name}")
        expected[name] = entry

    actual = {}
    for path in sorted(package_root.rglob("*")):
        if path.is_symlink():
            raise ReleasePackagingError(f"Artifact handoff contains a symlink: {path}")
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
        raise ReleasePackagingError("Artifact handoff differs from manifest: " + " ".join(details))

    total = 0
    for name, path in actual.items():
        entry = expected[name]
        size = path.stat().st_size
        total += size
        if entry.get("size") != size:
            raise ReleasePackagingError(f"Artifact size mismatch: {name}")
        if str(entry.get("sha256") or "").lower() != sha256_file(path):
            raise ReleasePackagingError(f"Artifact checksum mismatch: {name}")

    if manifest.get("fileCount") != len(actual):
        raise ReleasePackagingError("Artifact manifest fileCount does not match package contents")
    if manifest.get("totalBytes") != total:
        raise ReleasePackagingError("Artifact manifest totalBytes does not match package contents")
    return True


def parse_release_ref(ref):
    ref = str(ref or "").strip()
    if ref.startswith("refs/tags/"):
        tag = ref[len("refs/tags/"):]
    else:
        tag = ref
    if not tag.startswith("v") or len(tag) < 2:
        raise ReleasePackagingError("Release jobs require a v-prefixed tag ref")
    version = tag[1:]
    if not VERSION_RE.fullmatch(version):
        raise ReleasePackagingError(f"Unsupported release version: {version}")
    return tag, version


def render_template(value, app):
    replacements = {
        "{app.id}": str(app["id"]),
        "{app.storeId}": str((app.get("identity") or {}).get("storeId") or ""),
    }
    rendered = str(value)
    for key, replacement in replacements.items():
        rendered = rendered.replace(key, replacement)
    if "{" in rendered or "}" in rendered:
        raise ReleasePackagingError(f"Unsupported publish template: {value}")
    return rendered


def _tar_entries(package_root, archive_root):
    yield package_root, archive_root, True
    for path in sorted(package_root.rglob("*"), key=lambda item: item.relative_to(package_root).as_posix()):
        relative = path.relative_to(package_root).as_posix()
        yield path, f"{archive_root}/{relative}", path.is_dir()


def create_deterministic_archive(package_root, destination, archive_root):
    package_root = Path(package_root)
    destination = Path(destination)
    if not package_root.is_dir():
        raise ReleasePackagingError(f"Package handoff directory is missing: {package_root}")

    ensure_private_dir(destination.parent)
    tmp = destination.with_name("." + destination.name + ".tmp")
    try:
        with tmp.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as zipped:
                with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as archive:
                    for path, name, is_dir in _tar_entries(package_root, archive_root):
                        info = tarfile.TarInfo(name + ("/" if is_dir and not name.endswith("/") else ""))
                        stat = path.stat()
                        info.uid = 0
                        info.gid = 0
                        info.uname = ""
                        info.gname = ""
                        info.mtime = NORMALIZED_MTIME
                        if is_dir:
                            info.type = tarfile.DIRTYPE
                            info.mode = 0o755
                            info.size = 0
                            archive.addfile(info)
                            continue
                        if not path.is_file():
                            raise ReleasePackagingError(f"Unsupported package entry: {path}")
                        info.mode = 0o755 if stat.st_mode & 0o111 else 0o644
                        info.size = stat.st_size
                        with path.open("rb") as handle:
                            archive.addfile(info, fileobj=handle)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, destination)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    return destination


def build_release_bundle(job, artifact_root, output_root, source_revision):
    snapshot = job.get("snapshot") or {}
    app = snapshot.get("app") or {}
    preset = snapshot.get("publishPreset") or {}
    global_config = snapshot.get("global") or {}
    trigger = job.get("trigger") or {}

    if not app.get("id"):
        raise ReleasePackagingError("Job snapshot is missing app identity")
    if not preset:
        raise ReleasePackagingError("Release job snapshot is missing publish preset")
    if not global_config:
        raise ReleasePackagingError("Release job snapshot is missing global configuration")

    release_policy = preset.get("release") or {}
    if not release_policy.get("enabled"):
        raise ReleasePackagingError("Publish preset has release publishing disabled")

    tag, version = parse_release_ref(trigger.get("ref"))
    app_id = app["id"]
    package_format = (app.get("package") or {}).get("format")
    source_path = (app.get("package") or {}).get("sourcePath")
    if not package_format or not source_path:
        raise ReleasePackagingError("App package configuration is incomplete")

    artifact_root = Path(artifact_root)
    package_root = artifact_root / "package"
    manifest_path = artifact_root / "manifest.json"
    if not manifest_path.is_file():
        raise ReleasePackagingError(f"Artifact manifest is missing: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_source = job.get("artifactSource") or {}
    expected_artifact_job = artifact_source.get("jobId") or job.get("id")
    if manifest.get("jobId") != expected_artifact_job or manifest.get("appId") != app_id:
        raise ReleasePackagingError("Artifact manifest does not belong to the selected job/app")
    if artifact_source:
        expected_manifest_sha = str(artifact_source.get("manifestSha256") or "")
        actual_manifest_sha = "sha256:" + sha256_file(manifest_path)
        if expected_manifest_sha != actual_manifest_sha:
            raise ReleasePackagingError("Artifact manifest changed after publish job creation")
        if str(manifest.get("sourceRevision") or "").lower() != str(artifact_source.get("sourceRevision") or "").lower():
            raise ReleasePackagingError("Artifact source revision differs from the publish job contract")
    verify_artifact_manifest(package_root, manifest)

    source_revision = str(source_revision or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", source_revision):
        raise ReleasePackagingError("A full source revision SHA is required for release provenance")
    source_revision = source_revision.lower()

    release_repo = ((global_config.get("releases") or {}).get("repository") or "").strip()
    if not release_repo:
        raise ReleasePackagingError("Global release destination repository is not configured")

    tag_prefix = render_template(release_policy.get("tagPrefixTemplate") or "", app)
    release_tag = f"{tag_prefix}{tag}"
    version_prerelease = "-" in version
    configured_channel = str(release_policy.get("channel") or "stable")
    if configured_channel not in {"stable", "beta", "prerelease"}:
        raise ReleasePackagingError(f"Unsupported release channel: {configured_channel}")
    # A prerelease tag can never advance the stable feed. New Phase 8 presets may
    # instead advance the dedicated prerelease feed; legacy presets retain the
    # Phase 3 behavior and do not gain new channel mutations implicitly.
    channel = "prerelease" if version_prerelease and configured_channel == "stable" else configured_channel
    prerelease = version_prerelease or channel != "stable"
    legacy_update_stable = bool(release_policy.get("updateStableChannel")) and channel == "stable"
    if "updateChannel" in release_policy:
        update_channel = bool(release_policy.get("updateChannel"))
    else:
        update_channel = legacy_update_stable
    channel_path = f"channels/{app_id}/{channel}.json" if update_channel else None
    update_stable = update_channel and channel == "stable"

    output_root = ensure_private_dir(output_root)
    archive_name = f"{app_id}_{version}_{package_format}.tar.gz"
    source_leaf = Path(str(source_path).rstrip("/")).name or package_format
    archive_root = f"{app_id}_{version}/{source_leaf}"
    archive_path = create_deterministic_archive(package_root, output_root / archive_name, archive_root)

    provenance_name = f"{app_id}_{version}_release.json"
    provenance = {
        "schema_version": 1,
        "product": (app.get("identity") or {}).get("name") or app_id,
        "product_id": app_id,
        "version": version,
        "tag": tag,
        "release_tag": release_tag,
        "source_revision": source_revision,
        "source_repository": ((app.get("source") or {}).get("repository") or ""),
        "config_revision": job.get("configRevision"),
        "artifact_manifest_sha256": sha256_file(manifest_path),
        "package": archive_name,
        "package_format": package_format,
    }
    provenance_path = output_root / provenance_name
    write_private_json(provenance_path, provenance)

    checksummed = [archive_path, provenance_path]
    checksum_lines = [f"{sha256_file(path)}  {path.name}" for path in sorted(checksummed, key=lambda p: p.name)]
    checksums_path = output_root / "SHA256SUMS"
    write_private_text(checksums_path, "\n".join(checksum_lines) + "\n")

    verification = preset.get("verification") or {}
    plan = {
        "schemaVersion": 1,
        "kind": "ForgeCoreReleasePlan",
        "jobId": job.get("id"),
        "appId": app_id,
        "version": version,
        "sourceTag": tag,
        "sourceRevision": source_revision,
        "repository": release_repo,
        "releaseTag": release_tag,
        "channel": channel,
        "prerelease": prerelease,
        "updateChannel": update_channel,
        "channelPath": channel_path,
        # Legacy Phase 3 fields remain in the plan for stable-channel consumers.
        "updateStableChannel": update_stable,
        "stableChannelPath": f"channels/{app_id}/stable.json" if update_stable else None,
        "assets": [archive_name, provenance_name, "SHA256SUMS"],
        "verification": {
            "sha256": bool(verification.get("sha256")),
            "sigstore": bool(verification.get("sigstore")),
        },
    }
    plan_path = output_root / "release-plan.json"
    write_private_json(plan_path, plan)

    return {
        "archive": archive_path,
        "provenance": provenance_path,
        "checksums": checksums_path,
        "plan": plan_path,
        "releasePlan": plan,
    }
