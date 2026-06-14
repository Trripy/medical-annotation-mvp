"""add image file and thumbnail paths

Revision ID: 20260604_0002
Revises: 20260604_0001
Create Date: 2026-06-04 00:02:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260604_0002"
down_revision: str | None = "20260604_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("images", sa.Column("file_path", sa.String(length=1024), nullable=True))
    op.add_column("images", sa.Column("thumbnail_path", sa.String(length=1024), nullable=True))
    op.execute("UPDATE images SET file_path = storage_path WHERE file_path IS NULL")
    op.execute("UPDATE images SET thumbnail_path = storage_path WHERE thumbnail_path IS NULL")
    op.alter_column("images", "file_path", nullable=False)
    op.alter_column("images", "thumbnail_path", nullable=False)
    op.drop_column("images", "storage_path")


def downgrade() -> None:
    op.add_column("images", sa.Column("storage_path", sa.String(length=1024), nullable=True))
    op.execute("UPDATE images SET storage_path = file_path WHERE storage_path IS NULL")
    op.alter_column("images", "storage_path", nullable=False)
    op.drop_column("images", "thumbnail_path")
    op.drop_column("images", "file_path")
