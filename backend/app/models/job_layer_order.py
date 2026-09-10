from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.job import Job
    from app.models.label import Label


class JobLayerOrderRule(Base):
    __tablename__ = "job_layer_order_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, nullable=False)
    auto_apply: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    job: Mapped[Job] = relationship(back_populates="layer_order_rule")
    items: Mapped[list[JobLayerOrderRuleItem]] = relationship(
        back_populates="rule", cascade="all, delete-orphan", order_by="JobLayerOrderRuleItem.position"
    )


class JobLayerOrderRuleItem(Base):
    __tablename__ = "job_layer_order_rule_items"
    __table_args__ = (
        UniqueConstraint("rule_id", "label_id", name="uq_job_layer_order_rule_items_rule_label"),
        UniqueConstraint("rule_id", "position", name="uq_job_layer_order_rule_items_rule_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("job_layer_order_rules.id", ondelete="CASCADE"), nullable=False)
    label_id: Mapped[int] = mapped_column(ForeignKey("labels.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    rule: Mapped[JobLayerOrderRule] = relationship(back_populates="items")
    label: Mapped[Label] = relationship()
