"""Owned, durable native Whisper downloads and joint runtime qualification.

Construction performs no network access or model hashing/probing. Call
verify_selection after restart before using a persisted optional selection.
Blocking activation/verification belongs on the caller's background thread.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import threading
import time
import urllib.request
import uuid

from .model_catalog import catalog as pinned_catalog, lookup
from .paths import reject_program_files

PACK_SHA256 = "bff80723000e5e058230f8ae27751a4e2ed4378d5dc1c0f849222cb5d022213f"
PACK_VERSION = "1.9.4-b5130-small"
EXPECTATION = "and so my fellow americans"
RUNNING = {"queued", "downloading", "verifying", "probing"}
STATUSES = RUNNING | {"paused", "interrupted", "completed", "failed"}
CHUNK = 1024 * 1024

class ModelStoreError(RuntimeError):
    pass

class _Paused(Exception):
    pass

class _HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise ModelStoreError("Model download redirected outside HTTPS")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _normal(value):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ModelStoreError("Native model paths must be absolute and normal")
    if str(path).startswith(("\\\\", "//")):
        raise ModelStoreError("Network model paths are not supported")
    return path


def _safe(path):
    """Inspect every existing ancestor without following links/junctions."""
    for item in reversed((path, *path.parents)):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ModelStoreError(f"Linked/reparse model path rejected: {item}")
        if item != path and not stat.S_ISDIR(info.st_mode):
            raise ModelStoreError(f"Non-directory model ancestor: {item}")
    if path.exists() and not (path.is_file() or path.is_dir()):
        raise ModelStoreError(f"Non-regular model path: {path}")
    return path


def _hash(path, cancel=None):
    _safe(path)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            if cancel is not None and cancel.is_set():
                raise _Paused()
            block = source.read(CHUNK)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()



class _WindowsProcessJob:
    """Kernel-owned child-tree lifetime; closing the job kills all descendants."""
    def __init__(self, proc):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel = kernel
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ModelStoreError("Cannot create owned runtime process job")
        # JOBOBJECT_EXTENDED_LIMIT_INFORMATION: native ABI sizes and DWORD
        # LimitFlags at byte 16 in JOBOBJECT_BASIC_LIMIT_INFORMATION.
        info = ctypes.create_string_buffer(144 if ctypes.sizeof(ctypes.c_void_p) == 8 else 112)
        ctypes.c_uint32.from_buffer(info, 16).value = 0x2000  # KILL_ON_JOB_CLOSE
        if (not kernel.SetInformationJobObject(self.handle, 9, info, len(info)) or
                not kernel.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(proc._handle)))):
            self.close()
            raise ModelStoreError("Cannot bind runtime probe to owned child-tree job")

    def resume(self, proc):
        import ctypes
        from ctypes import wintypes
        native = ctypes.WinDLL("ntdll", use_last_error=True)
        native.NtResumeProcess.argtypes = [wintypes.HANDLE]
        native.NtResumeProcess.restype = ctypes.c_long
        if native.NtResumeProcess(wintypes.HANDLE(int(proc._handle))) != 0:
            raise ModelStoreError("Cannot resume owned runtime probe")

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

class NativeModelStore:
    def __init__(self, data_root, component_root, runtime_binary, bundled_model, probe_audio):
        self.data_root = _normal(data_root)
        reject_program_files(self.data_root, label="Native model data root")
        if self.data_root == self.data_root.anchor or self.data_root == Path(self.data_root.anchor):
            raise ModelStoreError("Filesystem root cannot own model data")
        self.component_root = _normal(component_root)
        self.runtime_binary = _normal(runtime_binary)
        self.bundled_model = _normal(bundled_model)
        self.probe_audio = _normal(probe_audio)
        if self.data_root == self.component_root or self.component_root in self.data_root.parents:
            raise ModelStoreError("Model data root cannot be inside the read-only runtime bundle")
        self.root = self.data_root / "Models" / "Whisper"
        self.state = self.root / "state"
        self._lock = threading.RLock()
        self._threads = set()
        self._events = {}
        self._jobs = {}
        self._qualified = {}
        self._leases = {}
        self._busy = None
        self._download_model = None
        self._closed = False
        self._desired = "small"
        self._binding()
        self._mkdir(self.state)
        selection = self.state / "selection.json"
        if selection.exists():
            data = self._read(selection)
            spec = lookup(data.get("model_id"))
            if data != self._choice(spec.model_id):
                raise ModelStoreError("Invalid native model selection journal")
            self._desired = spec.model_id
        for spec in pinned_catalog():
            if spec.model_id == "small":
                continue
            journal = self._journal(spec.model_id)
            if journal.exists():
                job = self._read(journal)
                self._validate_job(job, spec)
                if job["status"] in RUNNING:
                    job.update(status="interrupted", message="Interrupted by application exit; resume explicitly", error=None)
                    if job.get("operation") == "qualification":
                        file = self._owned(self._paths(spec)[0])
                        actual_bytes = file.stat().st_size if file.exists() else 0
                        job["actual_file_bytes"] = actual_bytes
                        job["bytes_downloaded"] = min(actual_bytes, spec.size_bytes)
                    else:
                        job["bytes_downloaded"] = self._partial_size(spec)
                    self._progress(job)
                    self._write(journal, job)
                self._jobs[spec.model_id] = job

    def _binding(self):
        expected = (self.component_root / "bin" / "whisper-cli.exe",
                    self.component_root / "models" / "ggml-small.bin",
                    self.component_root / "probes" / "jfk.wav")
        for actual, wanted in zip((self.runtime_binary, self.bundled_model, self.probe_audio), expected):
            if actual != wanted or not _safe(actual).is_file():
                raise ModelStoreError("Model store requires exact activated Whisper component paths")
        marker = self.component_root / ".verified.json"
        _safe(marker)
        with marker.open("r", encoding="utf-8-sig") as source:
            data = json.load(source)
        if data.get("sha256") != PACK_SHA256 or data.get("version") != PACK_VERSION:
            raise ModelStoreError("Activated Whisper bundle marker does not match accepted pack")
        _safe(self.data_root)

    def _owned(self, path):
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ModelStoreError("Path is outside owned model store") from exc
        _safe(self.data_root)
        return _safe(path)

    def _mkdir(self, path):
        self._owned(path)
        path.mkdir(parents=True, exist_ok=True)
        self._owned(path)

    def _read(self, path):
        self._owned(path)
        if path.stat().st_size > 128 * 1024:
            raise ModelStoreError("Oversized model metadata")
        with path.open("r", encoding="utf-8-sig") as source:
            value = json.load(source)
        if not isinstance(value, dict):
            raise ModelStoreError("Invalid model metadata object")
        return value

    def _write(self, path, value):
        self._mkdir(path.parent)
        self._owned(path)
        temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
        try:
            self._owned(temp)
            with temp.open("x", encoding="utf-8") as target:
                json.dump(value, target, sort_keys=True, allow_nan=False)
                target.flush()
                os.fsync(target.fileno())
            self._owned(path)
            self._owned(temp)
            os.replace(temp, path)
            if os.name != "nt":
                fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        finally:
            if temp.exists():
                self._owned(temp).unlink()

    def _paths(self, spec):
        file = self.root / spec.model_id / spec.sha256 / spec.filename
        return file, file.with_name(file.name + ".part"), file.with_name(file.name + ".attestation.json")

    def _journal(self, model_id):
        return self.state / (model_id + ".json")

    def _partial_size(self, spec):
        part = self._owned(self._paths(spec)[1])
        size = part.stat().st_size if part.exists() else 0
        if size > spec.size_bytes:
            raise ModelStoreError("Owned partial exceeds pinned model size; retained for diagnosis")
        return size

    def _choice(self, model_id):
        return {"schema": 1, "model_id": model_id, "sha256": lookup(model_id).sha256}

    def _validate_job(self, job, spec):
        if (job.get("schema") != 1 or job.get("model_id") != spec.model_id or
                job.get("sha256") != spec.sha256 or job.get("download_url") != spec.url or
                job.get("file_path") != str(self._paths(spec)[0]) or
                job.get("total_bytes") != spec.size_bytes or job.get("status") not in STATUSES):
            raise ModelStoreError("Model journal does not match pinned schema/ownership")
        try:
            uuid.UUID(job["id"])
            count = job["bytes_downloaded"]
            if type(count) is not int or not 0 <= count <= spec.size_bytes:
                raise ValueError()
            for key in ("created_at", "updated_at"):
                if not isinstance(job[key], (int, float)) or not 0 <= job[key] < 1e12:
                    raise ValueError()
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelStoreError("Invalid durable model job fields") from exc

    def _progress(self, job):
        job["progress"] = job["bytes_downloaded"] / job["total_bytes"]
        job["updated_at"] = time.time()
        job["active"] = self._desired == job["model_id"] and job["model_id"] in self._qualified

    def _update(self, model_id, **changes):
        with self._lock:
            job = self._jobs[model_id]
            job.update(changes)
            self._progress(job)
            self._write(self._journal(model_id), job)

    def get_job(self, model_id):
        lookup(model_id)
        with self._lock:
            job = self._jobs.get(model_id)
            if job is None:
                return None
            snapshot = dict(job)
            snapshot["active"] = self._desired == model_id and model_id in self._qualified
            return snapshot

    def catalog(self):
        with self._lock:
            result = []
            for spec in pinned_catalog():
                item = asdict(spec)
                item.update(bundled=spec.model_id == "small", removable=spec.model_id != "small",
                            ready=spec.model_id == "small" or self._valid_cached(spec.model_id),
                            job=self.get_job(spec.model_id))
                result.append(item)
            return result

    def _fingerprint(self, path):
        _safe(path)
        info = path.stat()
        return {"size": info.st_size, "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}

    def _valid_cached(self, model_id):
        att = self._qualified.get(model_id)
        if att is None:
            return False
        try:
            self._binding()
            file = self._owned(self._paths(lookup(model_id))[0])
            valid = (att["file_stat"] == self._fingerprint(file) and
                     att["runtime_stat"] == self._fingerprint(self.runtime_binary) and
                     att["audio_stat"] == self._fingerprint(self.probe_audio))
        except (OSError, ModelStoreError):
            valid = False
        if not valid:
            self._qualified.pop(model_id, None)
        return valid

    def selection(self):
        with self._lock:
            self._binding()
            selected = self._desired
            ready = selected == "small" or self._valid_cached(selected)
            actual = selected if ready else "small"
            path = self.bundled_model if actual == "small" else self._paths(lookup(actual))[0]
            return {"model_id": actual, "file_path": str(path), "runtime_binary": str(self.runtime_binary),
                    "ready": True, "requested_model_id": selected,
                    "optional_state": "qualified" if ready else "verification_required",
                    "fallback": not ready}

    @contextmanager
    def usage_lease(self, model_id=None):
        with self._lock:
            current = self.selection()
            requested = current["model_id"] if model_id is None else lookup(model_id).model_id
            if requested != "small" and not self._valid_cached(requested):
                raise ModelStoreError("Optional model requires verification before use")
            if self._busy == requested:
                raise ModelStoreError("Model is currently transferring or probing")
            self._leases[requested] = self._leases.get(requested, 0) + 1
            binding = dict(current, model_id=requested, file_path=str(self.bundled_model if requested == "small" else self._paths(lookup(requested))[0]))
        try:
            yield binding
        finally:
            with self._lock:
                self._leases[requested] -= 1

    def _reserve(self, model_id):
        if self._closed:
            raise ModelStoreError("Native model store is shut down")
        if self._busy is not None:
            raise ModelStoreError(f"Model {self._busy} is transferring/probing; pause it first")
        if self._leases.get(model_id, 0):
            raise ModelStoreError("Model is in use; release its usage lease first")
        self._busy = model_id
        event = threading.Event()
        self._events[model_id] = event
        return event

    def start_download(self, model_id, make_active=False):
        spec = lookup(model_id)
        if model_id == "small":
            raise ModelStoreError("Small is the protected bundled model")
        with self._lock:
            if self._busy == model_id:
                job = self._jobs.get(model_id)
                if self._download_model == model_id and job is not None and job["status"] in RUNNING:
                    return self.get_job(model_id)
                raise ModelStoreError("Model activation/verification is in progress; wait for it to finish before downloading")
            cancel = self._reserve(model_id)
            try:
                self._partial_size(spec)
                now = time.time()
                prior = self._jobs.get(model_id)
                job = {"schema": 1, "id": prior["id"] if prior else str(uuid.uuid4()),
                       "model_id": model_id, "sha256": spec.sha256, "status": "queued",
                       "download_url": spec.url, "file_path": str(self._paths(spec)[0]),
                       "bytes_downloaded": self._partial_size(spec), "total_bytes": spec.size_bytes,
                       "progress": 0, "message": "Queued", "error": None, "active": False,
                       "created_at": prior["created_at"] if prior else now, "updated_at": now}
                self._jobs[model_id] = job
                self._update(model_id)
                worker = threading.Thread(target=self._worker, args=(spec, cancel, bool(make_active)),
                                          name=f"native-model-{model_id}", daemon=False)
                self._threads.add(worker)
                snapshot = self.get_job(model_id)
                try:
                    worker.start()
                except BaseException:
                    self._threads.discard(worker)
                    raise
                self._download_model = model_id
                return snapshot
            except BaseException:
                self._busy = None
                self._events.pop(model_id, None)
                raise

    def cancel(self, model_id):
        lookup(model_id)
        with self._lock:
            event = self._events.get(model_id)
            if event is not None:
                event.set()
            return self.get_job(model_id)

    def _check(self, cancel):
        if cancel.is_set():
            raise _Paused()

    def _transfer(self, spec, cancel):
        file, part, _ = self._paths(spec)
        self._mkdir(part.parent)
        offset = self._partial_size(spec)
        self._check(cancel)
        margin = max(64 * CHUNK, spec.size_bytes // 20)
        if shutil.disk_usage(part.parent).free < spec.size_bytes - offset + margin:
            raise ModelStoreError("Insufficient disk space for remaining model bytes plus safety margin")
        self._update(spec.model_id, status="downloading", message="Downloading verified pinned model")
        if offset == spec.size_bytes:
            return
        headers = {"Accept-Encoding": "identity", "User-Agent": "Aivora-Native-Model-Store/1"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        opener = urllib.request.build_opener(_HTTPSRedirect())
        with opener.open(urllib.request.Request(spec.url, headers=headers), timeout=30) as response:
            if not response.geturl().startswith("https://"):
                raise ModelStoreError("Model response URL must use HTTPS")
            status = response.status
            if response.headers.get("Content-Encoding", "identity") != "identity":
                raise ModelStoreError("Encoded model response rejected")
            if status == 206:
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                if not match or tuple(map(int, match.groups())) != (offset, spec.size_bytes - 1, spec.size_bytes):
                    raise ModelStoreError("Model server returned incompatible Content-Range")
            elif status == 200:
                if response.headers.get("Content-Range"):
                    raise ModelStoreError("Unexpected Content-Range on full model response")
                if offset and shutil.disk_usage(part.parent).free < spec.size_bytes + margin:
                    raise ModelStoreError("Insufficient disk space for full HTTP 200 restart; resumed partial retained")
                offset = 0
            else:
                raise ModelStoreError(f"Unexpected model HTTP status {status}")
            length = response.headers.get("Content-Length")
            if length is None or not length.isdigit() or int(length) != spec.size_bytes - offset:
                raise ModelStoreError("Model response length does not match pinned remaining size")
            self._check(cancel)
            self._owned(part)
            with part.open("ab" if offset else "wb") as output:
                count = offset
                last_time, last_count = time.monotonic(), count
                self._update(spec.model_id, bytes_downloaded=count)
                while True:
                    self._check(cancel)
                    block = response.read(min(CHUNK, spec.size_bytes - count + 1))
                    if not block:
                        break
                    if count + len(block) > spec.size_bytes:
                        raise ModelStoreError("Model response exceeds pinned size")
                    output.write(block)
                    count += len(block)
                    if time.monotonic() - last_time >= 1 or count - last_count >= CHUNK:
                        output.flush()
                        os.fsync(output.fileno())
                        self._update(spec.model_id, bytes_downloaded=count)
                        last_time, last_count = time.monotonic(), count
                output.flush()
                os.fsync(output.fileno())
            self._check(cancel)
            if count != spec.size_bytes:
                raise ModelStoreError("Model transfer truncated; partial retained for resume")
            self._update(spec.model_id, bytes_downloaded=count)

    def _kill(self, proc):
        if proc.poll() is None:
            if os.name == "nt":
                try:
                    killer = subprocess.Popen([str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"),
                                               "/PID", str(proc.pid), "/T", "/F"],
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                              creationflags=subprocess.CREATE_NO_WINDOW)
                    try:
                        killer.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        killer.kill()
                        killer.wait(timeout=5)
                except OSError:
                    pass
                if proc.poll() is None:
                    proc.kill()
            else:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        proc.wait(timeout=10)

    def _probe(self, candidate, cancel):
        self._binding()
        self._check(cancel)
        options = {"creationflags": subprocess.CREATE_NO_WINDOW | 0x4} if os.name == "nt" else {"start_new_session": True}
        proc = subprocess.Popen([str(self.runtime_binary), "-ng", "-t", "4", "-l", "en", "-m", str(candidate),
                                 "-f", str(self.probe_audio), "-nt", "-np"], shell=False,
                                cwd=self.component_root, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
        process_job = None
        retained = [bytearray(), bytearray()]
        failures = []
        started = []
        pipes = (proc.stdout, proc.stderr)

        def drain(pipe, index):
            try:
                while True:
                    block = pipe.read(16384)
                    if not block:
                        break
                    retained[index].extend(block)
                    del retained[index][:-65536]
            except BaseException as exc:
                failures.append(exc)
            finally:
                try:
                    pipe.close()
                except BaseException as exc:
                    failures.append(exc)

        deadline = time.monotonic() + 300
        try:
            if os.name == "nt":
                process_job = _WindowsProcessJob(proc)
            for index, pipe in enumerate(pipes):
                reader = threading.Thread(target=drain, args=(pipe, index), daemon=False)
                # Hold the lock across launch/tracking so shutdown cannot capture
                # an unstarted thread or miss a reader that has actually started.
                with self._lock:
                    try:
                        reader.start()
                    except BaseException:
                        if reader.ident is not None:
                            started.append((reader, pipe))
                            self._threads.add(reader)
                        raise
                    started.append((reader, pipe))
                    self._threads.add(reader)
            if process_job is not None:
                process_job.resume(proc)
            while proc.poll() is None:
                self._check(cancel)
                if time.monotonic() >= deadline:
                    raise ModelStoreError("Native model runtime probe timed out after 300 seconds")
                cancel.wait(.1)
            self._check(cancel)
        finally:
            cleanup_errors = []
            if process_job is not None:
                try:
                    process_job.close()
                except BaseException as exc:
                    cleanup_errors.append(exc)
            # Termination precedes closing pipes not claimed by a started reader.
            try:
                if proc.poll() is None:
                    self._kill(proc)
                elif os.name != "nt":
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            except BaseException as exc:
                cleanup_errors.append(exc)
            claimed = {pipe for _, pipe in started}
            for pipe in pipes:
                if pipe not in claimed:
                    try:
                        pipe.close()
                    except BaseException as exc:
                        cleanup_errors.append(exc)
            for reader, _ in started:
                try:
                    reader.join(timeout=10)
                except BaseException as exc:
                    cleanup_errors.append(exc)
                if not reader.is_alive():
                    with self._lock:
                        self._threads.discard(reader)
            if any(reader.is_alive() for reader, _ in started):
                cleanup_errors.append(ModelStoreError("Owned probe reader is still running"))
            if cleanup_errors:
                raise ModelStoreError("Runtime probe process/pipe cleanup incomplete; model remains unqualified") from cleanup_errors[0]
        if failures:
            raise ModelStoreError("Runtime probe output drain failed") from failures[0]
        output = re.sub(r"[^a-z0-9]+", " ", retained[0].decode("utf-8", errors="replace").lower()).strip()
        if proc.returncode != 0 or EXPECTATION not in output:
            raise ModelStoreError("Runtime/model probe failed the public JFK transcription expectation")

    def _qualify(self, spec, candidate, cancel, job=False):
        self._binding()
        self._owned(candidate)
        if job:
            self._update(spec.model_id, status="verifying", message="Verifying full model SHA256")
        before = self._fingerprint(candidate)
        if before["size"] != spec.size_bytes or _hash(candidate, cancel) != spec.sha256:
            raise ModelStoreError("Model size/SHA256 verification failed; file retained")
        self._check(cancel)
        runtime_stat = self._fingerprint(self.runtime_binary)
        audio_stat = self._fingerprint(self.probe_audio)
        runtime_sha = _hash(self.runtime_binary, cancel)
        audio_sha = _hash(self.probe_audio, cancel)
        file, _, att_path = self._paths(spec)
        prior = self._read(att_path) if att_path.exists() else None
        valid_prior = (candidate == file and prior is not None and prior.get("schema") == 1 and
                       prior.get("model") == asdict(spec) and prior.get("runtime_sha256") == runtime_sha and
                       prior.get("audio_sha256") == audio_sha and prior.get("probe_expectation") == EXPECTATION and
                       prior.get("probe_success") is True and prior.get("file_stat") == before)
        if not valid_prior:
            if job:
                self._update(spec.model_id, status="probing", message="Probing activated runtime with model")
            self._probe(candidate, cancel)
        self._check(cancel)
        self._binding()
        if (before != self._fingerprint(candidate) or runtime_stat != self._fingerprint(self.runtime_binary) or
                audio_stat != self._fingerprint(self.probe_audio)):
            raise ModelStoreError("Model/runtime/audio changed during qualification")
        if candidate != file:
            with self._lock:
                self._check(cancel)
                if self._leases.get(spec.model_id, 0):
                    raise ModelStoreError("Cannot replace a leased model")
                self._owned(candidate)
                self._owned(file)
                os.replace(candidate, file)
        att = {"schema": 1, "model": asdict(spec), "runtime_sha256": runtime_sha,
               "audio_sha256": audio_sha, "probe_expectation": EXPECTATION, "probe_success": True,
               "file_stat": self._fingerprint(file), "runtime_stat": runtime_stat,
               "audio_stat": audio_stat, "qualified_at": time.time()}
        with self._lock:
            self._check(cancel)
            self._write(att_path, att)
            self._qualified[spec.model_id] = att
        return att

    def _activate_locked(self, model_id, cancel):
        self._check(cancel)
        self._write(self.state / "selection.json", self._choice(model_id))
        self._desired = model_id

    def _worker(self, spec, cancel, make_active):
        try:
            file, part, _ = self._paths(spec)
            self._owned(file)
            if not file.exists():
                self._transfer(spec, cancel)
            self._qualify(spec, file if file.exists() else part, cancel, job=True)
            with self._lock:
                self._check(cancel)
                if make_active:
                    self._activate_locked(spec.model_id, cancel)
                self._update(spec.model_id, status="completed", bytes_downloaded=spec.size_bytes,
                             message="Model verified and runtime probe passed", error=None)
        except _Paused:
            count = spec.size_bytes if self._paths(spec)[0].exists() else self._partial_size(spec)
            self._update(spec.model_id, status="paused", bytes_downloaded=count,
                         message="Paused; resume explicitly to finish verification", error=None)
        except Exception as exc:
            count = spec.size_bytes if self._paths(spec)[0].exists() else min(spec.size_bytes, self._paths(spec)[1].stat().st_size if self._paths(spec)[1].exists() else 0)
            self._update(spec.model_id, status="failed", bytes_downloaded=count, message="Model acquisition/qualification failed",
                         error=str(exc))
        finally:
            with self._lock:
                self._busy = None
                self._events.pop(spec.model_id, None)
                self._download_model = None

    def activate(self, model_id):
        spec = lookup(model_id)
        with self._lock:
            cancel = self._reserve(model_id)
        job_created = False
        try:
            self._binding()
            if model_id != "small":
                file = self._owned(self._paths(spec)[0])
                actual_bytes = file.stat().st_size if file.exists() else 0
                with self._lock:
                    prior = self._jobs.get(model_id)
                    now = time.time()
                    self._jobs[model_id] = {
                        "schema": 1, "id": prior["id"] if prior else str(uuid.uuid4()),
                        "model_id": model_id, "sha256": spec.sha256, "operation": "qualification",
                        "status": "queued", "download_url": spec.url, "file_path": str(file),
                        "bytes_downloaded": min(actual_bytes, spec.size_bytes),
                        "actual_file_bytes": actual_bytes, "total_bytes": spec.size_bytes,
                        "progress": 0, "message": "Queued for local model qualification; no download",
                        "error": None, "active": False,
                        "created_at": prior["created_at"] if prior else now, "updated_at": now,
                    }
                    job_created = True
                    self._update(model_id)
                # Byte progress describes retained bytes, not hash/probe readiness.
                # _download_model remains None for this synchronous owner.
                self._qualify(spec, file, cancel, job=True)
            with self._lock:
                self._activate_locked(model_id, cancel)
                if job_created:
                    self._update(model_id, status="completed", bytes_downloaded=spec.size_bytes,
                                 actual_file_bytes=spec.size_bytes,
                                 message="Local model verified, runtime probe passed, and model activated", error=None)
                return self.selection()
        except _Paused:
            if job_created:
                self._update(model_id, status="paused",
                             message="Local qualification paused; retained file can be verified later", error=None)
            raise
        except Exception as exc:
            if job_created:
                self._update(model_id, status="failed", message="Local model qualification failed; retained file preserved",
                             error=str(exc))
            raise
        finally:
            with self._lock:
                self._busy = None
                self._events.pop(model_id, None)

    def verify_selection(self):
        with self._lock:
            desired = self._desired
        return self.activate(desired)

    def remove(self, model_id):
        spec = lookup(model_id)
        if model_id == "small":
            raise ModelStoreError("Bundled small model cannot be removed")
        with self._lock:
            if self._busy == model_id or self._leases.get(model_id, 0):
                raise ModelStoreError("Model is transferring/probing or in use; pause/release it first")
            paths = self._paths(spec)
            for path in paths:
                self._owned(path)
                if path.exists() and not path.is_file():
                    raise ModelStoreError("Model removal target is not a regular owned file")
            if self._desired == model_id:
                self._binding()
                self._write(self.state / "selection.json", self._choice("small"))
                self._desired = "small"
            self._qualified.pop(model_id, None)
            for path in paths:
                if path.exists():
                    self._owned(path).unlink()
            if model_id in self._jobs:
                self._update(model_id, status="interrupted", bytes_downloaded=0,
                             message="Optional model removed", error=None)
            return self.selection()

    def shutdown(self):
        with self._lock:
            self._closed = True
            for event in self._events.values():
                event.set()
            threads = tuple(self._threads)
        for worker in threads:
            if worker is not threading.current_thread():
                worker.join()
        # Synchronous activations are caller-owned threads; wait until their owned
        # hash/probe lifetime has actually completed as well.
        while True:
            with self._lock:
                if self._busy is None:
                    return
            time.sleep(.05)
