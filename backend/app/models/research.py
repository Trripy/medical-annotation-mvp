from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.research_phase import ResearchPhaseAnnotationSet
    from app.models.research_skill import ResearchSkillAssessment
    from app.models.user import User


class ResearchVideo(Base):
    __tablename__ = "research_videos"
    __table_args__ = (
        CheckConstraint(
            "hidden_reason IS NULL OR hidden_reason IN ('trimmed_source', 'manual')",
            name="ck_research_videos_hidden_reason",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(String(1024))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    frame_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="processing")
    source_video_id: Mapped[int | None] = mapped_column(ForeignKey("research_videos.id", ondelete="SET NULL"))
    origin_type: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded")
    trim_start_frame: Mapped[int | None] = mapped_column(Integer)
    trim_end_frame_exclusive: Mapped[int | None] = mapped_column(Integer)
    hidden_from_video_list: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hidden_reason: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
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

    created_by: Mapped[User | None] = relationship("User")
    source_video: Mapped[ResearchVideo | None] = relationship(
        "ResearchVideo",
        remote_side="ResearchVideo.id",
        back_populates="derived_videos",
    )
    derived_videos: Mapped[list[ResearchVideo]] = relationship(
        "ResearchVideo",
        back_populates="source_video",
        passive_deletes=True,
    )
    frames: Mapped[list[ResearchVideoFrame]] = relationship(
        back_populates="video",
        cascade="all, delete-orphan",
        order_by="ResearchVideoFrame.frame_index",
    )
    labels: Mapped[list[ResearchVideoLabel]] = relationship(
        back_populates="video",
        cascade="all, delete-orphan",
        order_by="ResearchVideoLabel.sort_order",
    )
    annotations: Mapped[list[ResearchVideoAnnotation]] = relationship(
        back_populates="video",
        cascade="all, delete-orphan",
    )
    phase_annotation_sets: Mapped[list[ResearchPhaseAnnotationSet]] = relationship(
        "ResearchPhaseAnnotationSet",
        back_populates="video",
        cascade="all, delete-orphan",
    )
    skill_assessments: Mapped[list[ResearchSkillAssessment]] = relationship(
        "ResearchSkillAssessment",
        back_populates="video",
        cascade="all, delete-orphan",
    )


Index("ix_research_videos_source_video_id", ResearchVideo.source_video_id)
Index("ix_research_videos_source_trim_processing", ResearchVideo.source_video_id, ResearchVideo.trim_start_frame, ResearchVideo.trim_end_frame_exclusive, ResearchVideo.status)
Index("ix_research_videos_hidden_from_video_list", ResearchVideo.hidden_from_video_list)


class ResearchVideoFrame(Base):
    __tablename__ = "research_video_frames"
    __table_args__ = (
        UniqueConstraint("video_id", "frame_index", name="uq_research_video_frames_video_frame"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("research_videos.id", ondelete="CASCADE"), nullable=False)
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
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

    video: Mapped[ResearchVideo] = relationship(back_populates="frames")
    annotations: Mapped[list[ResearchVideoAnnotation]] = relationship(
        back_populates="frame",
        cascade="all, delete-orphan",
    )


class ResearchVideoLabel(Base):
    __tablename__ = "research_video_labels"
    __table_args__ = (
        UniqueConstraint("video_id", "name", name="uq_research_video_labels_video_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("research_videos.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    color: Mapped[str] = mapped_column(String(16), nullable=False, default="#16a34a")
    shape_type: Mapped[str] = mapped_column(String(32), nullable=False, default="polygon")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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

    video: Mapped[ResearchVideo] = relationship(back_populates="labels")
    annotations: Mapped[list[ResearchVideoAnnotation]] = relationship(back_populates="label")


class ResearchVideoAnnotation(Base):
    __tablename__ = "research_video_annotations"
    __table_args__ = (
        CheckConstraint(
            "shape_type IN ('rectangle', 'polygon', 'point')",
            name="ck_research_video_annotations_shape_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("research_videos.id", ondelete="CASCADE"), nullable=False)
    frame_id: Mapped[int] = mapped_column(ForeignKey("research_video_frames.id", ondelete="CASCADE"), nullable=False)
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    label_id: Mapped[int] = mapped_column(
        ForeignKey("research_video_labels.id", ondelete="RESTRICT"),
        nullable=False,
    )
    shape_type: Mapped[str] = mapped_column(String(32), nullable=False)
    points: Mapped[list[dict[str, float]] | list[list[float]]] = mapped_column(JSON, nullable=False)
    attributes: Mapped[dict | None] = mapped_column(JSON)
    visible: Mapped[bool] = mapped_column(nullable=False, default=True)
    z_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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

    video: Mapped[ResearchVideo] = relationship(back_populates="annotations")
    frame: Mapped[ResearchVideoFrame] = relationship(back_populates="annotations")
    label: Mapped[ResearchVideoLabel] = relationship(back_populates="annotations")
