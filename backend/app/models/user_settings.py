from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    edge_snap_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    default_tool: Mapped[str] = mapped_column(String(32), nullable=False, default="sam2")
    add_polygon_vertex_shortcut: Mapped[str] = mapped_column(String(32), nullable=False, default="shift")
    delete_polygon_vertex_shortcut: Mapped[str] = mapped_column(String(32), nullable=False, default="alt")
    pan_modifier_shortcut: Mapped[str] = mapped_column(String(32), nullable=False, default="ctrl")
    polygon_confirm_point_shortcut: Mapped[str] = mapped_column(String(32), nullable=False, default="space")
    sam_result_edge_snap_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sam_result_edge_snap_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    sam_accept_next_tool: Mapped[str] = mapped_column(String(32), nullable=False, default="keep_current")
    remember_last_frame_per_job: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    keep_view_transform_on_frame_switch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sam2_default_model: Mapped[str] = mapped_column(String(64), nullable=False, default="sam2_hiera_large")
    sam2_default_multimask_output: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sam2_default_show_prompt_points: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sam2_default_candidate: Mapped[str] = mapped_column(String(8), nullable=False, default="best")
    sam2_default_polygon_epsilon: Mapped[float] = mapped_column(Float, nullable=False, default=0.002)
    sam2_default_mask_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sam2_default_min_mask_area: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    sam2_default_max_hole_area: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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

    user: Mapped[User] = relationship(back_populates="settings")
