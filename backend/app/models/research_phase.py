from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.research import ResearchVideo
    from app.models.user import User


class ResearchPhaseProtocol(Base):
    __tablename__ = "research_phase_protocols"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_research_phase_protocols_name_version"),
        CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="ck_research_phase_protocols_status",
        ),
        CheckConstraint("version >= 1", name="ck_research_phase_protocols_version_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    created_by: Mapped[User | None] = relationship("User", back_populates="created_phase_protocols")
    labels: Mapped[list[ResearchPhaseLabel]] = relationship(
        back_populates="protocol",
        order_by="ResearchPhaseLabel.display_order",
    )
    annotation_sets: Mapped[list[ResearchPhaseAnnotationSet]] = relationship(
        back_populates="protocol",
    )


class ResearchPhaseLabel(Base):
    __tablename__ = "research_phase_labels"
    __table_args__ = (
        UniqueConstraint("protocol_id", "key", name="uq_research_phase_labels_protocol_key"),
        UniqueConstraint("protocol_id", "name", name="uq_research_phase_labels_protocol_name"),
        UniqueConstraint("protocol_id", "shortcut", name="uq_research_phase_labels_protocol_shortcut"),
        CheckConstraint("display_order >= 0", name="ck_research_phase_labels_display_order_non_negative"),
        CheckConstraint(
            "shortcut IS NULL OR length(trim(shortcut)) > 0",
            name="ck_research_phase_labels_shortcut_not_blank",
        ),
        Index("ix_research_phase_labels_protocol_display_order", "protocol_id", "display_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    protocol_id: Mapped[int] = mapped_column(
        ForeignKey("research_phase_protocols.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    color: Mapped[str] = mapped_column(String(16), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    shortcut: Mapped[str | None] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    protocol: Mapped[ResearchPhaseProtocol] = relationship(back_populates="labels")
    segments: Mapped[list[ResearchPhaseSegment]] = relationship(back_populates="phase_label")


class ResearchPhaseAnnotationSet(Base):
    __tablename__ = "research_phase_annotation_sets"
    __table_args__ = (
        UniqueConstraint(
            "video_id",
            "protocol_id",
            "annotator_id",
            name="uq_research_phase_annotation_sets_video_protocol_annotator",
        ),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'reviewed', 'locked')",
            name="ck_research_phase_annotation_sets_status",
        ),
        CheckConstraint("revision >= 1", name="ck_research_phase_annotation_sets_revision_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    video_id: Mapped[int] = mapped_column(
        ForeignKey("research_videos.id", ondelete="CASCADE"),
        nullable=False,
    )
    protocol_id: Mapped[int] = mapped_column(
        ForeignKey("research_phase_protocols.id", ondelete="RESTRICT"),
        nullable=False,
    )
    annotator_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    video: Mapped[ResearchVideo] = relationship("ResearchVideo", back_populates="phase_annotation_sets")
    protocol: Mapped[ResearchPhaseProtocol] = relationship(back_populates="annotation_sets")
    annotator: Mapped[User] = relationship("User", back_populates="phase_annotation_sets")
    segments: Mapped[list[ResearchPhaseSegment]] = relationship(
        back_populates="annotation_set",
        cascade="all, delete-orphan",
        order_by="ResearchPhaseSegment.start_frame",
    )


class ResearchPhaseSegment(Base):
    __tablename__ = "research_phase_segments"
    __table_args__ = (
        CheckConstraint("start_frame >= 0", name="ck_research_phase_segments_start_frame_non_negative"),
        CheckConstraint(
            "end_frame_exclusive IS NULL OR end_frame_exclusive > start_frame",
            name="ck_research_phase_segments_end_after_start",
        ),
        CheckConstraint(
            "source IN ('manual', 'model_suggestion', 'model_corrected', 'imported')",
            name="ck_research_phase_segments_source",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_research_phase_segments_confidence_range",
        ),
        Index("ix_research_phase_segments_annotation_set_start_frame", "annotation_set_id", "start_frame"),
        Index("ix_research_phase_segments_annotation_set_phase_label", "annotation_set_id", "phase_label_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    annotation_set_id: Mapped[int] = mapped_column(
        ForeignKey("research_phase_annotation_sets.id", ondelete="CASCADE"),
        nullable=False,
    )
    phase_label_id: Mapped[int] = mapped_column(
        ForeignKey("research_phase_labels.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Segments use [start_frame, end_frame_exclusive) semantics.
    start_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    end_frame_exclusive: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    confidence: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    annotation_set: Mapped[ResearchPhaseAnnotationSet] = relationship(back_populates="segments")
    phase_label: Mapped[ResearchPhaseLabel] = relationship(back_populates="segments")
