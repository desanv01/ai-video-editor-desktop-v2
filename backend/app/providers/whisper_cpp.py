"""Local whisper.cpp transcription provider.

The adapter is intentionally download-free: it can describe and validate a
configured whisper.cpp runtime, but it only runs when both the binary and model
file already exist on disk.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import stat
import subprocess
import threading
import signal
from pathlib import Path
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from providers.interfaces import (
    ProviderCapability,
    ProviderHealth,
    ProviderHealthStatus,
    ProviderKind,
    ProviderMetadata,
    TranscriptionProvider,
    TranscriptionRequest,
    TranscriptionResponse,
)


@dataclass(frozen=True)
class WhisperCppModelOption:
    model_id: str
    tier: str
    label: str
    expected_filename: str
    download_url: str
    description: str
    size_label: str
    size_mb: int
    speed: str
    quality: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class WhisperCppModelCatalogEntry:
    model_id: str
    tier: str
    label: str
    expected_filename: str
    download_url: str
    description: str
    size_label: str
    size_mb: int
    speed: str
    quality: str
    active: bool
    downloaded: bool
    file_path: Optional[str] = None


@dataclass(frozen=True)
class WhisperCppModelSelection:
    model_id: str
    tier: str
    model_path: str
    binary_path: str


@dataclass(frozen=True)
class WhisperCppRuntimeStatus:
    configured: bool
    binary_path: str
    model_path: str
    issues: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class WhisperCppRunResult:
    stdout: str
    stderr: str


WhisperCppRunner = Callable[[list[str], str], Awaitable[WhisperCppRunResult]]

WHISPER_CPP_PROVIDER_ID = "whisper-cpp"
WHISPER_CPP_MODEL_REPO_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"

WHISPER_CPP_MODEL_OPTIONS: tuple[WhisperCppModelOption, ...] = (
    WhisperCppModelOption(
        model_id="small",
        tier="fast",
        label="Whisper small",
        expected_filename="ggml-small.bin",
        download_url=f"{WHISPER_CPP_MODEL_REPO_URL}/ggml-small.bin",
        description="Fast local transcription for rough lecture drafts and quick review cycles.",
        size_label="466 MB",
        size_mb=466,
        speed="fast",
        quality="good",
        aliases=("small.en",),
    ),
    WhisperCppModelOption(
        model_id="medium",
        tier="balanced",
        label="Whisper medium",
        expected_filename="ggml-medium.bin",
        download_url=f"{WHISPER_CPP_MODEL_REPO_URL}/ggml-medium.bin",
        description="Balanced local model for day-to-day lecture transcription.",
        size_label="1.5 GB",
        size_mb=1500,
        speed="balanced",
        quality="better",
        aliases=("medium.en",),
    ),
    WhisperCppModelOption(
        model_id="large-v3",
        tier="accurate",
        label="Whisper large-v3",
        expected_filename="ggml-large-v3.bin",
        download_url=f"{WHISPER_CPP_MODEL_REPO_URL}/ggml-large-v3.bin",
        description="Highest-quality local option for final transcripts when runtime speed is less important.",
        size_label="3.1 GB",
        size_mb=3100,
        speed="slow",
        quality="best",
    ),
)


def normalize_whisper_cpp_model_id(model_id: str) -> str:
    normalized = (model_id or "").strip().lower()
    for option in WHISPER_CPP_MODEL_OPTIONS:
        aliases = {alias.lower() for alias in option.aliases}
        if normalized == option.model_id or normalized in aliases:
            return option.model_id
    return "small"


def get_whisper_cpp_model_option(model_id: str) -> WhisperCppModelOption:
    normalized = normalize_whisper_cpp_model_id(model_id)
    return next(
        (candidate for candidate in WHISPER_CPP_MODEL_OPTIONS if candidate.model_id == normalized),
        WHISPER_CPP_MODEL_OPTIONS[0],
    )


def _managed_whisper_files(component_root: str, binary_path: str, model_path: str) -> tuple[str, str, list[str]]:
    """Require the activated joint component, never PATH or manual model search."""
    values = tuple(str(value or "").strip() for value in (component_root, binary_path, model_path))
    issue = "Prepare or repair the activated Whisper small component; its confined runtime and model are required"
    if not all(values):
        return "", "", [issue]
    paths = tuple(Path(value) for value in values)
    if not all(path.is_absolute() for path in paths):
        return "", "", [issue + " (paths must be absolute)"]
    root, binary, model = tuple(Path(os.path.abspath(path)) for path in paths)
    try:
        for target in (root, binary, model):
            target.relative_to(root)
            for part in reversed((target, *target.parents)):
                info = part.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    return "", "", [issue + " (symlink or reparse path rejected)"]
        actual_root = root.resolve(strict=True)
        if not actual_root.is_dir():
            return "", "", [issue + " (component root is not a directory)"]
        actual_files = []
        for target, expected in ((binary, "bin/whisper-cli.exe"), (model, "models/ggml-small.bin")):
            actual = target.resolve(strict=True)
            if actual.relative_to(actual_root).as_posix().lower() != expected or not stat.S_ISREG(actual.stat().st_mode):
                return "", "", [issue + " (unexpected or nonregular component file)"]
            actual_files.append(str(actual))
        return actual_files[0], actual_files[1], []
    except (OSError, ValueError):
        return "", "", [issue + " (missing file or path outside the activated root)"]


def resolve_whisper_cpp_model_selection(settings) -> WhisperCppModelSelection:
    if getattr(settings, "is_native_desktop", False):
        from desktop_native.model_manager import native_selection
        try:
            selected = native_selection(settings)
            option = get_whisper_cpp_model_option(selected["model_id"])
            return WhisperCppModelSelection(model_id=option.model_id, tier=option.tier,
                model_path=selected["file_path"], binary_path=selected["runtime_binary"])
        except (RuntimeError, OSError, ValueError):
            return WhisperCppModelSelection(model_id="small", tier=WHISPER_CPP_MODEL_OPTIONS[0].tier,
                                            model_path="", binary_path="")
    model_id = (
        getattr(settings, "WHISPER_CPP_MODEL_ID", "")
        or getattr(settings, "LOCAL_TRANSCRIPTION_MODEL_ID", "")
        or "small"
    )
    option = get_whisper_cpp_model_option(model_id)
    model_path = (
        getattr(settings, "WHISPER_CPP_MODEL_PATH", "")
        or getattr(settings, "LOCAL_TRANSCRIPTION_MODEL_PATH", "")
        or ""
    )
    path_option = _option_for_model_path(model_path)
    if path_option and option.model_id == "small" and path_option.model_id != "small":
        option = path_option
    if not model_path:
        model_path = _first_existing_model_path(settings, option)
    binary_path = getattr(settings, "WHISPER_CPP_BINARY_PATH", "") or "whisper-cli"
    return WhisperCppModelSelection(
        model_id=option.model_id,
        tier=option.tier,
        model_path=model_path,
        binary_path=binary_path,
    )


def resolve_whisper_cpp_runtime_status(settings) -> WhisperCppRuntimeStatus:
    selection = resolve_whisper_cpp_model_selection(settings)
    if getattr(settings, "is_native_desktop", False):
        binary_path, model_path, issues = _managed_whisper_files(
            getattr(settings, "WHISPER_CPP_COMPONENT_ROOT", ""),
            getattr(settings, "WHISPER_CPP_BINARY_PATH", ""),
            getattr(settings, "WHISPER_CPP_MODEL_PATH", ""),
        )
        if not issues:
            from desktop_native.model_manager import native_selection
            try:
                selected = native_selection(settings)
                binary_path, model_path = selected["runtime_binary"], selected["file_path"]
            except (RuntimeError, OSError, ValueError) as exc:
                issues.append(str(exc))
        return WhisperCppRuntimeStatus(
            configured=not issues, binary_path=binary_path, model_path=model_path,
            issues=tuple(issues), message="whisper.cpp runtime is ready." if not issues else "; ".join(issues),
        )
    binary_path = resolve_whisper_cpp_binary_path(selection.binary_path)
    issues: list[str] = []
    if not binary_path:
        issues.append(
            "WHISPER_CPP_BINARY_PATH must point to whisper-cli/main, or whisper-cli must be on PATH"
        )
    if not selection.model_path:
        issues.append("WHISPER_CPP_MODEL_PATH or LOCAL_TRANSCRIPTION_MODEL_PATH is not set")
    elif not os.path.isfile(selection.model_path):
        issues.append(f"Configured whisper.cpp model file does not exist: {selection.model_path}")

    return WhisperCppRuntimeStatus(
        configured=not issues,
        binary_path=binary_path,
        model_path=selection.model_path,
        issues=tuple(issues),
        message="whisper.cpp runtime is ready." if not issues else "; ".join(issues),
    )


def resolve_whisper_cpp_binary_path(binary_path: str) -> str:
    if binary_path and os.path.isfile(binary_path):
        return binary_path
    return shutil.which(binary_path or "whisper-cli") or ""


def build_whisper_cpp_model_catalog(settings) -> list[WhisperCppModelCatalogEntry]:
    if getattr(settings, "is_native_desktop", False):
        from desktop_native.model_manager import native_catalog_snapshot
        from desktop_native.model_catalog import lookup
        try:
            snapshot = native_catalog_snapshot(settings)
            states = {item["model_id"]: item for item in snapshot["models"]}
        except (RuntimeError, OSError, ValueError):
            states = {}
        return [WhisperCppModelCatalogEntry(
            model_id=option.model_id, tier=option.tier, label=option.label,
            expected_filename=option.expected_filename, download_url=lookup(option.model_id).url,
            description=option.description, size_label=option.size_label, size_mb=option.size_mb,
            speed=option.speed, quality=option.quality,
            active=states.get(option.model_id, {}).get("active", option.model_id == "small"),
            downloaded=states.get(option.model_id, {}).get("downloaded", False),
            file_path=states.get(option.model_id, {}).get("file_path"),
        ) for option in WHISPER_CPP_MODEL_OPTIONS]
    selection = resolve_whisper_cpp_model_selection(settings)
    configured_model_path = (
        getattr(settings, "WHISPER_CPP_MODEL_PATH", "")
        or getattr(settings, "LOCAL_TRANSCRIPTION_MODEL_PATH", "")
        or ""
    )
    search_dirs = _model_search_dirs(settings, configured_model_path)

    catalog: list[WhisperCppModelCatalogEntry] = []
    for option in WHISPER_CPP_MODEL_OPTIONS:
        active = option.model_id == selection.model_id
        candidate_paths = _candidate_model_paths(option, configured_model_path, search_dirs)
        if active and configured_model_path:
            candidate_paths.insert(0, os.path.abspath(configured_model_path))
        existing_path = next((path for path in candidate_paths if os.path.isfile(path)), None)
        file_path = existing_path or (configured_model_path if active and configured_model_path else None)
        catalog.append(
            WhisperCppModelCatalogEntry(
                model_id=option.model_id,
                tier=option.tier,
                label=option.label,
                expected_filename=option.expected_filename,
                download_url=option.download_url,
                description=option.description,
                size_label=option.size_label,
                size_mb=option.size_mb,
                speed=option.speed,
                quality=option.quality,
                active=active,
                downloaded=existing_path is not None,
                file_path=file_path,
            )
        )
    return catalog


def _option_for_model_path(model_path: str) -> Optional[WhisperCppModelOption]:
    if not model_path:
        return None
    filename = os.path.basename(model_path).lower()
    for option in WHISPER_CPP_MODEL_OPTIONS:
        if filename == option.expected_filename.lower():
            return option
    return None


def _first_existing_model_path(settings, option: WhisperCppModelOption) -> str:
    for path in _candidate_model_paths(option, "", _model_search_dirs(settings, "")):
        if os.path.isfile(path):
            return path
    return ""


def _model_search_dirs(settings, configured_model_path: str) -> list[str]:
    dirs = [
        getattr(settings, "WHISPER_CPP_MODELS_DIR", ""),
        getattr(settings, "LOCAL_TRANSCRIPTION_MODELS_DIR", ""),
        managed_whisper_cpp_models_dir(settings),
    ]
    if configured_model_path:
        dirs.append(os.path.dirname(configured_model_path))

    seen: set[str] = set()
    normalized_dirs: list[str] = []
    for path in dirs:
        if not path:
            continue
        normalized = os.path.abspath(path)
        if normalized not in seen:
            normalized_dirs.append(normalized)
            seen.add(normalized)
    return normalized_dirs


def managed_whisper_cpp_models_dir(settings) -> str:
    configured = (
        getattr(settings, "WHISPER_CPP_MODELS_DIR", "")
        or getattr(settings, "LOCAL_TRANSCRIPTION_MODELS_DIR", "")
    )
    if configured:
        return configured
    root = getattr(settings, "LOCAL_MODEL_STORAGE_PATH", "") or "/data/models"
    return os.path.join(root, "whisper-cpp")


def managed_whisper_cpp_model_path(settings, option: WhisperCppModelOption) -> str:
    return os.path.join(managed_whisper_cpp_models_dir(settings), option.expected_filename)


def _candidate_model_paths(
    option: WhisperCppModelOption,
    configured_model_path: str,
    search_dirs: list[str],
) -> list[str]:
    paths = []
    if configured_model_path:
        configured_name = os.path.basename(configured_model_path)
        if configured_name == option.expected_filename:
            paths.append(configured_model_path)
    paths.extend(os.path.join(directory, option.expected_filename) for directory in search_dirs)

    seen: set[str] = set()
    unique_paths: list[str] = []
    for path in paths:
        normalized = os.path.abspath(path)
        if normalized not in seen:
            unique_paths.append(normalized)
            seen.add(normalized)
    return unique_paths


class WhisperCppTranscriptionProvider(TranscriptionProvider):
    """Transcription provider backed by a local whisper.cpp CLI binary."""

    def __init__(
        self,
        *,
        binary_path: str = "whisper-cli",
        model_path: str = "",
        model_id: str = "small",
        work_dir: Optional[str] = None,
        runner: Optional[WhisperCppRunner] = None,
        validate_runtime: bool = True,
    ):
        # The existing registry passes explicit paths; capture only native
        # profile/root settings here so its public factory needs no expansion.
        from config import settings as runtime_settings
        self._native_desktop = bool(getattr(runtime_settings, "is_native_desktop", False))
        self._component_root = str(getattr(runtime_settings, "WHISPER_CPP_COMPONENT_ROOT", "") or "")
        self._binding_issues = list(resolve_whisper_cpp_runtime_status(runtime_settings).issues) if self._native_desktop else []
        self._binary_path = (binary_path or "") if self._native_desktop else (binary_path or "whisper-cli")
        self._model_path = model_path or ""
        self._model_id = model_id if self._native_desktop else normalize_whisper_cpp_model_id(model_id or "small")
        self._native_store = None
        if self._native_desktop and not self._binding_issues:
            from desktop_native.model_manager import get_native_model_store, native_selection, validate_captured_binding
            self._native_store = get_native_model_store(runtime_settings)
            selected = native_selection(runtime_settings)
            if model_id != selected["model_id"]:
                raise RuntimeError("Explicit native model ID must match the current verified store selection")
            validate_captured_binding(self._native_store, self._model_id, self._model_path, self._binary_path)
        self._work_dir = work_dir
        self._runner = runner or (self._run_native_command if self._native_desktop else self._run_command)
        self._validate_runtime = validate_runtime
        self._metadata = ProviderMetadata(
            provider_id=WHISPER_CPP_PROVIDER_ID,
            kind=ProviderKind.TRANSCRIPTION,
            label="whisper.cpp Local Transcription",
            provider_name="whisper.cpp",
            default_model=self._model_id,
            is_local=True,
            capabilities=(
                ProviderCapability("audio_transcription", "Local speech-to-text transcription."),
                ProviderCapability("segment_timestamps", "Segment timestamps from whisper.cpp JSON output."),
                ProviderCapability("offline_runtime", "Runs without API calls once model files exist."),
            ),
        )

    @property
    def metadata(self) -> ProviderMetadata:
        return self._metadata

    async def health(self) -> ProviderHealth:
        issues = self._runtime_issues()
        if issues:
            return ProviderHealth(
                status=ProviderHealthStatus.NOT_CONFIGURED,
                message="whisper.cpp is not ready for local transcription.",
                details={
                    "issues": issues,
                    "binary_path": self._binary_path,
                    "model_path": self._model_path,
                    "model_id": self._model_id,
                },
            )

        return ProviderHealth(
            status=ProviderHealthStatus.AVAILABLE,
            message="whisper.cpp binary and model file are configured.",
            details={
                "binary_path": self._resolved_binary_path(),
                "model_path": self._model_path,
                "model_id": self._model_id,
            },
        )

    async def transcribe(self, request: TranscriptionRequest) -> TranscriptionResponse:
        if not self._native_desktop:
            return await self._transcribe_legacy(request)
        issues = self._runtime_issues()
        if issues:
            raise RuntimeError("whisper.cpp local transcription is not configured: " + "; ".join(issues))
        from desktop_native.model_manager import native_model_lease
        with native_model_lease(self._native_store, self._model_id, self._model_path, self._binary_path):
            owner = asyncio.create_task(self._transcribe_native(request))
            cancelled = False
            while True:
                try:
                    result = await asyncio.shield(owner)
                    break
                except asyncio.CancelledError:
                    cancelled = True
                    if owner.done():
                        raise
                    owner.cancel()
                    # Keep the lease until the runner's owned cleanup finishes.
                    while not owner.done():
                        try:
                            await asyncio.shield(owner)
                        except asyncio.CancelledError:
                            continue
                    if not owner.cancelled():
                        owner.result()
                    raise
            if cancelled:
                raise asyncio.CancelledError()
            return result

    async def _transcribe_native(self, request):
        work_dir = self._work_dir or os.path.dirname(request.audio_path) or os.getcwd()
        os.makedirs(work_dir, exist_ok=True)
        output_base = os.path.join(work_dir, f"whisper_cpp_{uuid.uuid4().hex}")
        output_json_path = f"{output_base}.json"
        command = [self._resolved_binary_path(), "-m", self._model_path, "-f", request.audio_path,
                   "-oj", "-of", output_base]
        if request.language:
            command.extend(["-l", request.language])
        threads = request.metadata.get("threads")
        if isinstance(threads, int) and threads > 0:
            command.extend(["-t", str(threads)])
        try:
            result = await self._runner(command, output_json_path)
            raw_payload = self._load_json_payload(output_json_path, result.stdout)
            transcript = self._parse_payload(raw_payload, request.metadata.get("duration"))
            transcript["provider"] = self.metadata.provider_id
            return TranscriptionResponse(transcript=transcript, provider_id=self.metadata.provider_id,
                                         model=self._model_id, raw=raw_payload)
        finally:
            try:
                os.remove(output_json_path)
            except OSError:
                pass

    async def _run_native_command(self, command, output_json_path):
        cancel = threading.Event()
        owner = asyncio.create_task(asyncio.to_thread(self._run_native_sync, command, output_json_path, cancel))
        try:
            return await asyncio.shield(owner)
        except asyncio.CancelledError:
            cancel.set()
            while not owner.done():
                try:
                    await asyncio.shield(owner)
                except asyncio.CancelledError:
                    continue
            if not owner.cancelled():
                owner.result()
            raise

    def _run_native_sync(self, command, output_json_path, cancel):
        from desktop_native.model_store import _WindowsProcessJob
        options = {"creationflags": subprocess.CREATE_NO_WINDOW | 0x4} if os.name == "nt" else {"start_new_session": True}
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, shell=False, **options)
        job = None
        try:
            if os.name == "nt":
                job = _WindowsProcessJob(proc)
                job.resume(proc)
            while True:
                if cancel.is_set():
                    if job is not None:
                        job.close()
                    self._native_store._kill(proc)
                try:
                    stdout, stderr = proc.communicate(timeout=.25)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if cancel.is_set():
                return WhisperCppRunResult(stdout="", stderr="Cancelled")
            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")
            if proc.returncode != 0:
                raise RuntimeError(f"whisper.cpp failed with exit code {proc.returncode}: {stderr_text[:500]}")
            if not os.path.exists(output_json_path) and not stdout_text.strip():
                raise RuntimeError("whisper.cpp completed but did not produce JSON output")
            return WhisperCppRunResult(stdout=stdout_text, stderr=stderr_text)
        finally:
            try:
                if job is not None:
                    job.close()
                if proc.poll() is None:
                    self._native_store._kill(proc)
                elif os.name != "nt":
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            finally:
                proc.stdout.close()
                proc.stderr.close()

    async def _transcribe_legacy(self, request: TranscriptionRequest) -> TranscriptionResponse:
        issues = self._runtime_issues() if self._native_desktop or self._validate_runtime else []
        if issues:
            raise RuntimeError(
                "whisper.cpp local transcription is not configured: "
                + "; ".join(issues)
            )

        work_dir = self._work_dir or os.path.dirname(request.audio_path) or os.getcwd()
        os.makedirs(work_dir, exist_ok=True)
        output_base = os.path.join(work_dir, f"whisper_cpp_{uuid.uuid4().hex}")
        output_json_path = f"{output_base}.json"

        command = [
            self._resolved_binary_path(),
            "-m",
            self._model_path,
            "-f",
            request.audio_path,
            "-oj",
            "-of",
            output_base,
        ]
        if request.language:
            command.extend(["-l", request.language])

        threads = request.metadata.get("threads")
        if isinstance(threads, int) and threads > 0:
            command.extend(["-t", str(threads)])

        result = await self._runner(command, output_json_path)
        raw_payload = self._load_json_payload(output_json_path, result.stdout)
        transcript = self._parse_payload(raw_payload, request.metadata.get("duration"))
        transcript["provider"] = self.metadata.provider_id

        try:
            os.remove(output_json_path)
        except OSError:
            pass

        return TranscriptionResponse(
            transcript=transcript,
            provider_id=self.metadata.provider_id,
            model=self.metadata.default_model,
            raw=raw_payload,
        )

    def _runtime_issues(self) -> list[str]:
        if self._native_desktop:
            if self._binding_issues or self._native_store is None:
                return self._binding_issues or ["Native model binding is missing; prepare or repair Whisper"]
            from desktop_native.model_manager import validate_captured_binding
            try:
                validate_captured_binding(self._native_store, self._model_id, self._model_path, self._binary_path)
                return []
            except (RuntimeError, OSError, ValueError) as exc:
                return [str(exc)]
        issues: list[str] = []
        if not self._resolved_binary_path():
            issues.append(
                "WHISPER_CPP_BINARY_PATH must point to whisper-cli/main, or whisper-cli must be on PATH"
            )
        if not self._model_path:
            issues.append("WHISPER_CPP_MODEL_PATH or LOCAL_TRANSCRIPTION_MODEL_PATH is not set")
        elif not os.path.isfile(self._model_path):
            issues.append(f"Configured whisper.cpp model file does not exist: {self._model_path}")
        return issues

    def _resolved_binary_path(self) -> str:
        if self._native_desktop:
            issues = self._runtime_issues()
            if issues:
                raise RuntimeError("; ".join(issues))
            return self._binary_path
        return resolve_whisper_cpp_binary_path(self._binary_path)

    @staticmethod
    async def _run_command(command: list[str], output_json_path: str) -> WhisperCppRunResult:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(
                f"whisper.cpp failed with exit code {proc.returncode}: {stderr_text[:500]}"
            )
        if not os.path.exists(output_json_path) and not stdout_text.strip():
            raise RuntimeError("whisper.cpp completed but did not produce JSON output")
        return WhisperCppRunResult(stdout=stdout_text, stderr=stderr_text)

    @staticmethod
    def _load_json_payload(output_json_path: str, stdout: str) -> dict[str, Any]:
        if os.path.exists(output_json_path):
            with open(output_json_path, "r", encoding="utf-8") as handle:
                return json.load(handle)

        text = stdout.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if match:
                return json.loads(match.group(0))
            raise RuntimeError("Could not parse whisper.cpp JSON output") from exc

    def _parse_payload(self, payload: dict[str, Any], fallback_duration: Optional[float]) -> dict[str, Any]:
        raw_segments = payload.get("transcription") or payload.get("segments") or []
        segments = [self._parse_segment(segment) for segment in raw_segments]
        segments = [segment for segment in segments if segment["text"]]

        if not segments and payload.get("text"):
            duration = float(fallback_duration or 0.0)
            segments = [{
                "text": str(payload.get("text") or "").strip(),
                "start": 0.0,
                "end": duration,
                "speaker": None,
            }]

        text = " ".join(segment["text"] for segment in segments).strip()
        language = (
            (payload.get("result") or {}).get("language")
            or payload.get("language")
            or "unknown"
        )
        duration = max((segment["end"] for segment in segments), default=float(fallback_duration or 0.0))

        return {
            "text": text,
            "language": language,
            "duration": duration,
            "words": self._words_from_segments(segments),
            "segments": segments,
            "speakers": [],
        }

    @staticmethod
    def _parse_segment(segment: dict[str, Any]) -> dict[str, Any]:
        text = str(segment.get("text") or "").strip()
        offsets = segment.get("offsets") or {}
        timestamps = segment.get("timestamps") or {}
        start = _offset_to_seconds(offsets.get("from"))
        end = _offset_to_seconds(offsets.get("to"))

        if start is None:
            start = _timestamp_to_seconds(timestamps.get("from"))
        if end is None:
            end = _timestamp_to_seconds(timestamps.get("to"))

        return {
            "text": text,
            "start": float(start or 0.0),
            "end": float(end if end is not None else start or 0.0),
            "speaker": None,
        }

    @staticmethod
    def _words_from_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        words: list[dict[str, Any]] = []
        for segment in segments:
            tokens = segment["text"].split()
            if not tokens:
                continue
            start = float(segment.get("start", 0.0) or 0.0)
            end = float(segment.get("end", start) or start)
            duration = max(end - start, 0.0)
            step = duration / len(tokens) if duration > 0 else 0.0
            for index, token in enumerate(tokens):
                token_start = start + (step * index)
                words.append({
                    "word": token,
                    "start": token_start,
                    "end": token_start + step,
                    "speaker": None,
                })
        return words


def _offset_to_seconds(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number / 1000.0 if number > 100 else number


def _timestamp_to_seconds(value: Any) -> Optional[float]:
    if not value:
        return None
    text = str(value).strip().replace(",", ".")
    match = re.match(r"^(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)$", text)
    if not match:
        try:
            return float(text)
        except ValueError:
            return None
    hours = float(match.group(1) or 0)
    minutes = float(match.group(2) or 0)
    seconds = float(match.group(3) or 0)
    return (hours * 3600) + (minutes * 60) + seconds
