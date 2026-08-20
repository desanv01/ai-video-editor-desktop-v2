"""Portable SQLAlchemy types used by both PostgreSQL and native SQLite.

The Docker profile continues to use PostgreSQL's native UUID type.  Native
desktop stores UUIDs as canonical text so the same ORM models and Pydantic
schemas can be used without a PostgreSQL server.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CHAR, TypeDecorator
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID


class PortableUUID(TypeDecorator[uuid.UUID]):
    """Use PostgreSQL UUID on PostgreSQL and canonical text on SQLite."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PostgreSQLUUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        return value if dialect.name == "postgresql" else str(value)

    def process_result_value(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None or isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))
