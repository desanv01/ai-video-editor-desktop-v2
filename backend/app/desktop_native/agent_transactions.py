"""Short caller-session transactions for native agent snapshot/compute/apply."""

from copy import deepcopy
from types import SimpleNamespace

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession


def snapshot(row, fields: tuple[str, ...]) -> SimpleNamespace:
    """Copy loaded scalar/JSON attributes without retaining ORM instrumentation."""
    return SimpleNamespace(**{field: deepcopy(getattr(row, field)) for field in fields})


def column_snapshot(row) -> SimpleNamespace:
    """Copy loaded mapped columns, excluding relationships and ORM state."""
    return snapshot(row, tuple(column.key for column in inspect(row).mapper.column_attrs))


async def commit_native(db: AsyncSession) -> None:
    """Release the transaction, rolling back an unsuccessful/cancelled commit."""
    try:
        await db.commit()
    except BaseException:
        await db.rollback()
        raise


async def fresh_read(db: AsyncSession, statement):
    """End any old read snapshot and expire identities before a fresh apply read.

    Callers invoke this before constructing their apply mutations. Refuse pending
    writes rather than silently discarding or autoflushing unrelated changes.
    """
    if db.new or db.dirty or db.deleted:
        raise RuntimeError("Native agent fresh apply requires no pending ORM writes")
    if db.in_transaction():
        await db.rollback()
    db.expire_all()
    # Validation and owned-column writes must share this short writer boundary.
    await db.execute(text("BEGIN IMMEDIATE"))
    with db.no_autoflush:
        return await db.execute(statement.execution_options(populate_existing=True))
