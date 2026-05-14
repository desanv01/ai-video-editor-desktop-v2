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
    description: str


@dataclass(frozen=True)
class WhisperCppModelSelection:
    model_id: str
    tier: str
    model_path: str
    binary_path: str


@dataclass(frozen=True)
class WhisperCppRunResult:
    stdout: str
    stderr: str


WhisperCppRunner = Callable[[list[str], str], Awaitable[WhisperCppRunResult]]

WHISPER_CPP_PROVIDER_ID = "whisper-cpp"

WHISPER_CPP_MODEL_OPTIONS: tuple[WhisperCppModelOption, ...] = (
    WhisperCppModelOption(
        model_id="base.en",
        tier="fast",
        label="Fast local Whisper",
        expected_filename="ggml-base.en.bin",
        description="Small English model for quick local drafts.",
    ),
    WhisperCppModelOption(
        model_id="small.en",
        tier="balanced",
        label="Balanced local Whisper",
        expected_filename="ggml-small.en.bin",
        description="Balanced speed and quality for lecture drafts.",
    ),
    WhisperCppModelOption(
        model_id="large-v3",
        tier="accurate",
        label="Accurate local Whisper",
        expected_filename="ggml-large-v3.bin",
        description="Highest-quality local option once a model is downloaded.",
    ),
)


def resolve_whisper_cpp_model_selection(settings) -> WhisperCppModelSelection:
    model_id = (
        getattr(settings, "WHISPER_CPP_MODEL_ID", "")
        or getattr(settings, "LOCAL_TRANSCRIPTION_MODEL_ID", "")
        or "small.en"
    )
    option = next(
        (candidate for candidate in WHISPER_CPP_MODEL_OPTIONS if candidate.model_id == model_id),
        WHISPER_CPP_MODEL_OPTIONS[1],
    )
    model_path = (
        getattr(settings, "WHISPER_CPP_MODEL_PATH", "")
        or getattr(settings, "LOCAL_TRANSCRIPTION_MODEL_PATH", "")
        or ""
    )
    binary_path = getattr(settings, "WHISPER_CPP_BINARY_PATH", "") or "whisper-cli"
    return WhisperCppModelSelection(
        model_id=option.model_id,
        tier=option.tier,
        model_path=model_path,
        binary_path=binary_path,
    )


class WhisperCppTranscriptionProvider(TranscriptionProvider):
    """Transcription provider backed by a local whisper.cpp CLI binary."""

    def __init__(
        self,
        *,
        binary_path: str = "whisper-cli",
        model_path: str = "",
        model_id: str = "small.en",
        work_dir: Optional[str] = None,
        runner: Optional[WhisperCppRunner] = None,
        validate_runtime: bool = True,
    ):
        self._binary_path = binary_path or "whisper-cli"
        self._model_path = model_path or ""
        self._model_id = model_id or "small.en"
        self._work_dir = work_dir
        self._runner = runner or self._run_command
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
        issues = self._runtime_issues() if self._validate_runtime else []
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
        if os.path.isfile(self._binary_path):
            return self._binary_path
        return shutil.which(self._binary_path) or ""

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
