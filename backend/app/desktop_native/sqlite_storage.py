"""SQLite backup/restore hooks for the native desktop profile."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class SQLiteStorageError(RuntimeError):
    """Raised when a native database backup or restore cannot be completed."""


def _validate_sqlite_file(path: Path) -> None:
    if not path.is_file():
        raise SQLiteStorageError(f"SQLite database does not exist: {path}")
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise SQLiteStorageError(f"SQLite database could not be opened: {path}") from exc
    if not result or result[0] != "ok":
        raise SQLiteStorageError(f"SQLite integrity check failed for {path}: {result}")


def backup_database(database_path: str | Path, destination: str | Path) -> Path:
    """Create a consistent SQLite backup using SQLite's online backup API."""

    source = Path(database_path).resolve(strict=False)
    target = Path(destination).resolve(strict=False)
    _validate_sqlite_file(source)
    if source == target:
        raise SQLiteStorageError("SQLite backup destination must differ from the source")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    if temporary.exists():
        temporary.unlink()
    try:
        source_conn = sqlite3.connect(source, timeout=30)
        target_conn = sqlite3.connect(temporary, timeout=30)
        try:
            source_conn.backup(target_conn)
            target_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            target_conn.commit()
        finally:
            source_conn.close()
            target_conn.close()
        _validate_sqlite_file(temporary)
        temporary.replace(target)
        return target
    except (OSError, sqlite3.Error) as exc:
        if temporary.exists():
            temporary.unlink()
        raise SQLiteStorageError(f"SQLite backup failed: {source} -> {target}") from exc


def restore_database(
    database_path: str | Path,
    source_backup: str | Path,
    *,
    keep_current_backup: bool = True,
) -> Path | None:
    """Restore a validated backup atomically.

    The caller must dispose active SQLAlchemy connections before invoking this
    hook.  When requested, the current database is preserved beside the
    target as ``.pre-restore.bak`` before replacement.
    """

    target = Path(database_path).resolve(strict=False)
    source = Path(source_backup).resolve(strict=False)
    _validate_sqlite_file(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    previous: Path | None = None
    if target.exists() and keep_current_backup:
        previous = target.with_suffix(target.suffix + ".pre-restore.bak")
        backup_database(target, previous)
    temporary = target.with_suffix(target.suffix + ".restore.part")
    if temporary.exists():
        temporary.unlink()
    try:
        source_conn = sqlite3.connect(source, timeout=30)
        target_conn = sqlite3.connect(temporary, timeout=30)
        try:
            source_conn.backup(target_conn)
            target_conn.commit()
        finally:
            source_conn.close()
            target_conn.close()
        _validate_sqlite_file(temporary)
        temporary.replace(target)
        return previous
    except (OSError, sqlite3.Error) as exc:
        if temporary.exists():
            temporary.unlink()
        raise SQLiteStorageError(f"SQLite restore failed: {source} -> {target}") from exc
