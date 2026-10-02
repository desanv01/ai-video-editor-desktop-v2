"""Native SQLite schema initialization and forward-only migrations."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from pathlib import Path
from desktop_native.index_journal import INDEX_DDL

from sqlalchemy import inspect, text


NATIVE_SCHEMA_VERSION = "006_lancedb_index_journal"
MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("001_initial", "Core video, transcript, analysis, plan and material tables"),
    ("002_app_ai_settings", "Persistent AI settings"),
    ("003_project_assets", "Project and project asset compatibility tables"),
    ("004_project_media_sources", "Project source type and sync role columns"),
    ("005_large_file_size_bigint", "Large upload size compatibility marker"),
    ("006_lancedb_index_journal", "Durable LanceDB snapshots and publication journal"),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _columns(connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _add_column_if_missing(connection, table: str, name: str, definition: str) -> None:
    if name not in _columns(connection, table):
        connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}'))


def _validate_revisions(applied: list[str]) -> None:
    known = [revision for revision, _ in MIGRATIONS]
    if applied != known[:len(applied)]:
        raise RuntimeError(f'Unknown, future or non-contiguous native schema revisions: {applied}')


def preflight_native_schema(database_path: str | Path) -> dict:
    """Read revision identity without opening a writable/WAL connection."""
    path = Path(database_path).resolve(strict=False)
    if not path.exists():
        return {'applied': [], 'legacy': False, 'existing': False, 'upgrade': False}
    connection = sqlite3.connect(path.as_uri() + '?mode=ro',uri=True,timeout=30)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        has_ledger = 'desktop_schema_migrations' in tables
        applied = [row[0] for row in connection.execute('SELECT revision FROM desktop_schema_migrations ORDER BY revision')] if has_ledger else []
        _validate_revisions(applied)
        return {'applied':applied,'legacy':bool(tables) and not has_ledger,'existing':bool(tables),'upgrade':bool(tables) and len(applied)<len(MIGRATIONS)}
    finally:
        connection.close()


def initialize_native_schema(connection, metadata, expected=None) -> None:
    """Apply only known pending revisions within the caller's explicit transaction."""
    tables = set(inspect(connection).get_table_names())
    applied = [row[0] for row in connection.exec_driver_sql('SELECT revision FROM desktop_schema_migrations ORDER BY revision')] if 'desktop_schema_migrations' in tables else []
    _validate_revisions(applied)
    if expected is not None and applied != expected['applied']:
        raise RuntimeError('Native schema changed after preflight; restart upgrade')
    if len(applied) == len(MIGRATIONS):
        return
    connection.exec_driver_sql('CREATE TABLE IF NOT EXISTS desktop_schema_migrations (revision TEXT PRIMARY KEY, description TEXT NOT NULL, applied_at TEXT NOT NULL)')
    for revision, description in MIGRATIONS[len(applied):]:
        if revision in ('001_initial','002_app_ai_settings','003_project_assets'):
            metadata.create_all(connection)
        if revision == '003_project_assets':
            if 'videos' in inspect(connection).get_table_names():
                _add_column_if_missing(connection,'videos','project_id','CHAR(36)')
                _add_column_if_missing(connection,'videos','project_asset_id','CHAR(36)')
        if revision == '004_project_media_sources':
            if 'project_assets' in inspect(connection).get_table_names():
                _add_column_if_missing(connection,'project_assets','source_type',"VARCHAR(40) NOT NULL DEFAULT 'other'")
                _add_column_if_missing(connection,'project_assets','sync_role',"VARCHAR(40) NOT NULL DEFAULT 'none'")
        if revision == '006_lancedb_index_journal':
            for statement in INDEX_DDL:
                connection.exec_driver_sql(statement)
        connection.execute(text('INSERT INTO desktop_schema_migrations(revision,description,applied_at) VALUES(:revision,:description,:applied_at)'), {'revision':revision,'description':description,'applied_at':_utc_now()})

    connection.exec_driver_sql(
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
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS desktop_job_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL REFERENCES desktop_jobs(job_id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_desktop_job_events_job_id "
        "ON desktop_job_events(job_id, event_id)"
    )


def native_schema_status(connection) -> dict[str, object]:  # type: ignore[no-untyped-def]
    """Return a deterministic schema/readiness summary for diagnostics."""

    tables = set(inspect(connection).get_table_names())
    applied = []
    if "desktop_schema_migrations" in tables:
        applied = [
            row[0]
            for row in connection.execute(
                text("SELECT revision FROM desktop_schema_migrations ORDER BY revision")
            ).all()
        ]
    required = {"videos", "projects", "project_assets", "app_ai_settings", "desktop_jobs", "desktop_index_sources", "desktop_index_chunks", "desktop_index_operations"}
    return {
        "schemaVersion": NATIVE_SCHEMA_VERSION,
        "ready": required.issubset(tables)
        and all(revision in applied for revision, _ in MIGRATIONS),
        "tables": sorted(tables),
        "appliedMigrations": applied,
    }
