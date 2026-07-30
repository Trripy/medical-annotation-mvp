"""add research video trim provenance

Revision ID: 20260728_0016
Revises: 20260722_0015
Create Date: 2026-07-28 00:16:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_0016"
down_revision: str | None = "20260722_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("research_videos", sa.Column("source_video_id", sa.Integer(), nullable=True))
    op.add_column(
        "research_videos",
        sa.Column("origin_type", sa.String(length=32), nullable=False, server_default=sa.text("'uploaded'")),
    )
    op.add_column("research_videos", sa.Column("trim_start_frame", sa.Integer(), nullable=True))
    op.add_column("research_videos", sa.Column("trim_end_frame_exclusive", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_research_videos_source_video_id",
        "research_videos",
        "research_videos",
        ["source_video_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_research_videos_source_video_id", "research_videos", ["source_video_id"], unique=False)
    op.create_index(
        "ix_research_videos_source_trim_processing",
        "research_videos",
        ["source_video_id", "trim_start_frame", "trim_end_frame_exclusive", "status"],
        unique=False,
    )
    op.create_check_constraint(
        "ck_research_videos_origin_type",
        "research_videos",
        "origin_type IN ('uploaded', 'server_imported', 'trimmed')",
    )
    op.create_check_constraint(
        "ck_research_videos_trim_start_non_negative",
        "research_videos",
        "trim_start_frame IS NULL OR trim_start_frame >= 0",
    )
    op.create_check_constraint(
        "ck_research_videos_trim_end_after_start",
        "research_videos",
        "trim_end_frame_exclusive IS NULL OR trim_start_frame IS NULL OR trim_end_frame_exclusive > trim_start_frame",
    )
    op.create_check_constraint(
        "ck_research_videos_trimmed_provenance_present",
        "research_videos",
        "origin_type != 'trimmed' OR (trim_start_frame IS NOT NULL AND trim_end_frame_exclusive IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_research_videos_trimmed_provenance_present", "research_videos", type_="check")
    op.drop_constraint("ck_research_videos_trim_end_after_start", "research_videos", type_="check")
    op.drop_constraint("ck_research_videos_trim_start_non_negative", "research_videos", type_="check")
    op.drop_constraint("ck_research_videos_origin_type", "research_videos", type_="check")
    op.drop_index("ix_research_videos_source_trim_processing", table_name="research_videos")
    op.drop_index("ix_research_videos_source_video_id", table_name="research_videos")
    op.drop_constraint("fk_research_videos_source_video_id", "research_videos", type_="foreignkey")
    op.drop_column("research_videos", "trim_end_frame_exclusive")
    op.drop_column("research_videos", "trim_start_frame")
    op.drop_column("research_videos", "origin_type")
    op.drop_column("research_videos", "source_video_id")
