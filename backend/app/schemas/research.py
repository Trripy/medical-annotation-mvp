from typing import Literal

from pydantic import BaseModel, Field, field_validator


Point = list[float]
ShapeType = Literal["rectangle", "polygon", "point"]
ResearchVideoStatus = Literal["processing", "ready", "failed"]


class ResearchVideoLabelPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    color: str = Field(default="#22c55e", max_length=16)
    shape_type: ShapeType = "polygon"

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Label name is required")
        return normalized


class ResearchVideoLabelRead(BaseModel):
    id: int
    name: str
    color: str
    shape_type: ShapeType = "polygon"
    sort_order: int = 0
    annotation_count: int = 0

    model_config = {"from_attributes": True}


class ResearchVideoFrameRead(BaseModel):
    id: int
    frame_index: int
    timestamp_ms: int
    filename: str
    width: int | None
    height: int | None
    image_url: str

    model_config = {"from_attributes": True}


class ResearchVideoRead(BaseModel):
    id: int
    name: str
    original_filename: str
    width: int | None
    height: int | None
    fps: float | None
    frame_count: int
    duration_ms: int | None
    status: ResearchVideoStatus
    thumbnail_url: str | None
    created_at: str
    updated_at: str


class ResearchVideoDetailRead(ResearchVideoRead):
    file_url: str
    frames: list[ResearchVideoFrameRead]
    labels: list[ResearchVideoLabelRead]


class ResearchVideoWorkspaceRead(ResearchVideoRead):
    file_url: str
    labels: list[ResearchVideoLabelRead]


class ResearchVideoFramesPageRead(BaseModel):
    items: list[ResearchVideoFrameRead]
    offset: int
    limit: int
    total: int
    has_more: bool


class ResearchVideoAnnotationRead(BaseModel):
    id: int
    frame_id: int
    frame_index: int
    label_id: int
    shape_type: ShapeType
    points: list[Point]
    attributes: dict | None = None
    visible: bool = True

    model_config = {"from_attributes": True}


class ResearchVideoAnnotationWrite(BaseModel):
    label_id: int
    shape_type: ShapeType
    points: list[Point] = Field(min_length=1)
    attributes: dict | None = None
    visible: bool = True


class ResearchVideoAnnotationSaveRequest(BaseModel):
    annotations: list[ResearchVideoAnnotationWrite]


class ResearchVideoFrameAnnotationsRead(BaseModel):
    video_id: int
    frame_index: int
    annotations: list[ResearchVideoAnnotationRead]


class ResearchVideoUploadResponse(ResearchVideoRead):
    warnings: list[str] = Field(default_factory=list)
