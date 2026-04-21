"""Initial schema — all 6 tables

Revision ID: 001_initial
Revises: None
Create Date: 2026-03-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Videos ──
    op.create_table(
        "videos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("file_size_bytes", sa.Integer),
        sa.Column("duration_seconds", sa.Float),
        sa.Column("resolution", sa.String(20)),
        sa.Column("fps", sa.Float),
        sa.Column("status", sa.String(30), nullable=False, server_default="uploaded"),
        sa.Column("error_message", sa.Text),
        sa.Column("audio_path", sa.String(500)),
        sa.Column("processed_video_path", sa.String(500)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ── Transcripts ──
    op.create_table(
        "transcripts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("video_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("full_text", sa.Text),
        sa.Column("language", sa.String(10)),
        sa.Column("word_count", sa.Integer),
        sa.Column("words_json", postgresql.JSON),
        sa.Column("segments_json", postgresql.JSON),
        sa.Column("speakers_json", postgresql.JSON),
        sa.Column("asr_provider", sa.String(30)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ── Segments ──
    op.create_table(
        "segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("video_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("videos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_index", sa.Integer, nullable=False),
        sa.Column("start_time", sa.Float, nullable=False),
        sa.Column("end_time", sa.Float, nullable=False),
        sa.Column("duration", sa.Float),
        sa.Column("text", sa.Text),
        sa.Column("speaker", sa.String(50)),
        # Agent 2
        sa.Column("topic_label", sa.String(255)),
        sa.Column("summary", sa.Text),
        sa.Column("importance_score", sa.Float),
        sa.Column("segment_type", sa.String(30)),
        # Agent 3
        sa.Column("filler_count", sa.Integer, server_default="0"),
        sa.Column("filler_words", postgresql.JSON),
        sa.Column("pause_duration_total", sa.Float, server_default="0"),
        sa.Column("has_repetition", sa.Boolean, server_default="false"),
        sa.Column("fluency_score", sa.Float),
        # Agent 4
        sa.Column("scene_id", sa.String(50)),
        sa.Column("slide_index", sa.Integer),
        sa.Column("has_slide_change", sa.Boolean, server_default="false"),
        # Agent 5
        sa.Column("action", sa.String(20), server_default="keep"),
        sa.Column("action_confidence", sa.Float),
        sa.Column("action_reason", sa.Text),
        # Teacher
        sa.Column("teacher_action", sa.String(20)),
        sa.Column("teacher_note", sa.Text),
        sa.Column("is_teacher_modified", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_segments_video_id", "segments", ["video_id"])

    # ── Scenes ──
    op.create_table(
        "scenes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("video_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("videos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("timestamp", sa.Float, nullable=False),
        sa.Column("scene_index", sa.Integer, nullable=False),
        sa.Column("scene_type", sa.String(50)),
        sa.Column("thumbnail_path", sa.String(500)),
        sa.Column("confidence", sa.Float),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_scenes_video_id", "scenes", ["video_id"])

    # ── Edit Plans ──
    op.create_table(
        "edit_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("video_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("plan_json", postgresql.JSON),
        sa.Column("original_duration", sa.Float),
        sa.Column("estimated_duration", sa.Float),
        sa.Column("segments_total", sa.Integer),
        sa.Column("segments_keep", sa.Integer),
        sa.Column("segments_cut", sa.Integer),
        sa.Column("segments_highlight", sa.Integer),
        sa.Column("filler_words_removed", sa.Integer),
        sa.Column("silence_removed_seconds", sa.Float),
        sa.Column("is_approved", sa.Boolean, server_default="false"),
        sa.Column("approved_at", sa.DateTime),
        sa.Column("teacher_notes", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ── Course Materials ──
    op.create_table(
        "course_materials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("file_type", sa.String(20)),
        sa.Column("content_text", sa.Text),
        sa.Column("chunk_count", sa.Integer, server_default="0"),
        sa.Column("is_embedded", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("course_materials")
    op.drop_table("edit_plans")
    op.drop_index("ix_scenes_video_id", table_name="scenes")
    op.drop_table("scenes")
    op.drop_index("ix_segments_video_id", table_name="segments")
    op.drop_table("segments")
    op.drop_table("transcripts")
    op.drop_table("videos")
