"""Durable single-machine jobs/status/events backed by the native SQLite DB."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ACTIVE_JOB_STATUSES = frozenset({"queued", "running", "cancel_requested"})
TERMINAL_JOB_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))


class DurableJobStore:
    """A small SQLite queue suitable for one native engine process.

    Each operation opens its own connection, uses a bounded busy timeout and
    commits state and event records in one transaction.  This lets API calls,
    background workers and a restart recovery pass safely share the database.
    """

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path).resolve(strict=False)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def _session(self):  # type: ignore[no-untyped-def]
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._session() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS desktop_jobs (
                    job_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS desktop_job_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES desktop_jobs(job_id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_desktop_job_events_job_id
                    ON desktop_job_events(job_id, event_id);
                """
            )

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for key in ("payload_json", "result_json"):
            raw = result.get(key)
            result[key.removesuffix("_json")] = json.loads(raw) if raw else None
            del result[key]
        return result

    def create_job(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        job_id = job_id or str(uuid.uuid4())
        now = _now()
        with self._lock, self._session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO desktop_jobs "
                "(job_id, kind, status, payload_json, created_at, updated_at) "
                "VALUES (?, ?, 'queued', ?, ?, ?)",
                (job_id, kind, _json(payload), now, now),
            )
            connection.execute(
                "INSERT INTO desktop_job_events (job_id, event_type, payload_json, created_at) "
                "VALUES (?, 'created', ?, ?)",
                (job_id, _json(payload), now),
            )
            connection.commit()
        return self.get_job(job_id)  # type: ignore[return-value]

    def update_job(
        self,
        job_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        event_type: str = "status",
        event_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _now()
        with self._lock, self._session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute(
                "SELECT 1 FROM desktop_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if exists is None:
                connection.rollback()
                raise KeyError(f"Unknown native job: {job_id}")
            connection.execute(
                "UPDATE desktop_jobs SET status = ?, result_json = ?, error = ?, updated_at = ? "
                "WHERE job_id = ?",
                (status, _json(result) if result is not None else None, error, now, job_id),
            )
            payload = dict(event_payload or {})
            payload.setdefault("status", status)
            if error:
                payload.setdefault("error", error)
            connection.execute(
                "INSERT INTO desktop_job_events (job_id, event_type, payload_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (job_id, event_type, _json(payload), now),
            )
            connection.commit()
        return self.get_job(job_id)  # type: ignore[return-value]

    def append_event(
        self, job_id: str, event_type: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        now = _now()
        with self._lock, self._session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM desktop_jobs WHERE job_id = ?", (job_id,)
            ).fetchone() is None:
                connection.rollback()
                raise KeyError(f"Unknown native job: {job_id}")
            cursor = connection.execute(
                "INSERT INTO desktop_job_events (job_id, event_type, payload_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (job_id, event_type, _json(payload), now),
            )
            connection.commit()
            event_id = cursor.lastrowid
        return {
            "eventId": event_id,
            "jobId": job_id,
            "eventType": event_type,
            "payload": payload or {},
            "createdAt": now,
        }

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._session() as connection:
            return self._row(
                connection.execute(
                    "SELECT * FROM desktop_jobs WHERE job_id = ?", (job_id,)
                ).fetchone()
            )

    def list_jobs(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._session() as connection:
            if status:
                rows = connection.execute(
                    "SELECT * FROM desktop_jobs WHERE status = ? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM desktop_jobs ORDER BY updated_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._row(row) for row in rows if row is not None]  # type: ignore[list-item]

    def list_events(self, job_id: str, *, after_event_id: int = 0) -> list[dict[str, Any]]:
        with self._session() as connection:
            rows = connection.execute(
                "SELECT event_id, job_id, event_type, payload_json, created_at "
                "FROM desktop_job_events WHERE job_id = ? AND event_id > ? ORDER BY event_id",
                (job_id, after_event_id),
            ).fetchall()
        return [
            {
                "eventId": row["event_id"],
                "jobId": row["job_id"],
                "eventType": row["event_type"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def recover_inflight(self) -> int:
        """Mark jobs interrupted by process termination and append events."""
        now = _now()
        with self._lock, self._session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT job_id FROM desktop_jobs WHERE status IN ('queued', 'running', 'cancel_requested')"
            ).fetchall()
            for row in rows:
                job_id = row["job_id"]
                connection.execute(
                    "UPDATE desktop_jobs SET status = 'interrupted', error = ?, updated_at = ? "
                    "WHERE job_id = ?",
                    ("Native engine stopped before the job reached a terminal state.", now, job_id),
                )
                connection.execute(
                    "INSERT INTO desktop_job_events (job_id, event_type, payload_json, created_at) "
                    "VALUES (?, 'recovered', ?, ?)",
                    (job_id, _json({"status": "interrupted"}), now),
                )
            connection.commit()
        return len(rows)
