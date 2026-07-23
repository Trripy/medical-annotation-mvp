from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.research import ResearchVideo
    from app.models.research_phase import (
        ResearchPhaseAnnotationSet,
        ResearchPhaseLabel,
        ResearchPhaseProtocol,
        ResearchPhaseSegment,
    )
    from app.models.user import User


class ResearchSkillRubric(Base):
    __tablename__ = "research_skill_rubrics"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_research_skill_rubrics_name_version"),
        CheckConstraint("version >= 1", name="ck_research_skill_rubrics_version_positive"),
        CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="ck_research_skill_rubrics_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    phase_protocol_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_phase_protocols.id", ondelete="RESTRICT")
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    phase_protocol: Mapped[ResearchPhaseProtocol | None] = relationship("ResearchPhaseProtocol")
    created_by: Mapped[User | None] = relationship("User", back_populates="created_skill_rubrics")
    criteria: Mapped[list[ResearchSkillCriterion]] = relationship(
        back_populates="rubric",
        cascade="all, delete-orphan",
        order_by="ResearchSkillCriterion.display_order",
    )
    assessments: Mapped[list[ResearchSkillAssessment]] = relationship(back_populates="rubric")


class ResearchSkillCriterion(Base):
    __tablename__ = "research_skill_criteria"
    __table_args__ = (
        UniqueConstraint("rubric_id", "key", name="uq_research_skill_criteria_rubric_key"),
        UniqueConstraint("rubric_id", "name", name="uq_research_skill_criteria_rubric_name"),
        CheckConstraint("display_order >= 0", name="ck_research_skill_criteria_display_order_non_negative"),
        CheckConstraint("weight IS NULL OR weight >= 0", name="ck_research_skill_criteria_weight_non_negative"),
        CheckConstraint("scope IN ('overall', 'phase')", name="ck_research_skill_criteria_scope"),
        CheckConstraint(
            "score_type IN ('integer_scale', 'number', 'single_choice', 'boolean', 'text')",
            name="ck_research_skill_criteria_score_type",
        ),
        Index("ix_research_skill_criteria_rubric_display_order", "rubric_id", "display_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    rubric_id: Mapped[int] = mapped_column(ForeignKey("research_skill_rubrics.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    score_type: Mapped[str] = mapped_column(String(32), nullable=False)
    min_value: Mapped[float | None] = mapped_column(Float)
    max_value: Mapped[float | None] = mapped_column(Float)
    step: Mapped[float | None] = mapped_column(Float)
    options_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_na: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    weight: Mapped[float | None] = mapped_column(Float)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    rubric: Mapped[ResearchSkillRubric] = relationship(back_populates="criteria")
    phase_label_links: Mapped[list[ResearchSkillCriterionPhaseLabel]] = relationship(
        back_populates="criterion",
        cascade="all, delete-orphan",
    )
    scores: Mapped[list[ResearchSkillScore]] = relationship(back_populates="criterion")


class ResearchSkillCriterionPhaseLabel(Base):
    __tablename__ = "research_skill_criterion_phase_labels"

    criterion_id: Mapped[int] = mapped_column(
        ForeignKey("research_skill_criteria.id", ondelete="CASCADE"),
        primary_key=True,
    )
    phase_label_id: Mapped[int] = mapped_column(
        ForeignKey("research_phase_labels.id", ondelete="RESTRICT"),
        primary_key=True,
    )

    criterion: Mapped[ResearchSkillCriterion] = relationship(back_populates="phase_label_links")
    phase_label: Mapped[ResearchPhaseLabel] = relationship("ResearchPhaseLabel")


class ResearchSkillAssessment(Base):
    __tablename__ = "research_skill_assessments"
    __table_args__ = (
        UniqueConstraint(
            "video_id",
            "rubric_id",
            "rater_id",
            name="uq_research_skill_assessments_video_rubric_rater",
        ),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'reviewed', 'locked')",
            name="ck_research_skill_assessments_status",
        ),
        CheckConstraint("revision >= 1", name="ck_research_skill_assessments_revision_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("research_videos.id", ondelete="CASCADE"), nullable=False)
    rubric_id: Mapped[int] = mapped_column(ForeignKey("research_skill_rubrics.id", ondelete="RESTRICT"), nullable=False)
    rater_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    phase_annotation_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_phase_annotation_sets.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    overall_comment: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    video: Mapped[ResearchVideo] = relationship("ResearchVideo", back_populates="skill_assessments")
    rubric: Mapped[ResearchSkillRubric] = relationship(back_populates="assessments")
    rater: Mapped[User] = relationship("User", back_populates="skill_assessments")
    phase_annotation_set: Mapped[ResearchPhaseAnnotationSet | None] = relationship("ResearchPhaseAnnotationSet")
    scores: Mapped[list[ResearchSkillScore]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
    )


class ResearchSkillScore(Base):
    __tablename__ = "research_skill_scores"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id",
            "criterion_id",
            "target_key",
            name="uq_research_skill_scores_assessment_criterion_target",
        ),
        Index("ix_research_skill_scores_assessment", "assessment_id"),
        Index("ix_research_skill_scores_criterion", "criterion_id"),
        Index("ix_research_skill_scores_phase_segment", "phase_segment_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("research_skill_assessments.id", ondelete="CASCADE"),
        nullable=False,
    )
    criterion_id: Mapped[int] = mapped_column(
        ForeignKey("research_skill_criteria.id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_key: Mapped[str] = mapped_column(String(255), nullable=False)
    phase_segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_phase_segments.id", ondelete="RESTRICT")
    )
    value_json: Mapped[Any | None] = mapped_column(JSON)
    is_na: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    assessment: Mapped[ResearchSkillAssessment] = relationship(back_populates="scores")
    criterion: Mapped[ResearchSkillCriterion] = relationship(back_populates="scores")
    phase_segment: Mapped[ResearchPhaseSegment | None] = relationship("ResearchPhaseSegment")
    evidence: Mapped[list[ResearchSkillEvidence]] = relationship(
        back_populates="score",
        cascade="all, delete-orphan",
        order_by="ResearchSkillEvidence.start_frame",
    )


class ResearchSkillEvidence(Base):
    __tablename__ = "research_skill_evidence"
    __table_args__ = (
        CheckConstraint("start_frame >= 0", name="ck_research_skill_evidence_start_frame_non_negative"),
        CheckConstraint(
            "end_frame_exclusive IS NULL OR end_frame_exclusive > start_frame",
            name="ck_research_skill_evidence_end_after_start",
        ),
        Index("ix_research_skill_evidence_score_start_frame", "skill_score_id", "start_frame"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    skill_score_id: Mapped[int] = mapped_column(
        ForeignKey("research_skill_scores.id", ondelete="CASCADE"),
        nullable=False,
    )
    start_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    end_frame_exclusive: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    score: Mapped[ResearchSkillScore] = relationship(back_populates="evidence")
