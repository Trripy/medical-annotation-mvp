from typing import Literal

from pydantic import BaseModel, Field


ShapeType = Literal["rectangle", "polygon", "point"]


class JobLabelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    shape_type: ShapeType = "polygon"
    color: str = Field(default="#22c55e", max_length=16)


class JobRead(BaseModel):
    id: int
    project_id: int | None
    project_name: str | None
    name: str
    status: str
    task_id: int | None = None
    frames: int
    thumbnail_url: str | None
