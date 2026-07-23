"""create research skill tables

Revision ID: 20260722_0015
Revises: 20260722_0014
Create Date: 2026-07-22 00:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0015"
down_revision: str | None = "20260722_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_skill_rubrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("phase_protocol_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_research_skill_rubrics_version_positive"),
        sa.CheckConstraint("status IN ('draft', 'active', 'archived')", name="ck_research_skill_rubrics_status"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["phase_protocol_id"], ["research_phase_protocols.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_research_skill_rubrics_name_version"),
    )
    op.create_index(op.f("ix_research_skill_rubrics_id"), "research_skill_rubrics", ["id"], unique=False)

    op.create_table(
        "research_skill_criteria",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rubric_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("score_type", sa.String(length=32), nullable=False),
        sa.Column("min_value", sa.Float(), nullable=True),
        sa.Column("max_value", sa.Float(), nullable=True),
        sa.Column("step", sa.Float(), nullable=True),
        sa.Column("options_json", sa.JSON(), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allow_na", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("display_order >= 0", name="ck_research_skill_criteria_display_order_non_negative"),
        sa.CheckConstraint("weight IS NULL OR weight >= 0", name="ck_research_skill_criteria_weight_non_negative"),
        sa.CheckConstraint("scope IN ('overall', 'phase')", name="ck_research_skill_criteria_scope"),
        sa.CheckConstraint(
            "score_type IN ('integer_scale', 'number', 'single_choice', 'boolean', 'text')",
            name="ck_research_skill_criteria_score_type",
        ),
        sa.ForeignKeyConstraint(["rubric_id"], ["research_skill_rubrics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rubric_id", "key", name="uq_research_skill_criteria_rubric_key"),
        sa.UniqueConstraint("rubric_id", "name", name="uq_research_skill_criteria_rubric_name"),
    )
    op.create_index(op.f("ix_research_skill_criteria_id"), "research_skill_criteria", ["id"], unique=False)
    op.create_index(
        "ix_research_skill_criteria_rubric_display_order",
        "research_skill_criteria",
        ["rubric_id", "display_order"],
        unique=False,
    )

    op.create_table(
        "research_skill_criterion_phase_labels",
        sa.Column("criterion_id", sa.Integer(), nullable=False),
        sa.Column("phase_label_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["criterion_id"], ["research_skill_criteria.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["phase_label_id"], ["research_phase_labels.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("criterion_id", "phase_label_id"),
    )

    op.create_table(
        "research_skill_assessments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("rubric_id", sa.Integer(), nullable=False),
        sa.Column("rater_id", sa.Integer(), nullable=False),
        sa.Column("phase_annotation_set_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("overall_comment", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'reviewed', 'locked')",
            name="ck_research_skill_assessments_status",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_research_skill_assessments_revision_positive"),
        sa.ForeignKeyConstraint(["phase_annotation_set_id"], ["research_phase_annotation_sets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rater_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rubric_id"], ["research_skill_rubrics.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["video_id"], ["research_videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "video_id",
            "rubric_id",
            "rater_id",
            name="uq_research_skill_assessments_video_rubric_rater",
        ),
    )
    op.create_index(op.f("ix_research_skill_assessments_id"), "research_skill_assessments", ["id"], unique=False)

    op.create_table(
        "research_skill_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("criterion_id", sa.Integer(), nullable=False),
        sa.Column("target_key", sa.String(length=255), nullable=False),
        sa.Column("phase_segment_id", sa.Integer(), nullable=True),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("is_na", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["assessment_id"], ["research_skill_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["criterion_id"], ["research_skill_criteria.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_segment_id"], ["research_phase_segments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assessment_id",
            "criterion_id",
            "target_key",
            name="uq_research_skill_scores_assessment_criterion_target",
        ),
    )
    op.create_index(op.f("ix_research_skill_scores_id"), "research_skill_scores", ["id"], unique=False)
    op.create_index("ix_research_skill_scores_assessment", "research_skill_scores", ["assessment_id"], unique=False)
    op.create_index("ix_research_skill_scores_criterion", "research_skill_scores", ["criterion_id"], unique=False)
    op.create_index("ix_research_skill_scores_phase_segment", "research_skill_scores", ["phase_segment_id"], unique=False)

    op.create_table(
        "research_skill_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("skill_score_id", sa.Integer(), nullable=False),
        sa.Column("start_frame", sa.Integer(), nullable=False),
        sa.Column("end_frame_exclusive", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("start_frame >= 0", name="ck_research_skill_evidence_start_frame_non_negative"),
        sa.CheckConstraint(
            "end_frame_exclusive IS NULL OR end_frame_exclusive > start_frame",
            name="ck_research_skill_evidence_end_after_start",
        ),
        sa.ForeignKeyConstraint(["skill_score_id"], ["research_skill_scores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_research_skill_evidence_id"), "research_skill_evidence", ["id"], unique=False)
    op.create_index(
        "ix_research_skill_evidence_score_start_frame",
        "research_skill_evidence",
        ["skill_score_id", "start_frame"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_research_skill_evidence_score_start_frame", table_name="research_skill_evidence")
    op.drop_index(op.f("ix_research_skill_evidence_id"), table_name="research_skill_evidence")
    op.drop_table("research_skill_evidence")

    op.drop_index("ix_research_skill_scores_phase_segment", table_name="research_skill_scores")
    op.drop_index("ix_research_skill_scores_criterion", table_name="research_skill_scores")
    op.drop_index("ix_research_skill_scores_assessment", table_name="research_skill_scores")
    op.drop_index(op.f("ix_research_skill_scores_id"), table_name="research_skill_scores")
    op.drop_table("research_skill_scores")

    op.drop_index(op.f("ix_research_skill_assessments_id"), table_name="research_skill_assessments")
    op.drop_table("research_skill_assessments")

    op.drop_table("research_skill_criterion_phase_labels")

    op.drop_index("ix_research_skill_criteria_rubric_display_order", table_name="research_skill_criteria")
    op.drop_index(op.f("ix_research_skill_criteria_id"), table_name="research_skill_criteria")
    op.drop_table("research_skill_criteria")

    op.drop_index(op.f("ix_research_skill_rubrics_id"), table_name="research_skill_rubrics")
    op.drop_table("research_skill_rubrics")
