"""create user settings

Revision ID: 20260613_0006
Revises: 20260613_0005
Create Date: 2026-06-13 00:06:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260613_0006"
down_revision: str | None = "20260613_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("edge_snap_threshold", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("default_tool", sa.String(length=32), nullable=False, server_default="sam2"),
        sa.Column("add_polygon_vertex_shortcut", sa.String(length=32), nullable=False, server_default="shift"),
        sa.Column("delete_polygon_vertex_shortcut", sa.String(length=32), nullable=False, server_default="alt"),
        sa.Column("pan_modifier_shortcut", sa.String(length=32), nullable=False, server_default="ctrl"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_settings_user_id"),
    )
    op.create_index(op.f("ix_user_settings_id"), "user_settings", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_settings_id"), table_name="user_settings")
    op.drop_table("user_settings")
