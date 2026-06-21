from typing import Literal

from pydantic import BaseModel, Field


Point = list[float]
ShapeType = Literal["rectangle", "polygon", "point"]


class LabelRead(BaseModel):
    id: int
    name: str
    color: str
    shape_type: ShapeType = "polygon"
    sort_order: int = 0

    model_config = {"from_attributes": True}


class JobImageRead(BaseModel):
    id: int
    filename: str
    width: int | None
    height: int | None
    frame_index: int | None
    image_url: str
    thumbnail_url: str


class AnnotationRead(BaseModel):
    id: int
    image_id: int
    label_id: int
    shape_type: ShapeType
    points: list[Point]
    attributes: dict | None = None

    model_config = {"from_attributes": True}


class AnnotationWrite(BaseModel):
    label_id: int
    shape_type: ShapeType
    points: list[Point] = Field(min_length=1)
    attributes: dict | None = None


class AnnotationSaveRequest(BaseModel):
    annotations: list[AnnotationWrite]


class JobDetailRead(BaseModel):
    id: int
    project_id: int | None
    name: str
    status: str
    task_id: int | None = None
    images: list[JobImageRead]
    labels: list[LabelRead]
    annotations: list[AnnotationRead]
