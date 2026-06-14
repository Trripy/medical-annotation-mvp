"""add image frame index

Revision ID: 20260604_0003
Revises: 20260604_0002
Create Date: 2026-06-04 00:03:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260604_0003"
down_revision: str | None = "20260604_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("images", sa.Column("frame_index", sa.Integer(), nullable=True))
    op.execute(
        """
        WITH ranked_images AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY task_id
                    ORDER BY filename ASC, id ASC
                ) - 1 AS next_frame_index
            FROM images
        )
        UPDATE images
        SET frame_index = ranked_images.next_frame_index
        FROM ranked_images
        WHERE images.id = ranked_images.id
        """
    )


def downgrade() -> None:
    op.drop_column("images", "frame_index")
