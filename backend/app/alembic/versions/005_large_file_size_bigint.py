"""Promote upload size columns to bigint

Revision ID: 005_large_file_size_bigint
Revises: 004_project_media_sources
Create Date: 2026-06-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "005_large_file_size_bigint"
down_revision: Union[str, None] = "004_project_media_sources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "project_assets",
        "file_size_bytes",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        postgresql_using="file_size_bytes::bigint",
        existing_nullable=True,
    )
    op.alter_column(
        "videos",
        "file_size_bytes",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        postgresql_using="file_size_bytes::bigint",
        existing_nullable=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    project_asset_max = bind.execute(sa.text("SELECT COALESCE(MAX(file_size_bytes), 0) FROM project_assets")).scalar_one()
    video_max = bind.execute(sa.text("SELECT COALESCE(MAX(file_size_bytes), 0) FROM videos")).scalar_one()
    limit = 2147483647
    if int(project_asset_max or 0) > limit or int(video_max or 0) > limit:
        raise RuntimeError("Cannot downgrade file_size_bytes columns to INTEGER while values exceed 2,147,483,647")

    op.alter_column(
        "videos",
        "file_size_bytes",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        postgresql_using="file_size_bytes::integer",
        existing_nullable=True,
    )
    op.alter_column(
        "project_assets",
        "file_size_bytes",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        postgresql_using="file_size_bytes::integer",
        existing_nullable=True,
    )
