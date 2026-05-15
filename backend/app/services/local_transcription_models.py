"""Managed local transcription model downloads and removal."""

from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib import request as url_request

from config import settings
from providers.whisper_cpp import (
    WhisperCppModelOption,
    build_whisper_cpp_model_catalog,
    get_whisper_cpp_model_option,
    managed_whisper_cpp_model_path,
    managed_whisper_cpp_models_dir,
)


DOWNLOAD_CHUNK_BYTES = 1024 * 1024


@dataclass
class LocalModelDownloadJob:
    job_id: str
    provider_id: str
    model_id: str
    status: str
    file_path: str
    download_url: str
    total_bytes: Optional[int] = None
    bytes_downloaded: int = 0
    progress_percent: float = 0.0
    message: str = "Queued"
    error: Optional[str] = None
    activate_on_complete: bool = True
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class LocalModelRemovalResult:
    provider_id: str
    model_id: str
    removed: bool
    file_path: Optional[str]
    message: str


class LocalTranscriptionModelService:
    """Download and remove whisper.cpp model files for the desktop settings UI."""

    provider_id = "whisper-cpp"

    def __init__(self):
        self._jobs: dict[str, LocalModelDownloadJob] = {}
        self._lock = threading.RLock()

    def get_job(self, model_id: str) -> Optional[LocalModelDownloadJob]:
        normalized = get_whisper_cpp_model_option(model_id).model_id
        with self._lock:
            return self._jobs.get(normalized)

    def start_download(
        self,
        model_id: str,
        *,
        activate_on_complete: bool = True,
    ) -> LocalModelDownloadJob:
        option = get_whisper_cpp_model_option(model_id)
        file_path = managed_whisper_cpp_model_path(settings, option)

        with self._lock:
            existing = self._jobs.get(option.model_id)
            if existing and existing.status in {"queued", "downloading"}:
                return existing

            if os.path.isfile(file_path):
                job = self._completed_job(option, file_path, activate_on_complete)
                self._jobs[option.model_id] = job
                if activate_on_complete:
                    self._activate_model(option, file_path)
                return job

            job = LocalModelDownloadJob(
                job_id=str(uuid.uuid4()),
                provider_id=self.provider_id,
                model_id=option.model_id,
                status="queued",
                file_path=file_path,
                download_url=option.download_url,
                activate_on_complete=activate_on_complete,
            )
            self._jobs[option.model_id] = job

        asyncio.create_task(asyncio.to_thread(self._download_model, option, job))
        return job

    def remove_model(self, model_id: str) -> LocalModelRemovalResult:
        option = get_whisper_cpp_model_option(model_id)
        catalog_entry = next(
            entry for entry in build_whisper_cpp_model_catalog(settings)
            if entry.model_id == option.model_id
        )
        file_path = catalog_entry.file_path or managed_whisper_cpp_model_path(settings, option)

        with self._lock:
            running_job = self._jobs.get(option.model_id)
            if running_job and running_job.status in {"queued", "downloading"}:
                raise RuntimeError(f"{option.label} is currently downloading")

        if not os.path.isfile(file_path):
            return LocalModelRemovalResult(
                provider_id=self.provider_id,
                model_id=option.model_id,
                removed=False,
                file_path=file_path,
                message=f"{option.label} is not downloaded.",
            )

        if not self._is_safe_managed_model_path(file_path, option):
            raise RuntimeError(
                "Refusing to remove a model outside the managed whisper.cpp model directories"
            )

        os.remove(file_path)

        with self._lock:
            self._jobs.pop(option.model_id, None)

        active_id = (
            getattr(settings, "WHISPER_CPP_MODEL_ID", "")
            or getattr(settings, "LOCAL_TRANSCRIPTION_MODEL_ID", "")
            or ""
        )
        if active_id and get_whisper_cpp_model_option(active_id).model_id == option.model_id:
            settings.WHISPER_CPP_MODEL_PATH = ""
            settings.LOCAL_TRANSCRIPTION_MODEL_PATH = ""

        return LocalModelRemovalResult(
            provider_id=self.provider_id,
            model_id=option.model_id,
            removed=True,
            file_path=file_path,
            message=f"{option.label} was removed.",
        )

    def _download_model(self, option: WhisperCppModelOption, job: LocalModelDownloadJob) -> None:
        temp_path = f"{job.file_path}.part"
        try:
            os.makedirs(os.path.dirname(job.file_path), exist_ok=True)
            self._update_job(job, status="downloading", message=f"Downloading {option.label}...")

            req = url_request.Request(
                option.download_url,
                headers={"User-Agent": "ai-video-editor-local-model-manager/1.0"},
            )
            with url_request.urlopen(req, timeout=30) as response:
                total_bytes = _parse_content_length(response.headers.get("Content-Length"))
                self._update_job(job, total_bytes=total_bytes)

                with open(temp_path, "wb") as handle:
                    while True:
                        chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        handle.write(chunk)
                        self._update_progress(job, len(chunk))

            if os.path.getsize(temp_path) <= 0:
                raise RuntimeError("Downloaded model file was empty")

            os.replace(temp_path, job.file_path)
            if job.activate_on_complete:
                self._activate_model(option, job.file_path)

            self._update_job(
                job,
                status="completed",
                progress_percent=100.0,
                message=f"{option.label} is ready for local transcription.",
                error=None,
            )
        except Exception as exc:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            self._update_job(
                job,
                status="failed",
                message=f"Could not download {option.label}.",
                error=str(exc),
            )

    def _update_progress(self, job: LocalModelDownloadJob, increment_bytes: int) -> None:
        with self._lock:
            job.bytes_downloaded += increment_bytes
            if job.total_bytes:
                job.progress_percent = min(
                    99.0,
                    round((job.bytes_downloaded / job.total_bytes) * 100, 2),
                )
            job.updated_at = time.time()

    def _update_job(self, job: LocalModelDownloadJob, **updates) -> None:
        with self._lock:
            for key, value in updates.items():
                setattr(job, key, value)
            job.updated_at = time.time()

    def _completed_job(
        self,
        option: WhisperCppModelOption,
        file_path: str,
        activate_on_complete: bool,
    ) -> LocalModelDownloadJob:
        file_size = os.path.getsize(file_path)
        return LocalModelDownloadJob(
            job_id=str(uuid.uuid4()),
            provider_id=self.provider_id,
            model_id=option.model_id,
            status="completed",
            file_path=file_path,
            download_url=option.download_url,
            total_bytes=file_size,
            bytes_downloaded=file_size,
            progress_percent=100.0,
            message=f"{option.label} is already downloaded.",
            activate_on_complete=activate_on_complete,
        )

    def _activate_model(self, option: WhisperCppModelOption, file_path: str) -> None:
        settings.WHISPER_CPP_MODEL_ID = option.model_id
        settings.LOCAL_TRANSCRIPTION_MODEL_ID = option.model_id
        settings.WHISPER_CPP_MODEL_PATH = file_path
        settings.LOCAL_TRANSCRIPTION_MODEL_PATH = file_path

    def _is_safe_managed_model_path(self, file_path: str, option: WhisperCppModelOption) -> bool:
        if os.path.basename(file_path) != option.expected_filename:
            return False

        candidate = Path(file_path).resolve()
        allowed_dirs = {
            Path(managed_whisper_cpp_models_dir(settings)).resolve(),
        }
        for configured_dir in (
            getattr(settings, "WHISPER_CPP_MODELS_DIR", ""),
            getattr(settings, "LOCAL_TRANSCRIPTION_MODELS_DIR", ""),
        ):
            if configured_dir:
                allowed_dirs.add(Path(configured_dir).resolve())

        for directory in allowed_dirs:
            try:
                candidate.relative_to(directory)
                return True
            except ValueError:
                continue
        return False


def _parse_content_length(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


local_transcription_model_service = LocalTranscriptionModelService()
