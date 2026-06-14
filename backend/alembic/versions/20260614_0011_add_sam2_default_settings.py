"""add sam2 default settings

Revision ID: 20260614_0011
Revises: 20260614_0010
Create Date: 2026-06-14 00:11:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260614_0011"
down_revision: str | None = "20260614_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("sam2_default_model", sa.String(length=64), nullable=False, server_default="sam2_hiera_large"),
    )
    op.add_column(
        "user_settings",
        sa.Column("sam2_default_multimask_output", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "user_settings",
        sa.Column("sam2_default_show_prompt_points", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "user_settings",
        sa.Column("sam2_default_candidate", sa.String(length=8), nullable=False, server_default="best"),
    )
    op.add_column(
        "user_settings",
        sa.Column("sam2_default_polygon_epsilon", sa.Float(), nullable=False, server_default="0.002"),
    )
    op.add_column(
        "user_settings",
        sa.Column("sam2_default_mask_threshold", sa.Float(), nullable=False, server_default="0.0"),
    )
    op.add_column(
        "user_settings",
        sa.Column("sam2_default_min_mask_area", sa.Integer(), nullable=False, server_default="100"),
    )
    op.add_column(
        "user_settings",
        sa.Column("sam2_default_max_hole_area", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "sam2_default_max_hole_area")
    op.drop_column("user_settings", "sam2_default_min_mask_area")
    op.drop_column("user_settings", "sam2_default_mask_threshold")
    op.drop_column("user_settings", "sam2_default_polygon_epsilon")
    op.drop_column("user_settings", "sam2_default_candidate")
    op.drop_column("user_settings", "sam2_default_show_prompt_points")
    op.drop_column("user_settings", "sam2_default_multimask_output")
    op.drop_column("user_settings", "sam2_default_model")
