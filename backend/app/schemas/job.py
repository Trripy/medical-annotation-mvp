from typing import Literal

from pydantic import BaseModel, Field, field_validator


ShapeType = Literal["rectangle", "polygon", "point"]
ImportFormat = Literal["auto", "labelme", "coco", "cvat", "yolo", "mask", "voc", "via", "supervisely"]
ImportMode = Literal["append", "replace_matched_images", "replace_all_job"]
MissingLabelPolicy = Literal["auto_create", "skip"]
LabelDeleteStrategy = Literal["reassign", "move_to_undefined", "delete_annotations"]
ExportScope = Literal["all", "annotated_only"]


class JobLabelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    shape_type: ShapeType = "polygon"
    color: str = Field(default="#22c55e", max_length=16)


class JobLabelPayload(BaseModel):
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


class JobLabelRead(BaseModel):
    id: int
    name: str
    color: str
    shape_type: ShapeType = "polygon"
    sort_order: int = 0
    annotation_count: int = 0

    model_config = {"from_attributes": True}


class JobLabelUsageRead(BaseModel):
    label_id: int
    label_name: str
    annotation_count: int
    frame_count: int


class JobLabelDeleteRequest(BaseModel):
    strategy: LabelDeleteStrategy | None = None
    target_label_id: int | None = None


class JobLabelDeleteResponse(BaseModel):
    deleted_label_id: int
    strategy: LabelDeleteStrategy | None = None
    affected_annotations: int
    target_label: str | None = None


class JobRead(BaseModel):
    id: int
    project_id: int | None
    project_name: str | None
    name: str
    status: str
    task_id: int | None = None
    frames: int
    annotated_images_count: int = 0
    thumbnail_url: str | None


class JobImportRequest(BaseModel):
    format: ImportFormat = "auto"
    import_mode: ImportMode = "append"
    missing_label_policy: MissingLabelPolicy = "auto_create"


class ImportSkippedItemRead(BaseModel):
    source: str
    reason: str


class CreatedLabelDetailRead(BaseModel):
    name: str
    color: str
    requested_color: str | None = None
    color_changed: bool = False
    reason: str | None = None


class JobImportResponse(BaseModel):
    job_id: int
    format_detected: str
    matched_images: int
    unmatched_items: int
    created_annotations: int
    created_labels: list[str]
    created_label_details: list[CreatedLabelDetailRead] = Field(default_factory=list)
    reassigned_conflicting_colors: int = 0
    skipped_items: list[ImportSkippedItemRead]
    errors: list[str]
