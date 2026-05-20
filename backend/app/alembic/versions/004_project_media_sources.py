"""Add project media source typing

Revision ID: 004_project_media_sources
Revises: 003_project_assets
Create Date: 2026-05-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004_project_media_sources"
down_revision: Union[str, None] = "003_project_assets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "project_assets",
        sa.Column("source_type", sa.String(40), nullable=False, server_default="other"),
    )
    op.add_column(
        "project_assets",
        sa.Column("sync_role", sa.String(40), nullable=False, server_default="none"),
    )

    op.execute(
        """
        UPDATE project_assets
        SET
            source_type = CASE
                WHEN kind = 'mixed_video' THEN 'mixed_video'
                WHEN kind = 'screen_video' THEN 'screen_recording'
                WHEN kind = 'camera_video' THEN 'camera_recording'
                WHEN kind = 'audio' THEN 'separate_audio'
                WHEN kind = 'slide_deck' THEN 'slide_deck'
                WHEN kind = 'pdf_notes' THEN 'pdf_notes'
                WHEN kind = 'text_notes' THEN 'text_notes'
                WHEN kind = 'course_material' THEN 'course_material'
                WHEN kind = 'image' THEN 'image'
                WHEN kind = 'b_roll' THEN 'b_roll'
                WHEN kind = 'transcript' THEN 'transcript'
                ELSE 'other'
            END,
            sync_role = CASE
                WHEN role = 'primary' THEN 'primary_timeline'
                WHEN role = 'screen' THEN 'screen_reference'
                WHEN role = 'camera' THEN 'camera_overlay'
                WHEN role = 'audio' THEN 'audio_master'
                WHEN role IN ('slides', 'notes', 'supporting_material') THEN 'structure_reference'
                ELSE 'none'
            END
        """
    )


def downgrade() -> None:
    op.drop_column("project_assets", "sync_role")
    op.drop_column("project_assets", "source_type")
