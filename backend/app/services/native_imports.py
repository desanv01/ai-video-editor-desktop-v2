"""
Helpers for large native desktop imports staged under app-controlled storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import uuid
from typing import Any

from services.upload_limits import max_upload_size_bytes


FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
IMPORT_SCHEMA_VERSION = "desktop.native-import-operation.v1"
TERMINAL_PHASES = {"completed", "cancelled", "quarantined"}


class NativeImportError(ValueError):
    """Stable API-facing failure for a durable native import operation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


@dataclass(slots=True)
class NativeImportSession:
    token: str
    project_id: str
    original_filename: str
    mime_type: str | None
    file_size_bytes: int
    staging_relative_path: str
    staging_part_relative_path: str
    manifest_relative_path: str
    created_at: str
    status: str
    updated_at: str | None = None
    bytes_received: int = 0
    last_error: str | None = None
    schema_version: str = IMPORT_SCHEMA_VERSION
    phase: str = "accepted"
    restartable: bool = False
    error: dict[str, Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "project_id": self.project_id,
            "original_filename": self.original_filename,
            "mime_type": self.mime_type,
            "file_size_bytes": self.file_size_bytes,
            "staging_relative_path": self.staging_relative_path,
            "staging_part_relative_path": self.staging_part_relative_path,
            "manifest_relative_path": self.manifest_relative_path,
            "created_at": self.created_at,
            "status": self.status,
            "updated_at": self.updated_at,
            "bytes_received": self.bytes_received,
            "last_error": self.last_error,
            "schema_version": self.schema_version,
            "phase": self.phase,
            "restartable": self.restartable,
            "error": self.error,
            "events": self.events,
        }

    def operation_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "operationId": self.token,
            "projectId": self.project_id,
            "phase": self.phase,
            "bytesReceived": self.bytes_received,
            "totalBytes": self.file_size_bytes,
            "restartable": self.restartable,
            "cancelable": self.phase not in TERMINAL_PHASES,
            "updatedAt": self.updated_at,
            "error": self.error,
            "events": self.events,
        }


def _storage_root(settings) -> Path:
    return Path(str(getattr(settings, "UPLOAD_PATH"))).resolve()


def _staging_root(settings) -> Path:
    fallback = _storage_root(settings) / "staging" / "native-imports"
    return Path(str(getattr(settings, "STAGING_UPLOAD_PATH", fallback))).resolve()


def _manifest_root(settings) -> Path:
    fallback = _staging_root(settings) / "manifests"
    return Path(str(getattr(settings, "IMPORT_MANIFEST_PATH", fallback))).resolve()


def _orphan_root(settings) -> Path:
    fallback = _storage_root(settings) / "orphaned-imports"
    return Path(str(getattr(settings, "ORPHAN_UPLOAD_PATH", fallback))).resolve()


def ensure_native_import_dirs(settings) -> None:
    for directory in (_storage_root(settings), _staging_root(settings), _manifest_root(settings), _orphan_root(settings)):
        directory.mkdir(parents=True, exist_ok=True)


def sanitize_filename(filename: str) -> str:
    cleaned = FILENAME_SAFE_RE.sub("_", filename.strip()).strip("._")
    return cleaned or "imported-video"


def _relative_to_storage(settings, path: Path) -> str:
    return path.resolve().relative_to(_storage_root(settings)).as_posix()


def _resolve_within_storage(settings, relative_path: str) -> Path:
    root = _storage_root(settings)
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path escapes storage root: {relative_path}") from exc
    return candidate


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)
    _sync_directory(path.parent)


def _sync_directory(path: Path) -> None:
    """Durably record a rename where directory fsync is supported."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        # Windows does not expose directory fsync through Python's os.open.
        return
    try:
        try:
            os.fsync(descriptor)
        except OSError:
            return
    finally:
        os.close(descriptor)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event(
    session: NativeImportSession,
    event_type: str,
    phase: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "sequence": len(session.events) + 1,
        "eventType": event_type,
        "phase": phase,
        "at": _now_iso(),
        "payload": payload or {},
    }


def _transition(
    settings,
    session: NativeImportSession,
    *,
    status: str,
    phase: str,
    event_type: str,
    bytes_received: int | None = None,
    restartable: bool = False,
    error: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> NativeImportSession:
    event = _event(session, event_type, phase, payload)
    updated = replace(
        session,
        status=status,
        phase=phase,
        updated_at=event["at"],
        bytes_received=(
            get_native_import_received_bytes(settings, session)
            if bytes_received is None
            else bytes_received
        ),
        restartable=restartable,
        error=error,
        last_error=error["message"] if error else None,
        events=[*session.events, event],
    )
    save_native_import_session(settings, updated)
    return updated


def _required_free_bytes(settings, file_size_bytes: int) -> int:
    multiplier = float(getattr(settings, "UPLOAD_REQUIRED_FREE_SPACE_MULTIPLIER", 4.0) or 4.0)
    minimum = int(getattr(settings, "UPLOAD_MIN_FREE_SPACE_BYTES", 8 * 1024 * 1024 * 1024) or 0)
    return max(int(file_size_bytes * multiplier), minimum)


def create_native_import_session(
    *,
    settings,
    project_id: str,
    original_filename: str,
    file_size_bytes: int,
    mime_type: str | None,
) -> tuple[NativeImportSession, int, int]:
    ensure_native_import_dirs(settings)

    max_size = max_upload_size_bytes(settings)
    if file_size_bytes > max_size:
        raise NativeImportError(
            "NATIVE_IMPORT_FILE_TOO_LARGE",
            f"File too large. Maximum: {max_size} bytes",
            status_code=413,
        )

    staging_root = _staging_root(settings)
    _, _, free = shutil.disk_usage(staging_root)
    required = _required_free_bytes(settings, file_size_bytes)
    if free < required:
        raise NativeImportError(
            "NATIVE_IMPORT_DISK_SPACE_LOW",
            f"Insufficient disk space for import. Required {required} bytes, available {free} bytes.",
            status_code=507,
            retryable=True,
        )

    token = str(uuid.uuid4())
    extension = Path(original_filename).suffix.lower() or ".mp4"
    safe_stem = sanitize_filename(Path(original_filename).stem)
    staged_filename = f"{token}-{safe_stem}{extension}"
    staged_path = staging_root / staged_filename
    part_path = staged_path.with_suffix(staged_path.suffix + ".part")
    manifest_path = _manifest_root(settings) / f"{token}.json"
    created_at = _now_iso()

    session = NativeImportSession(
        token=token,
        project_id=project_id,
        original_filename=original_filename,
        mime_type=mime_type,
        file_size_bytes=file_size_bytes,
        staging_relative_path=_relative_to_storage(settings, staged_path),
        staging_part_relative_path=_relative_to_storage(settings, part_path),
        manifest_relative_path=_relative_to_storage(settings, manifest_path),
        created_at=created_at,
        status="initialized",
        updated_at=created_at,
        bytes_received=0,
    )
    session.events.append(_event(session, "operation.accepted", "accepted"))
    _write_json_atomic(manifest_path, session.as_dict())
    return session, free, required


def _legacy_phase(status: str) -> str:
    if status.startswith("orphaned:"):
        return "quarantined"
    return {
        "initialized": "accepted",
        "copying": "copying",
        "copied": "staged",
        "finalizing": "finalizing",
        "finalized": "completed",
        "cancelled": "cancelled",
        "copy_failed": "failed",
        "interrupted": "interrupted",
    }.get(status, "failed")


def load_native_import_session(settings, token: str) -> NativeImportSession:
    manifest_path = _manifest_root(settings) / f"{token}.json"
    if not manifest_path.exists():
        raise NativeImportError(
            "NATIVE_IMPORT_NOT_FOUND",
            f"Import session {token} was not found",
            status_code=404,
        )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload.setdefault("updated_at", payload.get("created_at"))
    payload.setdefault("bytes_received", 0)
    payload.setdefault("last_error", None)
    payload.setdefault("schema_version", IMPORT_SCHEMA_VERSION)
    payload.setdefault("phase", _legacy_phase(str(payload.get("status") or "initialized")))
    payload.setdefault("restartable", payload["phase"] in {"interrupted", "failed"})
    payload.setdefault("error", None)
    payload.setdefault("events", [])
    return NativeImportSession(**payload)


def save_native_import_session(settings, session: NativeImportSession) -> None:
    manifest_path = _resolve_within_storage(settings, session.manifest_relative_path)
    _write_json_atomic(manifest_path, session.as_dict())


def resolve_staged_path(settings, session: NativeImportSession, *, part: bool = False) -> Path:
    relative = session.staging_part_relative_path if part else session.staging_relative_path
    return _resolve_within_storage(settings, relative)


def get_native_import_received_bytes(settings, session: NativeImportSession) -> int:
    staged_path = resolve_staged_path(settings, session, part=False)
    if staged_path.exists():
        return staged_path.stat().st_size
    part_path = resolve_staged_path(settings, session, part=True)
    if part_path.exists():
        return part_path.stat().st_size
    return 0


def mark_native_import_status(settings, session: NativeImportSession, status: str) -> NativeImportSession:
    phase = _legacy_phase(status)
    error = None
    if status == "copy_failed":
        error = NativeImportError(
            "NATIVE_IMPORT_PROMOTION_FAILED",
            "The staged import could not be promoted into project storage.",
            retryable=True,
        ).as_dict()
    return _transition(
        settings,
        session,
        status=status,
        phase=phase,
        event_type=f"operation.{phase}",
        restartable=phase in {"failed", "interrupted"},
        error=error,
    )


def append_native_import_chunk(
    settings,
    session: NativeImportSession,
    *,
    offset: int,
    chunk: bytes,
) -> tuple[NativeImportSession, int, bool]:
    if not chunk:
        raise NativeImportError("NATIVE_IMPORT_EMPTY_CHUNK", "Upload chunk was empty")
    if session.status in {"cancelled", "finalizing", "finalized"} or session.status.startswith("orphaned:"):
        raise NativeImportError(
            "NATIVE_IMPORT_NOT_WRITABLE",
            f"Upload session is not writable because it is {session.status}",
        )

    staged_path = resolve_staged_path(settings, session, part=False)
    part_path = resolve_staged_path(settings, session, part=True)
    part_path.parent.mkdir(parents=True, exist_ok=True)

    if staged_path.exists():
        staged_size = staged_path.stat().st_size
        if staged_size >= session.file_size_bytes:
            raise NativeImportError(
                "NATIVE_IMPORT_ALREADY_COMPLETE",
                "Upload session is already complete",
            )

    current_size = part_path.stat().st_size if part_path.exists() else 0
    if offset != current_size:
        raise NativeImportError(
            "NATIVE_IMPORT_OFFSET_CONFLICT",
            f"Unexpected chunk offset. Expected {current_size} bytes but received {offset}.",
            retryable=True,
        )

    next_size = offset + len(chunk)
    if next_size > session.file_size_bytes:
        raise NativeImportError(
            "NATIVE_IMPORT_SIZE_MISMATCH",
            f"Chunk would exceed declared file size. Expected at most {session.file_size_bytes} bytes.",
        )

    with open(part_path, "ab") as handle:
        handle.write(chunk)
        handle.flush()
        os.fsync(handle.fileno())

    bytes_received = part_path.stat().st_size
    completed = bytes_received == session.file_size_bytes
    if bytes_received != next_size:
        raise OSError(
            f"Chunk write failed. Expected {next_size} bytes after append but found {bytes_received} bytes."
        )

    if completed:
        os.replace(part_path, staged_path)
        _sync_directory(staged_path.parent)

    updated = _transition(
        settings,
        session,
        status="copied" if completed else "copying",
        phase="staged" if completed else "copying",
        event_type="copy.staged" if completed else "copy.progress",
        bytes_received=bytes_received,
        payload={"bytesReceived": bytes_received},
    )
    return updated, bytes_received, completed


def cancel_native_import_session(settings, token: str) -> tuple[NativeImportSession, list[str]]:
    session = load_native_import_session(settings, token)
    if session.phase == "completed":
        raise NativeImportError(
            "NATIVE_IMPORT_ALREADY_COMPLETE",
            "A completed import cannot be cancelled.",
        )
    if session.phase == "cancelled":
        return session, []
    session = _transition(
        settings,
        session,
        status="cancelling",
        phase="cancelling",
        event_type="operation.cancelling",
    )
    removed_files: list[str] = []
    for path in (resolve_staged_path(settings, session, part=True), resolve_staged_path(settings, session, part=False)):
        if path.exists():
            path.unlink()
            removed_files.append(_relative_to_storage(settings, path))
    session = _transition(
        settings,
        session,
        status="cancelled",
        phase="cancelled",
        event_type="operation.cancelled",
        bytes_received=0,
        payload={"removedFiles": removed_files},
    )
    return session, removed_files


def quarantine_native_import(settings, session: NativeImportSession, source_path: Path, reason: str) -> Path:
    ensure_native_import_dirs(settings)
    orphan_root = _orphan_root(settings)
    target = orphan_root / f"{session.token}-{sanitize_filename(Path(session.original_filename).name)}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if source_path.exists():
        os.replace(source_path, target)
    typed_error = NativeImportError(
        "NATIVE_IMPORT_FINALIZE_FAILED",
        reason,
        status_code=500,
        retryable=True,
    ).as_dict()
    _transition(
        settings,
        session,
        status=f"orphaned:{reason}",
        phase="quarantined",
        event_type="operation.quarantined",
        bytes_received=target.stat().st_size if target.exists() else 0,
        restartable=True,
        error=typed_error,
        payload={"quarantinePath": _relative_to_storage(settings, target)},
    )
    return target


def record_native_import_progress(
    settings,
    session: NativeImportSession,
    *,
    phase: str,
) -> NativeImportSession:
    """Persist shell-owned copy boundaries while bytes remain file-derived."""

    if phase not in {"copying", "staged"}:
        raise NativeImportError(
            "NATIVE_IMPORT_PHASE_INVALID",
            f"The shell cannot publish native import phase {phase!r}.",
        )
    if session.phase in TERMINAL_PHASES:
        raise NativeImportError(
            "NATIVE_IMPORT_NOT_WRITABLE",
            f"Import operation is already {session.phase}.",
        )
    received = get_native_import_received_bytes(settings, session)
    if phase == "staged" and received != session.file_size_bytes:
        raise NativeImportError(
            "NATIVE_IMPORT_SIZE_MISMATCH",
            f"Staged file has {received} bytes; expected {session.file_size_bytes}.",
            retryable=True,
        )
    return _transition(
        settings,
        session,
        status="copied" if phase == "staged" else "copying",
        phase=phase,
        event_type="copy.staged" if phase == "staged" else "copy.started",
        bytes_received=received,
        payload={"bytesReceived": received},
    )


def restart_native_import_session(settings, token: str) -> NativeImportSession:
    session = load_native_import_session(settings, token)
    if not session.restartable and session.phase not in {"interrupted", "failed", "quarantined"}:
        raise NativeImportError(
            "NATIVE_IMPORT_NOT_RESTARTABLE",
            f"Import operation in phase {session.phase} is not restartable.",
        )
    staged = resolve_staged_path(settings, session)
    part = resolve_staged_path(settings, session, part=True)
    if staged.exists() and staged.stat().st_size == session.file_size_bytes:
        phase, status = "staged", "copied"
    elif part.exists():
        phase, status = "copying", "copying"
    else:
        phase, status = "accepted", "initialized"
    return _transition(
        settings,
        session,
        status=status,
        phase=phase,
        event_type="operation.restarted",
        restartable=False,
        payload={"resumePhase": phase},
    )


def recover_native_import_sessions(settings) -> int:
    """Mark only in-flight operations interrupted after an engine restart."""

    ensure_native_import_dirs(settings)
    recovered = 0
    for manifest_path in _manifest_root(settings).glob("*.json"):
        try:
            session = load_native_import_session(settings, manifest_path.stem)
        except (NativeImportError, OSError, ValueError, json.JSONDecodeError):
            continue
        if session.phase not in {"copying", "finalizing", "cancelling"}:
            continue
        error = NativeImportError(
            "NATIVE_IMPORT_ENGINE_RESTARTED",
            f"The engine restarted while the import was {session.phase}.",
            retryable=True,
        ).as_dict()
        _transition(
            settings,
            session,
            status="interrupted",
            phase="interrupted",
            event_type="operation.interrupted",
            restartable=True,
            error=error,
            payload={"previousPhase": session.phase},
        )
        recovered += 1
    return recovered


def list_native_import_orphans(settings, project_id: str | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    ensure_native_import_dirs(settings)
    warnings: list[str] = []
    known_tokens: dict[str, NativeImportSession] = {}
    for manifest_path in _manifest_root(settings).glob("*.json"):
        try:
            session = load_native_import_session(settings, manifest_path.stem)
            if project_id and session.project_id != project_id:
                continue
            known_tokens[session.token] = session
        except Exception as exc:
            warnings.append(f"Could not parse import manifest {manifest_path.name}: {exc}")

    orphan_records: list[dict[str, Any]] = []
    for root, reason in ((_staging_root(settings), "staged_file_without_finalization"), (_orphan_root(settings), "quarantined_after_finalize_failure")):
        for path in root.glob("*"):
            if path.is_dir() or path.name == "manifests":
                continue
            token = path.name.split("-", 1)[0]
            session = known_tokens.get(token)
            if project_id and session and session.project_id != project_id:
                continue
            if session and session.phase in {"accepted", "copying"} and path.suffix == ".part":
                max_age_hours = int(getattr(settings, "UPLOAD_ABANDONED_PART_MAX_AGE_HOURS", 24) or 24)
                modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                if modified > datetime.now(timezone.utc) - timedelta(hours=max_age_hours):
                    continue
            orphan_records.append(
                {
                    "path": _relative_to_storage(settings, path),
                    "size_bytes": path.stat().st_size,
                    "modified_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                    "reason": reason if session is None else f"{reason}:{session.status}",
                }
            )
    orphan_records.sort(key=lambda item: item["modified_at"], reverse=True)
    return orphan_records, warnings
