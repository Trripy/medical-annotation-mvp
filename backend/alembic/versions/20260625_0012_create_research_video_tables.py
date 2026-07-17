"""create research video tables

Revision ID: 20260625_0012
Revises: 20260614_0011
Create Date: 2026-06-25 00:12:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260625_0012"
down_revision: str | None = "20260614_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_videos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("thumbnail_path", sa.String(length=1024), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("fps", sa.Float(), nullable=True),
        sa.Column("frame_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="processing"),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_research_videos_id"), "research_videos", ["id"], unique=False)

    op.create_table(
        "research_video_frames",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("frame_index", sa.Integer(), nullable=False),
        sa.Column("timestamp_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["video_id"], ["research_videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("video_id", "frame_index", name="uq_research_video_frames_video_frame"),
    )
    op.create_index(op.f("ix_research_video_frames_id"), "research_video_frames", ["id"], unique=False)

    op.create_table(
        "research_video_labels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=False, server_default="#16a34a"),
        sa.Column("shape_type", sa.String(length=32), nullable=False, server_default="polygon"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["video_id"], ["research_videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("video_id", "name", name="uq_research_video_labels_video_name"),
    )
    op.create_index(op.f("ix_research_video_labels_id"), "research_video_labels", ["id"], unique=False)

    op.create_table(
        "research_video_annotations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("frame_id", sa.Integer(), nullable=False),
        sa.Column("frame_index", sa.Integer(), nullable=False),
        sa.Column("label_id", sa.Integer(), nullable=False),
        sa.Column("shape_type", sa.String(length=32), nullable=False),
        sa.Column("points", sa.JSON(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=True),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("z_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "shape_type IN ('rectangle', 'polygon', 'point')",
            name="ck_research_video_annotations_shape_type",
        ),
        sa.ForeignKeyConstraint(["frame_id"], ["research_video_frames.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["label_id"], ["research_video_labels.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["video_id"], ["research_videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_research_video_annotations_id"), "research_video_annotations", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_research_video_annotations_id"), table_name="research_video_annotations")
    op.drop_table("research_video_annotations")
    op.drop_index(op.f("ix_research_video_labels_id"), table_name="research_video_labels")
    op.drop_table("research_video_labels")
    op.drop_index(op.f("ix_research_video_frames_id"), table_name="research_video_frames")
    op.drop_table("research_video_frames")
    op.drop_index(op.f("ix_research_videos_id"), table_name="research_videos")
    op.drop_table("research_videos")
