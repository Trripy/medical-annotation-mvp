"""add phase label mapping profiles

Revision ID: 20260730_0017
Revises: 20260728_0016
Create Date: 2026-07-30 00:17:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0017"
down_revision: str | None = "20260728_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_phase_label_mapping_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("protocol_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_research_phase_label_mapping_profiles_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_research_phase_label_mapping_profiles_version_positive"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["protocol_id"], ["research_phase_protocols.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "protocol_id",
            "name",
            "version",
            name="uq_research_phase_label_mapping_profiles_protocol_name_version",
        ),
    )
    op.create_index(
        "ix_research_phase_label_mapping_profiles_id",
        "research_phase_label_mapping_profiles",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_research_phase_label_mapping_profiles_protocol_status",
        "research_phase_label_mapping_profiles",
        ["protocol_id", "status"],
        unique=False,
    )

    op.create_table(
        "research_phase_label_mapping_targets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_research_phase_label_mapping_targets_name_not_blank"),
        sa.CheckConstraint("order_index >= 0", name="ck_research_phase_label_mapping_targets_order_non_negative"),
        sa.ForeignKeyConstraint(["profile_id"], ["research_phase_label_mapping_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "key", name="uq_research_phase_label_mapping_targets_profile_key"),
    )
    op.create_index(
        "ix_research_phase_label_mapping_targets_id",
        "research_phase_label_mapping_targets",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_research_phase_label_mapping_targets_profile_order",
        "research_phase_label_mapping_targets",
        ["profile_id", "order_index"],
        unique=False,
    )

    op.create_table(
        "research_phase_label_mapping_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("source_label_id", sa.Integer(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["research_phase_label_mapping_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_label_id"], ["research_phase_labels.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_id"], ["research_phase_label_mapping_targets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id",
            "source_label_id",
            name="uq_research_phase_label_mapping_rules_profile_source_label",
        ),
    )
    op.create_index(
        "ix_research_phase_label_mapping_rules_id",
        "research_phase_label_mapping_rules",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_research_phase_label_mapping_rules_target",
        "research_phase_label_mapping_rules",
        ["target_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_research_phase_label_mapping_rules_target", table_name="research_phase_label_mapping_rules")
    op.drop_index("ix_research_phase_label_mapping_rules_id", table_name="research_phase_label_mapping_rules")
    op.drop_table("research_phase_label_mapping_rules")
    op.drop_index("ix_research_phase_label_mapping_targets_profile_order", table_name="research_phase_label_mapping_targets")
    op.drop_index("ix_research_phase_label_mapping_targets_id", table_name="research_phase_label_mapping_targets")
    op.drop_table("research_phase_label_mapping_targets")
    op.drop_index(
        "ix_research_phase_label_mapping_profiles_protocol_status",
        table_name="research_phase_label_mapping_profiles",
    )
    op.drop_index("ix_research_phase_label_mapping_profiles_id", table_name="research_phase_label_mapping_profiles")
    op.drop_table("research_phase_label_mapping_profiles")
