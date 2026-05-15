"""Add project and project asset model

Revision ID: 003_project_assets
Revises: 002_app_ai_settings
Create Date: 2026-05-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "003_project_assets"
down_revision: Union[str, None] = "002_app_ai_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("source_mode", sa.String(30), nullable=False, server_default="single_video"),
        sa.Column("project_type", sa.String(50), server_default="lecture"),
        sa.Column("metadata_json", postgresql.JSON, server_default="{}"),
        sa.Column("error_message", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    op.create_table(
        "project_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("role", sa.String(40), nullable=False, server_default="other"),
        sa.Column("status", sa.String(30), nullable=False, server_default="uploaded"),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("file_size_bytes", sa.Integer),
        sa.Column("mime_type", sa.String(100)),
        sa.Column("duration_seconds", sa.Float),
        sa.Column("sync_offset_seconds", sa.Float, nullable=False, server_default="0"),
        sa.Column("metadata_json", postgresql.JSON, server_default="{}"),
        sa.Column("error_message", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_project_assets_project_id", "project_assets", ["project_id"])

    op.add_column("videos", sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("videos", sa.Column("project_asset_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_videos_project_id_projects",
        "videos",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_videos_project_asset_id_project_assets",
        "videos",
        "project_assets",
        ["project_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint("uq_videos_project_asset_id", "videos", ["project_asset_id"])


def downgrade() -> None:
    op.drop_constraint("uq_videos_project_asset_id", "videos", type_="unique")
    op.drop_constraint("fk_videos_project_asset_id_project_assets", "videos", type_="foreignkey")
    op.drop_constraint("fk_videos_project_id_projects", "videos", type_="foreignkey")
    op.drop_column("videos", "project_asset_id")
    op.drop_column("videos", "project_id")

    op.drop_index("ix_project_assets_project_id", table_name="project_assets")
    op.drop_table("project_assets")
    op.drop_table("projects")
