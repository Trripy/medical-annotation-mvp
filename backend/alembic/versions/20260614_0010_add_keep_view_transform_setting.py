"""add keep view transform setting

Revision ID: 20260614_0010
Revises: 20260614_0009
Create Date: 2026-06-14 00:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260614_0010"
down_revision: str | None = "20260614_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("keep_view_transform_on_frame_switch", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "keep_view_transform_on_frame_switch")
