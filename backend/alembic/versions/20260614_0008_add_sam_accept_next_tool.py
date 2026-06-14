"""add sam accept next tool setting

Revision ID: 20260614_0008
Revises: 20260614_0007
Create Date: 2026-06-14 00:08:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260614_0008"
down_revision: str | None = "20260614_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("sam_accept_next_tool", sa.String(length=32), nullable=False, server_default="keep_current"),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "sam_accept_next_tool")
