"""add job layer order rules

Revision ID: 20260909_0019
Revises: 20260731_0018
Create Date: 2026-09-09 00:19:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260909_0019"
down_revision: str | None = "20260731_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_layer_order_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("auto_apply", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_job_layer_order_rules_job_id"),
    )
    op.create_table(
        "job_layer_order_rule_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("label_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["label_id"], ["labels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["job_layer_order_rules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", "label_id", name="uq_job_layer_order_rule_items_rule_label"),
        sa.UniqueConstraint("rule_id", "position", name="uq_job_layer_order_rule_items_rule_position"),
    )
    op.create_index("ix_job_layer_order_rule_items_rule_id", "job_layer_order_rule_items", ["rule_id"])


def downgrade() -> None:
    op.drop_index("ix_job_layer_order_rule_items_rule_id", table_name="job_layer_order_rule_items")
    op.drop_table("job_layer_order_rule_items")
    op.drop_table("job_layer_order_rules")
