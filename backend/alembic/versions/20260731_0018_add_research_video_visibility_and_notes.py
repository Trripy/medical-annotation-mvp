"""add research video visibility and notes

Revision ID: 20260731_0018
Revises: 20260730_0017
Create Date: 2026-07-31 00:18:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_0018"
down_revision: str | None = "20260730_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "research_videos",
        sa.Column(
            "hidden_from_video_list",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column("research_videos", sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("research_videos", sa.Column("hidden_reason", sa.String(length=64), nullable=True))
    op.add_column("research_videos", sa.Column("notes", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_research_videos_hidden_reason",
        "research_videos",
        "hidden_reason IS NULL OR hidden_reason IN ('trimmed_source', 'manual')",
    )
    op.create_index(
        "ix_research_videos_hidden_from_video_list",
        "research_videos",
        ["hidden_from_video_list"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_research_videos_hidden_from_video_list", table_name="research_videos")
    op.drop_constraint("ck_research_videos_hidden_reason", "research_videos", type_="check")
    op.drop_column("research_videos", "notes")
    op.drop_column("research_videos", "hidden_reason")
    op.drop_column("research_videos", "hidden_at")
    op.drop_column("research_videos", "hidden_from_video_list")
