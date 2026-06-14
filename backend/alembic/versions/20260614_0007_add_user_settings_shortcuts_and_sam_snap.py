"""add user settings shortcuts and sam result snap

Revision ID: 20260614_0007
Revises: 20260613_0006
Create Date: 2026-06-14 00:07:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260614_0007"
down_revision: str | None = "20260613_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("polygon_confirm_point_shortcut", sa.String(length=32), nullable=False, server_default="space"),
    )
    op.add_column(
        "user_settings",
        sa.Column("sam_result_edge_snap_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "user_settings",
        sa.Column("sam_result_edge_snap_threshold", sa.Integer(), nullable=False, server_default="5"),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "sam_result_edge_snap_threshold")
    op.drop_column("user_settings", "sam_result_edge_snap_enabled")
    op.drop_column("user_settings", "polygon_confirm_point_shortcut")
