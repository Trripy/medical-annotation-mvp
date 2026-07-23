from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.annotation import Annotation
    from app.models.job import Job
    from app.models.project import Project
    from app.models.research_phase import ResearchPhaseAnnotationSet, ResearchPhaseProtocol
    from app.models.research_skill import ResearchSkillAssessment, ResearchSkillRubric
    from app.models.user_settings import UserSettings


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
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

    projects: Mapped[list[Project]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    assigned_jobs: Mapped[list[Job]] = relationship(back_populates="assignee")
    annotations: Mapped[list[Annotation]] = relationship(back_populates="created_by")
    created_phase_protocols: Mapped[list[ResearchPhaseProtocol]] = relationship(
        "ResearchPhaseProtocol",
        back_populates="created_by",
    )
    phase_annotation_sets: Mapped[list[ResearchPhaseAnnotationSet]] = relationship(
        "ResearchPhaseAnnotationSet",
        back_populates="annotator",
    )
    created_skill_rubrics: Mapped[list[ResearchSkillRubric]] = relationship(
        "ResearchSkillRubric",
        back_populates="created_by",
    )
    skill_assessments: Mapped[list[ResearchSkillAssessment]] = relationship(
        "ResearchSkillAssessment",
        back_populates="rater",
    )
    settings: Mapped[UserSettings | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
