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
    settings: Mapped[UserSettings | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
