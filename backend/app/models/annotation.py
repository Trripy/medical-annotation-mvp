from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.image import Image
    from app.models.job import Job
    from app.models.label import Label
    from app.models.user import User


class Annotation(Base):
    __tablename__ = "annotations"
    __table_args__ = (
        CheckConstraint(
            "shape_type IN ('rectangle', 'polygon', 'point')",
            name="ck_annotations_shape_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), nullable=False)
    label_id: Mapped[int] = mapped_column(ForeignKey("labels.id", ondelete="RESTRICT"), nullable=False)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    shape_type: Mapped[str] = mapped_column(String(32), nullable=False)
    points: Mapped[list[dict[str, float]] | list[list[float]]] = mapped_column(JSON, nullable=False)
    attributes: Mapped[dict | None] = mapped_column(JSON)
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

    image: Mapped[Image] = relationship(back_populates="annotations")
    label: Mapped[Label] = relationship(back_populates="annotations")
    job: Mapped[Job | None] = relationship(back_populates="annotations")
    created_by: Mapped[User | None] = relationship(back_populates="annotations")
