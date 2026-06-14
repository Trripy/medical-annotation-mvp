from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.annotation import Annotation
    from app.models.image import Image
    from app.models.label import Label
    from app.models.project import Project
    from app.models.task import Task
    from app.models.user import User


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Untitled Job")
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
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

    project: Mapped[Project | None] = relationship(back_populates="jobs")
    task: Mapped[Task | None] = relationship(back_populates="jobs")
    assignee: Mapped[User | None] = relationship(back_populates="assigned_jobs")
    annotations: Mapped[list[Annotation]] = relationship(back_populates="job")
    images: Mapped[list[Image]] = relationship(back_populates="job")
    labels: Mapped[list[Label]] = relationship(back_populates="job", cascade="all, delete-orphan")
