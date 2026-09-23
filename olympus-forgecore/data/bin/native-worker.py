#!/usr/bin/env python3
"""ForgeCore v2 native execution worker.

Consumes Phase 1 job state through dashboard-server.py's ExecutorAdapter contract.
The worker owns native workspaces, source checkout, command execution, logs,
timeouts/cancellation, package artifact handoff, Olympus Releases publication and
Community App Store submission.
"""

import argparse
import base64
import codecs
import hashlib
import importlib.util
import json
import os
import selectors
import shutil
import signal
import subprocess
import time
from pathlib import Path

APP_ROOT = Path(os.environ.get("FORGECORE_APP_ROOT", "/forgecore/app"))
STORAGE_ROOT = Path(os.environ.get("FORGECORE_STORAGE_ROOT", "/forgecore/storage"))
CONTROL_MODULE = Path(os.environ.get("FORGECORE_CONTROL_MODULE", "/forgecore/runtime/dashboard-server.py"))
RELEASE_PACKAGER_MODULE = Path(os.environ.get("FORGECORE_RELEASE_PACKAGER_MODULE", str(APP_ROOT / "bin" / "release-packager.py")))
RELEASE_PUBLISHER_MODULE = Path(os.environ.get("FORGECORE_RELEASE_PUBLISHER_MODULE", str(APP_ROOT / "bin" / "release-publisher.py")))
STORE_PUBLISHER_MODULE = Path(os.environ.get("FORGECORE_STORE_PUBLISHER_MODULE", str(APP_ROOT / "bin" / "store-publisher.py")))
ISOLATED_RUNTIME_MODULE = Path(os.environ.get("FORGECORE_ISOLATED_RUNTIME_MODULE", str(APP_ROOT / "bin" / "isolated-runtime.py")))
POLL_SECONDS = max(0.25, float(os.environ.get("FORGECORE_NATIVE_POLL_SECONDS", "2")))
DEFAULT_TIMEOUT_SECONDS = max(1, int(os.environ.get("FORGECORE_NATIVE_DEFAULT_TIMEOUT_SECONDS", "1800")))
MAX_LOG_LINE = 64 * 1024

WORKSPACES = STORAGE_ROOT / "workspaces"
LOG_ROOT = STORAGE_ROOT / "logs" / "jobs"
ARTIFACT_ROOT = STORAGE_ROOT / "artifacts"


class NativeExecutionError(RuntimeError):
    pass


class CommandTimeout(NativeExecutionError):
    pass


class CommandCancelled(NativeExecutionError):
    pass


def load_control_module(path=CONTROL_MODULE):
    spec = importlib.util.spec_from_file_location("forgecore_native_control", path)
    if spec is None or spec.loader is None:
        raise NativeExecutionError(f"Could not load ForgeCore control module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_release_packager(path=RELEASE_PACKAGER_MODULE):
    spec = importlib.util.spec_from_file_location("forgecore_release_packager", path)
    if spec is None or spec.loader is None:
        raise NativeExecutionError(f"Could not load ForgeCore release packager: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_release_publisher(path=RELEASE_PUBLISHER_MODULE):
    spec = importlib.util.spec_from_file_location("forgecore_release_publisher", path)
    if spec is None or spec.loader is None:
        raise NativeExecutionError(f"Could not load ForgeCore release publisher: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_store_publisher(path=STORE_PUBLISHER_MODULE):
    spec = importlib.util.spec_from_file_location("forgecore_store_publisher", path)
    if spec is None or spec.loader is None:
        raise NativeExecutionError(f"Could not load ForgeCore Community Store publisher: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_isolated_runtime(path=ISOLATED_RUNTIME_MODULE):
    spec = importlib.util.spec_from_file_location("forgecore_isolated_runtime", path)
    if spec is None or spec.loader is None:
        raise NativeExecutionError(f"Could not load ForgeCore isolated runtime: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ensure_private_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def write_private_json(path, data):
    ensure_private_dir(path.parent)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def validate_relative_path(value, label):
    value = str(value or "").strip()
    if not value or value.startswith("/") or "\\" in value:
        raise NativeExecutionError(f"{label} must be a relative POSIX path")
    parts = [part for part in value.split("/") if part]
    if not parts or any(part in (".", "..") for part in parts):
        raise NativeExecutionError(f"{label} contains an invalid path segment")
    return Path(*parts)


def secret_from_ref(ref):
    ref = str(ref or "")
    prefix = "secret://env/"
    if not ref.startswith(prefix):
        raise NativeExecutionError(f"Unsupported secret reference: {ref}")
    name = ref[len(prefix):]
    if not name or not name.replace("_", "A").isalnum() or name[0].isdigit():
        raise NativeExecutionError("secret://env reference contains an invalid environment variable name")
    value = os.environ.get(name)
    if value is None:
        raise NativeExecutionError(f"Required secret environment variable is missing: {name}")
    return value


class Redactor:
    def __init__(self, values=None):
        self.values = []
        for value in values or []:
            self.add(value)

    def add(self, value):
        value = str(value or "")
        if len(value) >= 4 and value not in self.values:
            self.values.append(value)
            self.values.sort(key=len, reverse=True)

    def text(self, value):
        value = str(value)
        for secret in self.values:
            value = value.replace(secret, "***")
        return value


class JobLog:
    def __init__(self, job_id, redactor):
        self.root = ensure_private_dir(LOG_ROOT / job_id)
        self.redactor = redactor
        self.job_path = self.root / "job.log"
        self.stage_path = None

    def set_stage(self, stage):
        self.stage_path = self.root / f"{stage}.log"

    def write(self, message):
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        clean = self.redactor.text(str(message).rstrip("\n"))
        line = f"{stamp} {clean}\n"
        for path in (self.job_path, self.stage_path):
            if path is None:
                continue
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        print(clean, flush=True)


class NativeExecutionEngine:
    def __init__(self, control=None, isolated_runtime=None):
        self.control = control or load_control_module()
        self.adapter = self.control.executor_adapter("forgecore-native")
        self._isolated_runtime = isolated_runtime
        self._isolated_module = None
        ensure_private_dir(WORKSPACES)
        ensure_private_dir(LOG_ROOT)
        ensure_private_dir(ARTIFACT_ROOT)
        self._recover_orphaned_jobs()

    def _recover_orphaned_jobs(self):
        jobs, _ = self.control.jobs(limit=500)
        for job in jobs:
            if job.get("executor") != "forgecore-native" or job.get("status") not in {"preparing", "running"}:
                continue
            job_id = job["id"]
            if self._isolated_enabled(job):
                try:
                    self._get_isolated_runtime().cleanup_job(job_id)
                except Exception as exc:
                    print(f"[native] isolated cleanup warning for {job_id}: {exc}", flush=True)
            try:
                if job.get("status") == "running" and job.get("cancelRequested"):
                    self.adapter.acknowledge_cancel(job_id)
                    continue
                message = "Native worker restarted before the previous execution finished"
                if job.get("status") == "running" and job.get("currentStage"):
                    self.adapter.finish_stage(job_id, job["currentStage"], "failed", message)
                else:
                    self.control.transition_job(job_id, "failed", message)
            except Exception as exc:
                print(f"[native] could not recover orphaned job {job_id}: {exc}", flush=True)

    def run_once(self):
        job = self.adapter.claim()
        if job is None:
            return False
        self.run_job(job)
        return True

    def run_job(self, job):
        job_id = job["id"]
        redactor = Redactor(self._ambient_secret_values())
        log = JobLog(job_id, redactor)
        workspace = WORKSPACES / job_id
        try:
            self._prepare_workspace(workspace)
            log.write(f"[native] claimed job {job_id} for {job['appId']}")
            job = self.adapter.start(job_id)
            for stage in job["stages"]:
                if stage["status"] == "skipped":
                    continue
                if self.adapter.cancellation_requested(job["id"]):
                    self.adapter.acknowledge_cancel(job_id)
                    log.write("[native] cancellation acknowledged before next stage")
                    return
                name = stage["name"]
                log.set_stage(name)
                self.adapter.start_stage(job_id, name)
                try:
                    message = self._run_stage(job, name, workspace, log, redactor)
                except CommandCancelled:
                    self.adapter.acknowledge_cancel(job_id)
                    log.write(f"[native] stage {name} cancelled")
                    return
                except Exception as exc:
                    message = self._safe_error(exc, redactor)
                    self.adapter.finish_stage(job_id, name, "failed", message)
                    log.write(f"[native] stage {name} failed: {message}")
                    return
                self.adapter.finish_stage(job_id, name, "succeeded", message)
                log.write(f"[native] stage {name} succeeded")
            final = self.control.get_job(job_id)
            if final and final.get("status") == "succeeded":
                log.write(f"[native] job {job_id} succeeded")
        except Exception as exc:
            message = self._safe_error(exc, redactor)
            current = self.control.get_job(job_id)
            if current and current.get("status") in {"preparing", "running"}:
                if current.get("status") == "running" and current.get("currentStage"):
                    try:
                        self.adapter.finish_stage(job_id, current["currentStage"], "failed", message)
                    except Exception:
                        pass
                else:
                    try:
                        self.control.transition_job(job_id, "failed", message)
                    except Exception:
                        pass
            log.write(f"[native] job {job_id} failed: {message}")

    def _run_stage(self, job, stage, workspace, log, redactor):
        if stage == "source":
            self._checkout_source(job, workspace, log, redactor)
            return "Source checkout completed"
        if stage in {"build", "test", "verify"}:
            count = self._run_configured_steps(job, stage, workspace, log, redactor)
            return f"Executed {count} native step(s)" if count else "No commands configured"
        if stage == "package":
            manifest = self._handoff_package(job, workspace, log)
            release_stage = next((item for item in job.get("stages", []) if item.get("name") == "release"), None)
            if release_stage and release_stage.get("status") != "skipped":
                bundle = self._prepare_release_bundle(job, workspace, log)
                return (
                    f"Artifact handoff created with {manifest['fileCount']} file(s); "
                    f"release bundle prepared for {bundle['releasePlan']['releaseTag']}"
                )
            return f"Artifact handoff created with {manifest['fileCount']} file(s)"
        if stage == "release":
            if job.get("jobType") == "publish":
                self._prepare_publish_only_release_bundle(job, log)
            published = self._publish_release(job, log)
            channel = published.get("releaseChannel") or published.get("stableChannel") or {}
            suffix = ""
            if channel.get("status") == "updated":
                channel_name = channel.get("channel") or published.get("channel") or "stable"
                suffix = f"; {channel_name} channel updated"
            return (
                f"Published and verified {len(published['verifiedAssets'])} asset(s) "
                f"for {published['releaseTag']}{suffix}"
            )
        if stage == "store":
            published = self._publish_store(job, log)
            status = published.get("status") or "submitted"
            if status == "pull-request-open":
                return f"Community Store PR ready for {published['directory']}"
            return f"Community Store {status} for {published['directory']}"
        raise NativeExecutionError(f"Unsupported native stage: {stage}")

    def _prepare_workspace(self, workspace):
        if workspace.exists():
            shutil.rmtree(workspace)
        ensure_private_dir(workspace)

    def _github_token(self, job):
        global_config = job.get("snapshot", {}).get("global") or {}
        github = global_config.get("github") or {}
        auth_ref = github.get("authRef")
        if auth_ref:
            return secret_from_ref(auth_ref)
        return os.environ.get("FORGECORE_GITHUB_TOKEN")

    def _checkout_source(self, job, workspace, log, redactor):
        app = job["snapshot"]["app"]
        source = app["source"]
        repo = source["repository"]
        ref = job["trigger"]["ref"]
        remote = f"https://github.com/{repo}.git"
        token = self._github_token(job)
        if token:
            redactor.add(token)
        elif source.get("private"):
            raise NativeExecutionError(
                "Private GitHub source requires global.github.authRef=secret://env/<NAME> "
                "or FORGECORE_GITHUB_TOKEN"
            )
        log.write(f"[source] fetching {repo} @ {ref}")
        self._run_process(["git", "init", "-q", "."], workspace, log, redactor, 120, job)
        self._run_process(["git", "remote", "add", "origin", remote], workspace, log, redactor, 30, job)
        env = {}
        if token:
            auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            env.update({
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {auth}",
            })
            redactor.add(auth)
        self._run_process(
            ["git", "fetch", "--force", "--depth=1", "origin", ref],
            workspace,
            log,
            redactor,
            900,
            job,
            extra_env=env,
        )
        self._run_process(["git", "checkout", "--detach", "FETCH_HEAD"], workspace, log, redactor, 60, job)
        revision = self._capture_process(["git", "rev-parse", "HEAD"], workspace, 30, extra_env=env)
        log.write(f"[source] checked out {revision.strip()}")

    @staticmethod
    def _runtime_config(job):
        global_config = job.get("snapshot", {}).get("global") or {}
        runtime = global_config.get("runtime") if isinstance(global_config, dict) else {}
        return runtime if isinstance(runtime, dict) else {}

    def _isolated_enabled(self, job):
        return self._runtime_config(job).get("isolatedDocker") is True

    def _get_isolated_runtime(self):
        if self._isolated_runtime is None:
            module = load_isolated_runtime()
            self._isolated_module = module
            self._isolated_runtime = module.DockerBuildRuntime(
                host=os.environ.get("FORGECORE_BUILD_DOCKER_HOST", "http://build-docker:2375"),
                storage_root=STORAGE_ROOT,
            )
        return self._isolated_runtime

    @staticmethod
    def _base_isolated_env(job):
        app = job.get("snapshot", {}).get("app", {})
        return {
            "CI": "true",
            "FORGECORE_JOB_ID": job["id"],
            "FORGECORE_APP_ID": job["appId"],
            "FORGECORE_TARGETS": ",".join(app.get("build", {}).get("targets", [])),
        }

    def _run_configured_steps(self, job, stage, workspace, log, redactor):
        build = job["snapshot"]["app"].get("build") or {}
        steps = [step for step in build.get("steps", []) if step.get("stage") == stage]
        runtime_config = self._runtime_config(job)
        isolated = self._isolated_enabled(job)
        runtime = self._get_isolated_runtime() if isolated and steps else None
        image = str(runtime_config.get("buildImage") or "python:3.13")
        network_mode = str(runtime_config.get("networkMode") or "bridge")
        memory_mib = int(runtime_config.get("memoryMiB") or 4096)
        cpus = float(runtime_config.get("cpus") or 2)
        pids_limit = int(runtime_config.get("pidsLimit") or 512)

        for index, step in enumerate(steps, 1):
            name = step.get("name") or f"{stage}-{index}"
            timeout = int(step.get("timeoutSeconds") or DEFAULT_TIMEOUT_SECONDS)
            cwd = workspace
            working_directory = ""
            if step.get("workingDirectory"):
                working_directory = validate_relative_path(step["workingDirectory"], "workingDirectory").as_posix()
                cwd = workspace / Path(working_directory)
                if not cwd.is_dir():
                    raise NativeExecutionError(f"Working directory does not exist: {step['workingDirectory']}")
            env = {str(k): str(v) for k, v in (step.get("env") or {}).items()}
            for key, ref in (step.get("secrets") or {}).items():
                value = secret_from_ref(ref)
                env[str(key)] = value
                redactor.add(value)
            log.write(f"[{stage}] step {index}/{len(steps)}: {name}")
            if isolated:
                isolated_env = self._base_isolated_env(job)
                isolated_env.update(env)
                log.write(f"[isolated] image={image} network={network_mode} memory={memory_mib}MiB cpus={cpus:g} pids={pids_limit}")
                try:
                    runtime.run_step(
                        job_id=job["id"], app_id=job["appId"], stage=stage, step_index=index,
                        command=step["run"], workspace=workspace, working_directory=working_directory,
                        env=isolated_env, timeout=timeout,
                        cancel_check=lambda: self.adapter.cancellation_requested(job["id"]),
                        log_write=log.write, image=image, network_mode=network_mode,
                        memory_mib=memory_mib, cpus=cpus, pids_limit=pids_limit,
                    )
                except TimeoutError as exc:
                    raise CommandTimeout(str(exc)) from exc
                except InterruptedError as exc:
                    raise CommandCancelled(str(exc)) from exc
                except Exception as exc:
                    raise NativeExecutionError(str(exc)) from exc
            else:
                self._run_process(
                    ["/bin/sh", "-lc", step["run"]], cwd, log, redactor, timeout, job,
                    extra_env=env, command_label=name,
                )
        return len(steps)

    def _base_child_env(self, job):
        keep = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR")
        env = {key: os.environ[key] for key in keep if key in os.environ}
        app = job.get("snapshot", {}).get("app", {})
        env.update({
            "CI": "true",
            "FORGECORE_JOB_ID": job["id"],
            "FORGECORE_APP_ID": job["appId"],
            "FORGECORE_TARGETS": ",".join(app.get("build", {}).get("targets", [])),
        })
        return env

    def _run_process(self, argv, cwd, log, redactor, timeout, job, extra_env=None, command_label=None):
        env = self._base_child_env(job)
        env.update(extra_env or {})
        display = command_label or " ".join(argv[:3])
        log.write(f"[exec] {display} (timeout {timeout}s)")
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            bufsize=0,
            start_new_session=True,
        )
        selector = selectors.DefaultSelector()
        assert proc.stdout is not None
        selector.register(proc.stdout, selectors.EVENT_READ)
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        deadline = time.monotonic() + timeout

        def emit(data, final=False):
            text = decoder.decode(data, final=final)
            if text:
                for line in text.splitlines():
                    log.write(line)

        try:
            while True:
                if self.adapter.cancellation_requested(job["id"]):
                    self._terminate_process(proc)
                    raise CommandCancelled("Job cancellation requested")
                if time.monotonic() >= deadline:
                    self._terminate_process(proc)
                    raise CommandTimeout(f"Command timed out after {timeout} seconds")
                events = selector.select(timeout=0.25)
                for key, _ in events:
                    data = os.read(key.fileobj.fileno(), MAX_LOG_LINE)
                    if data:
                        emit(data)
                code = proc.poll()
                if code is not None:
                    remainder = proc.stdout.read()
                    if remainder:
                        emit(remainder)
                    emit(b"", final=True)
                    if code != 0:
                        raise NativeExecutionError(f"Command exited with status {code}: {display}")
                    return
        finally:
            selector.close()
            if proc.poll() is None:
                self._terminate_process(proc)

    @staticmethod
    def _terminate_process(proc):
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    @staticmethod
    def _capture_process(argv, cwd, timeout, extra_env=None):
        env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL") if key in os.environ}
        env.update(extra_env or {})
        result = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            raise NativeExecutionError(result.stderr.strip() or f"Command exited with status {result.returncode}")
        return result.stdout

    @staticmethod
    def _reject_package_symlinks(source):
        source = Path(source)
        if source.is_symlink():
            raise NativeExecutionError(f"Package source path must not be a symlink: {source}")
        if source.is_dir():
            for path in source.rglob("*"):
                if path.is_symlink():
                    relative = path.relative_to(source).as_posix()
                    raise NativeExecutionError(
                        f"Package source contains a symlink and cannot be handed off safely: {relative}"
                    )

    def _handoff_package(self, job, workspace, log):
        app = job["snapshot"]["app"]
        rel = validate_relative_path(app["package"]["sourcePath"], "package.sourcePath")
        source = workspace / rel
        if not source.exists():
            raise NativeExecutionError(f"Package source path does not exist: {app['package']['sourcePath']}")
        self._reject_package_symlinks(source)
        destination_root = ARTIFACT_ROOT / job["appId"] / job["id"]
        if destination_root.exists():
            shutil.rmtree(destination_root)
        package_root = destination_root / "package"
        ensure_private_dir(destination_root)
        if source.is_dir():
            shutil.copytree(source, package_root)
        else:
            package_root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, package_root / source.name)
        try:
            source_revision = self._capture_process(["git", "rev-parse", "HEAD"], workspace, 30).strip().lower()
        except (NativeExecutionError, subprocess.TimeoutExpired):
            source_revision = None
        entries = []
        total = 0
        for path in sorted(p for p in package_root.rglob("*") if p.is_file()):
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            size = path.stat().st_size
            total += size
            entries.append({
                "path": path.relative_to(package_root).as_posix(),
                "sha256": digest.hexdigest(),
                "size": size,
            })
        manifest = {
            "schemaVersion": 1,
            "kind": "ForgeCoreArtifactManifest",
            "jobId": job["id"],
            "appId": job["appId"],
            "format": app["package"]["format"],
            "sourcePath": app["package"]["sourcePath"],
            **({"sourceRevision": source_revision} if source_revision else {}),
            "fileCount": len(entries),
            "totalBytes": total,
            "files": entries,
        }
        write_private_json(destination_root / "manifest.json", manifest)
        log.write(f"[package] artifact handoff: {destination_root}")
        return manifest

    def _prepare_release_bundle(self, job, workspace, log):
        artifact_root = ARTIFACT_ROOT / job["appId"] / job["id"]
        release_root = artifact_root / "release"
        if release_root.exists():
            shutil.rmtree(release_root)
        source_revision = self._capture_process(["git", "rev-parse", "HEAD"], workspace, 30).strip()
        packager = load_release_packager()
        bundle = packager.build_release_bundle(job, artifact_root, release_root, source_revision)
        log.write(f"[package] deterministic release bundle: {release_root}")
        return bundle

    def _prepare_publish_only_release_bundle(self, job, log):
        source = job.get("artifactSource") or {}
        source_job_id = str(source.get("jobId") or "")
        source_root = ARTIFACT_ROOT / job["appId"] / source_job_id
        manifest_path = source_root / "manifest.json"
        package_root = source_root / "package"
        if not manifest_path.is_file() or not package_root.is_dir():
            raise NativeExecutionError("Publish artifact source is no longer available")

        digest = hashlib.sha256()
        with manifest_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        actual_manifest_sha = "sha256:" + digest.hexdigest()
        if actual_manifest_sha != source.get("manifestSha256"):
            raise NativeExecutionError("Publish artifact source manifest changed after the job was queued")

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise NativeExecutionError(f"Publish artifact source manifest is invalid: {exc}") from exc
        if manifest.get("jobId") != source_job_id or manifest.get("appId") != job["appId"]:
            raise NativeExecutionError("Publish artifact source identity mismatch")
        if str(manifest.get("sourceRevision") or "").lower() != source.get("sourceRevision"):
            raise NativeExecutionError("Publish artifact source revision mismatch")

        destination_root = ARTIFACT_ROOT / job["appId"] / job["id"]
        release_root = destination_root / "release"
        ensure_private_dir(destination_root)
        if release_root.exists():
            shutil.rmtree(release_root)
        packager = load_release_packager()
        bundle = packager.build_release_bundle(
            job,
            source_root,
            release_root,
            source["sourceRevision"],
        )
        log.write(
            f"[release] prepared from artifact source {source_job_id} "
            f"@ {source['sourceRevision']}"
        )
        return bundle

    def _publish_release(self, job, log):
        artifact_root = ARTIFACT_ROOT / job["appId"] / job["id"]
        publisher = load_release_publisher()
        try:
            published = publisher.publish_release(
                job,
                artifact_root,
                cancel_check=lambda: self.adapter.cancellation_requested(job["id"]),
            )
        except publisher.ReleasePublishCancelled as exc:
            raise CommandCancelled(str(exc)) from exc
        log.write(
            f"[release] verified {len(published['verifiedAssets'])} asset(s) "
            f"for {published['repository']}:{published['releaseTag']}"
        )
        return published

    def _publish_store(self, job, log):
        job_artifact_root = ARTIFACT_ROOT / job["appId"] / job["id"]
        package_artifact_root = job_artifact_root
        if job.get("jobType") == "publish":
            source_job_id = str((job.get("artifactSource") or {}).get("jobId") or "")
            if not source_job_id:
                raise NativeExecutionError("Publish-only Store job is missing artifactSource.jobId")
            package_artifact_root = ARTIFACT_ROOT / job["appId"] / source_job_id

        publisher = load_store_publisher()
        try:
            published = publisher.publish_store(
                job,
                package_artifact_root,
                job_artifact_root,
                cancel_check=lambda: self.adapter.cancellation_requested(job["id"]),
            )
        except publisher.StorePublishCancelled as exc:
            raise CommandCancelled(str(exc)) from exc
        log.write(
            f"[store] {published.get('status')} {published['repository']}:"
            f"{published['directory']}"
            + (f" {published.get('pullRequestUrl')}" if published.get("pullRequestUrl") else "")
        )
        return published

    @staticmethod
    def _ambient_secret_values():
        values = []
        for key, value in os.environ.items():
            upper = key.upper()
            if any(marker in upper for marker in ("TOKEN", "SECRET", "PASSWORD")) and value:
                values.append(value)
        return values

    @staticmethod
    def _safe_error(exc, redactor):
        message = redactor.text(str(exc)).strip() or exc.__class__.__name__
        return message[:500]


def main():
    parser = argparse.ArgumentParser(description="ForgeCore native execution worker")
    parser.add_argument("--once", action="store_true", help="claim at most one queued native job")
    args = parser.parse_args()
    engine = NativeExecutionEngine()
    if args.once:
        return 0 if engine.run_once() else 3
    while True:
        worked = engine.run_once()
        if not worked:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
