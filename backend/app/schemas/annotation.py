from typing import Literal

from pydantic import BaseModel, Field, model_validator


Point = list[float]
ShapeType = Literal["rectangle", "polygon", "point", "classification"]


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
    z_order: int = 0

    model_config = {"from_attributes": True}


class AnnotationWrite(BaseModel):
    label_id: int
    shape_type: ShapeType
    points: list[Point] = Field(default_factory=list)
    attributes: dict | None = None
    z_order: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_points_for_shape(self) -> "AnnotationWrite":
        for index, point in enumerate(self.points):
            if len(point) < 2:
                raise ValueError(f"Point at index {index} must contain x and y coordinates")

        minimum_points = {
            "point": 1,
            "rectangle": 2,
            "polygon": 3,
        }.get(self.shape_type)
        if minimum_points is not None and len(self.points) < minimum_points:
            raise ValueError(
                f"{self.shape_type} annotations require at least {minimum_points} point(s)"
            )

        return self


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
