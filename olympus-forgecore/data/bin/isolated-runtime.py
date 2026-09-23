#!/usr/bin/env python3
"""ForgeCore v2 isolated build runtime.

Runs native build/test/verify steps as ephemeral containers on a dedicated Docker
Engine. The engine is separate from the ForgeCore v1 GitHub Actions Docker daemon.
Only the current job workspace is bind-mounted into a build container.
"""

import codecs
import json
import os
import queue
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

DEFAULT_HOST = os.environ.get("FORGECORE_BUILD_DOCKER_HOST", "http://build-docker:2375")
DEFAULT_API_TIMEOUT = max(1, int(os.environ.get("FORGECORE_BUILD_DOCKER_API_TIMEOUT_SECONDS", "30")))
LOG_CHUNK = 64 * 1024


class IsolatedRuntimeError(RuntimeError):
    pass


class IsolatedRuntimeTimeout(TimeoutError):
    pass


class IsolatedRuntimeCancelled(InterruptedError):
    pass


def validate_relative_directory(value):
    value = str(value or "").strip()
    if not value:
        return ""
    if value.startswith("/") or "\\" in value:
        raise IsolatedRuntimeError("workingDirectory must be a relative POSIX path")
    parts = [part for part in value.split("/") if part]
    if any(part in (".", "..") for part in parts):
        raise IsolatedRuntimeError("workingDirectory contains an invalid path segment")
    return "/".join(parts)


class DockerBuildRuntime:
    def __init__(self, host=None, storage_root=None):
        raw_host = str(host or DEFAULT_HOST).strip().rstrip("/")
        parsed = urlparse(raw_host)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise IsolatedRuntimeError("FORGECORE_BUILD_DOCKER_HOST must be an http(s) Docker Engine endpoint")
        self.host = raw_host
        root = Path(storage_root or os.environ.get("FORGECORE_STORAGE_ROOT", "/forgecore/storage"))
        self.storage_root = root.resolve()
        self.workspace_root = (self.storage_root / "workspaces").resolve()

    def ensure_ready(self):
        try:
            request = Request(self.host + "/_ping", method="GET")
            with urlopen(request, timeout=DEFAULT_API_TIMEOUT) as response:
                body = response.read(64).decode("utf-8", "replace").strip()
                if response.status != 200 or body != "OK":
                    raise IsolatedRuntimeError("isolated Docker engine did not answer OK")
        except (HTTPError, URLError, OSError) as exc:
            raise IsolatedRuntimeError(f"isolated Docker engine is unavailable: {exc}") from exc

    def _workspace_path(self, workspace):
        path = Path(workspace).resolve()
        try:
            path.relative_to(self.workspace_root)
        except ValueError as exc:
            raise IsolatedRuntimeError("build workspace is outside ForgeCore workspace storage") from exc
        if not path.is_dir():
            raise IsolatedRuntimeError("build workspace does not exist")
        return path

    def container_config(
        self,
        *,
        job_id,
        app_id,
        stage,
        step_index,
        command,
        workspace,
        working_directory,
        env,
        image,
        network_mode,
        memory_mib,
        cpus,
        pids_limit,
    ):
        workspace = self._workspace_path(workspace)
        relative = validate_relative_directory(working_directory)
        if network_mode not in {"bridge", "none"}:
            raise IsolatedRuntimeError("isolated runtime networkMode must be bridge or none")
        if not str(image or "").strip():
            raise IsolatedRuntimeError("isolated runtime build image is empty")
        container_workdir = "/workspace" + (f"/{relative}" if relative else "")
        labels = {
            "com.forgecore.role": "isolated-build",
            "com.forgecore.job": str(job_id),
            "com.forgecore.app": str(app_id),
            "com.forgecore.stage": str(stage),
            "com.forgecore.step": str(step_index),
        }
        return {
            "Image": str(image),
            "Cmd": ["/bin/sh", "-lc", str(command)],
            "WorkingDir": container_workdir,
            "Env": [f"{key}={value}" for key, value in sorted((env or {}).items())],
            "Labels": labels,
            "AttachStdout": True,
            "AttachStderr": True,
            "Tty": False,
            "HostConfig": {
                "Binds": [f"{workspace}:/workspace:rw"],
                "NetworkMode": network_mode,
                "SecurityOpt": ["no-new-privileges:true"],
                "Memory": int(memory_mib) * 1024 * 1024,
                "NanoCpus": int(float(cpus) * 1_000_000_000),
                "PidsLimit": int(pids_limit),
            },
        }

    def run_step(
        self,
        *,
        job_id,
        app_id,
        stage,
        step_index,
        command,
        workspace,
        working_directory="",
        env=None,
        timeout=1800,
        cancel_check=None,
        log_write=None,
        image="python:3.13",
        network_mode="bridge",
        memory_mib=4096,
        cpus=2,
        pids_limit=512,
    ):
        self.ensure_ready()
        spec = self.container_config(
            job_id=job_id,
            app_id=app_id,
            stage=stage,
            step_index=step_index,
            command=command,
            workspace=workspace,
            working_directory=working_directory,
            env=env or {},
            image=image,
            network_mode=network_mode,
            memory_mib=memory_mib,
            cpus=cpus,
            pids_limit=pids_limit,
        )
        self._ensure_image(image)
        create = self._request_json("POST", "/containers/create", spec, expected={201})
        container_id = str(create.get("Id") or "")
        if not container_id:
            raise IsolatedRuntimeError("Docker Engine did not return a container id")

        messages = queue.Queue()
        stream_done = threading.Event()
        emitted = {"value": False}

        def emit(value):
            emitted["value"] = True
            if log_write:
                for line in str(value).splitlines():
                    log_write(line)

        def follow():
            try:
                self._follow_logs(container_id, messages)
            except Exception as exc:
                messages.put(("error", str(exc)))
            finally:
                stream_done.set()

        try:
            self._request("POST", f"/containers/{container_id}/start", expected={204})
            thread = threading.Thread(target=follow, name=f"forgecore-log-{container_id[:12]}", daemon=True)
            thread.start()
            deadline = time.monotonic() + max(1, int(timeout))
            stream_error = None
            while True:
                self._drain_messages(messages, emit)
                if cancel_check and cancel_check():
                    self._terminate_container(container_id)
                    raise IsolatedRuntimeCancelled("Job cancellation requested")
                if time.monotonic() >= deadline:
                    self._terminate_container(container_id)
                    raise IsolatedRuntimeTimeout(f"Command timed out after {int(timeout)} seconds")
                state = self._inspect_state(container_id)
                if not state.get("Running", False):
                    exit_code = state.get("ExitCode")
                    break
                time.sleep(0.2)

            end = time.monotonic() + 2
            while (not stream_done.is_set() or not messages.empty()) and time.monotonic() < end:
                try:
                    kind, value = messages.get(timeout=0.1)
                except queue.Empty:
                    continue
                if kind == "log":
                    emit(value)
                elif kind == "error":
                    stream_error = value

            if not emitted["value"]:
                try:
                    final_logs = self._request(
                        "GET",
                        f"/containers/{container_id}/logs?stdout=1&stderr=1",
                        expected={200},
                    )
                    for line in self._decode_multiplexed(final_logs).splitlines():
                        emit(line)
                except IsolatedRuntimeError:
                    pass

            if exit_code not in (0, None):
                raise IsolatedRuntimeError(f"isolated command exited with status {exit_code}")
            if stream_error and log_write:
                log_write(f"[isolated] log stream warning: {stream_error}")
        finally:
            self._remove_container(container_id)

    def cleanup_job(self, job_id):
        filters = json.dumps({"label": [f"com.forgecore.job={job_id}", "com.forgecore.role=isolated-build"]})
        path = "/containers/json?" + urlencode({"all": "1", "filters": filters})
        try:
            containers = self._request_json("GET", path, expected={200})
        except IsolatedRuntimeError:
            return
        for item in containers if isinstance(containers, list) else []:
            container_id = str(item.get("Id") or "")
            if container_id:
                self._remove_container(container_id)

    def _ensure_image(self, image):
        escaped = quote(str(image), safe="")
        try:
            self._request_json("GET", f"/images/{escaped}/json", expected={200})
            return
        except IsolatedRuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise
        path = "/images/create?" + urlencode({"fromImage": str(image)})
        self._request("POST", path, expected={200}, timeout=900)

    def _inspect_state(self, container_id):
        payload = self._request_json("GET", f"/containers/{container_id}/json", expected={200})
        return payload.get("State") or {}

    def _terminate_container(self, container_id):
        try:
            self._request("POST", f"/containers/{container_id}/kill?signal=TERM", expected={204, 409})
        except IsolatedRuntimeError:
            pass
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                if not self._inspect_state(container_id).get("Running", False):
                    return
            except IsolatedRuntimeError:
                return
            time.sleep(0.1)
        try:
            self._request("POST", f"/containers/{container_id}/kill?signal=KILL", expected={204, 409})
        except IsolatedRuntimeError:
            pass

    def _remove_container(self, container_id):
        try:
            self._request("DELETE", f"/containers/{container_id}?force=1&v=1", expected={204, 404})
        except IsolatedRuntimeError:
            pass

    def _follow_logs(self, container_id, messages):
        path = f"/containers/{container_id}/logs?follow=1&stdout=1&stderr=1"
        request = Request(self.host + path, method="GET")
        try:
            with urlopen(request, timeout=max(DEFAULT_API_TIMEOUT, 3600)) as response:
                buffer = b""
                decoder = codecs.getincrementaldecoder("utf-8")("replace")
                while True:
                    chunk = response.read(LOG_CHUNK)
                    if not chunk:
                        break
                    buffer += chunk
                    while len(buffer) >= 8:
                        size = int.from_bytes(buffer[4:8], "big")
                        if len(buffer) < 8 + size:
                            break
                        payload = buffer[8:8 + size]
                        buffer = buffer[8 + size:]
                        text = decoder.decode(payload)
                        if text:
                            for line in text.splitlines():
                                messages.put(("log", line))
                tail = decoder.decode(b"", final=True)
                if tail:
                    for line in tail.splitlines():
                        messages.put(("log", line))
        except (HTTPError, URLError, OSError) as exc:
            raise IsolatedRuntimeError(f"Docker log stream failed: {exc}") from exc

    @staticmethod
    def _drain_messages(messages, emit):
        while True:
            try:
                kind, value = messages.get_nowait()
            except queue.Empty:
                return
            if kind == "log":
                emit(value)

    @staticmethod
    def _decode_multiplexed(data):
        data = bytes(data or b"")
        out = bytearray()
        while len(data) >= 8:
            size = int.from_bytes(data[4:8], "big")
            if len(data) < 8 + size:
                break
            out.extend(data[8:8 + size])
            data = data[8 + size:]
        return out.decode("utf-8", "replace")

    def _request_json(self, method, path, payload=None, expected={200}):
        raw = self._request(method, path, payload=payload, expected=expected)
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise IsolatedRuntimeError("Docker Engine returned invalid JSON") from exc

    def _request(self, method, path, payload=None, expected={200}, timeout=None):
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self.host + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout or DEFAULT_API_TIMEOUT) as response:
                data = response.read()
                if response.status not in expected:
                    raise IsolatedRuntimeError(f"Docker Engine HTTP {response.status}")
                return data
        except HTTPError as exc:
            detail = ""
            try:
                parsed = json.loads(exc.read().decode("utf-8", "replace"))
                detail = str(parsed.get("message") or "")
            except Exception:
                detail = ""
            suffix = f": {detail[:300]}" if detail else ""
            raise IsolatedRuntimeError(f"Docker Engine HTTP {exc.code}{suffix}") from exc
        except (URLError, OSError) as exc:
            raise IsolatedRuntimeError(f"Docker Engine request failed: {exc}") from exc
