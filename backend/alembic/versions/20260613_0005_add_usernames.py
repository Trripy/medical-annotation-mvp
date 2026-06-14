"""add usernames

Revision ID: 20260613_0005
Revises: 20260604_0004
Create Date: 2026-06-13 00:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260613_0005"
down_revision: str | None = "20260604_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("username", sa.String(length=255), nullable=True))
    op.add_column(
        "users",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.execute("UPDATE users SET username = CONCAT('user_', id) WHERE username IS NULL")
    op.alter_column("users", "username", nullable=False)
    op.alter_column("users", "email", existing_type=sa.String(length=255), nullable=True)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.alter_column("users", "email", existing_type=sa.String(length=255), nullable=False)
    op.drop_column("users", "updated_at")
    op.drop_column("users", "username")
