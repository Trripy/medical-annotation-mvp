"""allow classification shape type for annotations

Revision ID: 20260630_0013
Revises: 20260625_0012
Create Date: 2026-06-30 00:13:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260630_0013"
down_revision: str | None = "20260625_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT_NAME = "ck_annotations_shape_type"
NEW_CONSTRAINT_SQL = "shape_type IN ('rectangle', 'polygon', 'point', 'classification')"
OLD_CONSTRAINT_SQL = "shape_type IN ('rectangle', 'polygon', 'point')"


def _recreate_constraint(definition: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("annotations") as batch_op:
            batch_op.drop_constraint(CONSTRAINT_NAME, type_="check")
            batch_op.create_check_constraint(CONSTRAINT_NAME, definition)
        return

    op.drop_constraint(CONSTRAINT_NAME, "annotations", type_="check")
    op.create_check_constraint(CONSTRAINT_NAME, "annotations", definition)


def upgrade() -> None:
    _recreate_constraint(NEW_CONSTRAINT_SQL)


def downgrade() -> None:
    _recreate_constraint(OLD_CONSTRAINT_SQL)
