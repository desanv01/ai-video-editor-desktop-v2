"""Add persistent AI app settings

Revision ID: 002_app_ai_settings
Revises: 001_initial
Create Date: 2026-05-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002_app_ai_settings"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_ai_settings",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("preferred_processing_mode", sa.String(20), nullable=False, server_default="hybrid"),
        sa.Column("fallback_enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("capabilities_json", postgresql.JSON, nullable=False, server_default="{}"),
        sa.Column("api_keys_json", postgresql.JSON, nullable=False, server_default="{}"),
        sa.Column("local_model_paths_json", postgresql.JSON, nullable=False, server_default="{}"),
        sa.Column("domain_terms_json", postgresql.JSON, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("app_ai_settings")
