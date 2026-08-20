"""Native SQLite schema initialization and forward-only migrations."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import inspect, text


NATIVE_SCHEMA_VERSION = "005_large_file_size_bigint"
MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("001_initial", "Core video, transcript, analysis, plan and material tables"),
    ("002_app_ai_settings", "Persistent AI settings"),
    ("003_project_assets", "Project and project asset compatibility tables"),
    ("004_project_media_sources", "Project source type and sync role columns"),
    ("005_large_file_size_bigint", "Large upload size compatibility marker"),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _columns(connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _add_column_if_missing(connection, table: str, name: str, definition: str) -> None:
    if name not in _columns(connection, table):
        connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}'))


def initialize_native_schema(connection, metadata) -> None:  # type: ignore[no-untyped-def]
    """Create current ORM tables and apply SQLite-safe additive migrations.

    The existing Alembic revisions stay PostgreSQL-specific.  Native SQLite
    uses this equivalent migration ledger so a user's database can be opened
    and upgraded without importing or executing PostgreSQL DDL.
    """

    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    connection.exec_driver_sql("PRAGMA busy_timeout=30000")
    metadata.create_all(connection)

    # Databases created by an earlier native preview may predate the current
    # project columns.  SQLite cannot add a column with a dynamic default, so
    # only constant-safe definitions are used here.
    if "videos" in inspect(connection).get_table_names():
        _add_column_if_missing(connection, "videos", "project_id", "CHAR(36)")
        _add_column_if_missing(connection, "videos", "project_asset_id", "CHAR(36)")
    if "project_assets" in inspect(connection).get_table_names():
        _add_column_if_missing(
            connection,
            "project_assets",
            "source_type",
            "VARCHAR(40) NOT NULL DEFAULT 'other'",
        )
        _add_column_if_missing(
            connection,
            "project_assets",
            "sync_role",
            "VARCHAR(40) NOT NULL DEFAULT 'none'",
        )

    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS desktop_schema_migrations (
            revision TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    for revision, description in MIGRATIONS:
        connection.execute(
            text(
                "INSERT OR IGNORE INTO desktop_schema_migrations "
                "(revision, description, applied_at) VALUES (:revision, :description, :applied_at)"
            ),
            {
                "revision": revision,
                "description": description,
                "applied_at": _utc_now(),
            },
        )

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
    required = {"videos", "projects", "project_assets", "app_ai_settings", "desktop_jobs"}
    return {
        "schemaVersion": NATIVE_SCHEMA_VERSION,
        "ready": required.issubset(tables)
        and all(revision in applied for revision, _ in MIGRATIONS),
        "tables": sorted(tables),
        "appliedMigrations": applied,
    }
