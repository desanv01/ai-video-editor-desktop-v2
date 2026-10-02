"""Async database engine and session management.

PostgreSQL remains the default Docker path.  The explicit native desktop
profile uses a file-backed SQLite engine with per-connection safety pragmas;
no connection fallback is attempted when the selected profile is unavailable.
"""

from pathlib import Path
import asyncio
from datetime import datetime, timezone
import uuid

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from config import settings


def _native_database_url() -> str:
    configured = (settings.DATABASE_URL or "").strip()
    if configured.startswith("sqlite+aiosqlite:///"):
        return configured
    if settings.DESKTOP_DB_PATH:
        path = Path(settings.DESKTOP_DB_PATH).expanduser().resolve(strict=False)
    else:
        path = Path(settings.APP_STORAGE_ROOT).expanduser().resolve(strict=False) / "Config" / "engine.sqlite3"
    return f"sqlite+aiosqlite:///{path.as_posix()}"


_is_native_profile = bool(getattr(settings, "is_native_desktop", False))
_database_url = _native_database_url() if _is_native_profile else settings.DATABASE_URL

if _is_native_profile:
    engine = create_async_engine(
        _database_url,
        echo=False,
        connect_args={"timeout": 30},
        pool_pre_ping=True,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _configure_sqlite_connection(dbapi_connection, _connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=FULL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()
else:
    engine = create_async_engine(
        _database_url,
        echo=settings.APP_DEBUG,
        pool_size=20,
        max_overflow=10,
    )

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """FastAPI dependency — yields a DB session per request."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Preflight and back up native upgrades before a write transaction exists."""
    if _is_native_profile:
        from desktop_native.sqlite_schema import initialize_native_schema, preflight_native_schema
        from desktop_native.sqlite_storage import backup_database

        path = Path(engine.url.database).resolve(strict=False)
        expected = await asyncio.to_thread(preflight_native_schema,path)
        if expected['upgrade']:
            backup_root = Path(settings.BACKUP_PATH).resolve(strict=False)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
            destination = backup_root / f'engine.pre-upgrade.{stamp}.{uuid.uuid4().hex}.sqlite3'
            await asyncio.to_thread(backup_database,path,destination)
        path.parent.mkdir(parents=True,exist_ok=True)
        async with engine.begin() as conn:
            # sqlite's implicit DDL transaction behavior must not split revision marking.
            await conn.exec_driver_sql('BEGIN IMMEDIATE')
            await conn.run_sync(lambda sync_conn: initialize_native_schema(sync_conn,Base.metadata,expected))
    else:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

async def dispose_db() -> None:
    """Close pooled connections during graceful native shutdown."""
    await engine.dispose()
