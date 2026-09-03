from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


Point = list[float]
ShapeType = Literal["rectangle", "polygon", "point"]
ResearchVideoStatus = Literal["processing", "ready", "failed"]
ResearchVideoVisibility = Literal["visible", "hidden", "all"]
ResearchVideoHiddenReason = Literal["trimmed_source", "manual"]


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


class ResearchVideoPhaseSummaryRead(BaseModel):
    annotation_set_count: int = 0
    draft_count: int = 0
    submitted_count: int = 0
    latest_submitted_set_id: int | None = None
    latest_submitted_version: int | None = None
    latest_submitted_protocol_name: str | None = None
    latest_submitted_coverage_percent: float = 0.0
    latest_draft_set_id: int | None = None
    latest_draft_version: int | None = None
    latest_error_count: int = 0
    latest_warning_count: int = 0


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
    source_video_id: int | None = None
    origin_type: str = "uploaded"
    trim_start_frame: int | None = None
    trim_end_frame_exclusive: int | None = None
    hidden_from_video_list: bool = False
    hidden_at: str | None = None
    hidden_reason: str | None = None
    notes: str | None = None
    phase_summary: ResearchVideoPhaseSummaryRead = Field(default_factory=ResearchVideoPhaseSummaryRead)
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
    z_order: int = 0

    model_config = {"from_attributes": True}


class ResearchVideoAnnotationWrite(BaseModel):
    label_id: int
    shape_type: ShapeType
    points: list[Point] = Field(min_length=1)
    attributes: dict | None = None
    visible: bool = True
    z_order: int = Field(default=0, ge=0)


class ResearchVideoAnnotationSaveRequest(BaseModel):
    annotations: list[ResearchVideoAnnotationWrite]


class ResearchVideoFrameAnnotationsRead(BaseModel):
    video_id: int
    frame_index: int
    annotations: list[ResearchVideoAnnotationRead]


class ResearchVideoUploadResponse(ResearchVideoRead):
    warnings: list[str] = Field(default_factory=list)


class ResearchVideoTrimLinkedDataRead(BaseModel):
    frame_annotation_count: int = 0
    phase_annotation_set_count: int = 0
    phase_segment_count: int = 0
    skill_assessment_count: int = 0
    skill_evidence_count: int = 0


class ResearchVideoTrimInfoRead(BaseModel):
    video: ResearchVideoWorkspaceRead
    linked_data: ResearchVideoTrimLinkedDataRead
    minimum_keep_frames: int


class ResearchVideoTrimRequest(BaseModel):
    start_frame: int = Field(ge=0)
    end_frame_exclusive: int = Field(gt=0)
    display_name: str | None = Field(default=None, max_length=255)
    acknowledge_annotations_not_copied: bool = False
    hide_source_after_success: bool = Field(
        default=False,
        description=(
            "Hide the source video from the regular research video list after the trimmed video "
            "has been fully created and marked ready."
        ),
    )


class ResearchVideoTrimResponse(BaseModel):
    source_video_id: int
    trimmed_video_id: int
    status: ResearchVideoStatus
    source_video_hidden: bool = False
    warnings: list[str] = Field(default_factory=list)


class ResearchVideoNotesRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value if value.strip() else None


class ResearchVideoNotesResponse(BaseModel):
    video_id: int
    notes: str | None = None
    updated_at: str


class ResearchVideoVisibilityRequest(BaseModel):
    hidden_from_video_list: bool


class ResearchVideoVisibilityResponse(BaseModel):
    video_id: int
    hidden_from_video_list: bool
    hidden_at: str | None = None
    hidden_reason: str | None = None
    updated_at: str


class ResearchVideoVisibilityBulkItemRead(BaseModel):
    video_id: int
    display_name: str
    ready_derived_count: int = 0


class ResearchVideoVisibilityBulkPreviewRead(BaseModel):
    eligible_count: int = 0
    already_hidden_count: int = 0
    skipped_count: int = 0
    items: list[ResearchVideoVisibilityBulkItemRead] = Field(default_factory=list)


class ResearchVideoVisibilityBulkResultRead(BaseModel):
    affected_count: int = 0
    items: list[ResearchVideoVisibilityBulkItemRead] = Field(default_factory=list)


class ServerVideoImportRootRead(BaseModel):
    id: str
    name: str


class ServerVideoImportRootsRead(BaseModel):
    enabled: bool
    roots: list[ServerVideoImportRootRead] = Field(default_factory=list)


class ServerVideoDirectoryEntryRead(BaseModel):
    name: str
    relative_path: str


class ServerVideoFileEntryRead(BaseModel):
    name: str
    relative_path: str
    size_bytes: int
    modified_at: str | None = None
    extension: str


class ServerVideoBrowseRead(BaseModel):
    root_id: str
    relative_path: str
    parent_relative_path: str | None = None
    directories: list[ServerVideoDirectoryEntryRead]
    videos: list[ServerVideoFileEntryRead]
    truncated: bool = False


class ServerVideoImportFileRequest(BaseModel):
    root_id: str
    relative_path: str
    display_name: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=120)


class ServerVideoScanFolderRequest(BaseModel):
    root_id: str
    relative_path: str = ""
    recursive: bool = False


class ServerVideoScanFolderRead(BaseModel):
    root_id: str
    relative_path: str
    recursive: bool
    video_count: int
    total_size_bytes: int
    videos: list[ServerVideoFileEntryRead]
    unsupported_count: int
    unreadable_count: int
    truncated: bool


class ResearchVideoChecklistVideoRead(BaseModel):
    id: int
    display_name: str
    status: str
    duration_ms: int | None = None
    fps: float | None = None
    frame_count: int
    width: int | None = None
    height: int | None = None
    created_at: datetime
    thumbnail_url: str | None = None
    hidden_from_video_list: bool = False
    hidden_at: datetime | None = None
    hidden_reason: str | None = None
    notes: str | None = None


class ResearchVideoChecklistDerivedVideoRead(BaseModel):
    video_id: int
    display_name: str
    trim_start_frame: int | None = None
    trim_end_frame_exclusive: int | None = None
    created_at: datetime


class ResearchVideoChecklistTrimRead(BaseModel):
    origin_type: str
    is_trimmed: bool
    source_video_id: int | None = None
    source_video_display_name: str | None = None
    trim_start_frame: int | None = None
    trim_end_frame_exclusive: int | None = None
    trim_start_time_ms: int | None = None
    trim_end_time_ms: int | None = None
    kept_frame_count: int | None = None
    kept_duration_ms: int | None = None
    derived_video_count: int = 0
    derived_video_ids: list[int] = Field(default_factory=list)
    latest_derived_at: datetime | None = None
    derived_videos: list[ResearchVideoChecklistDerivedVideoRead] = Field(default_factory=list)


class ResearchVideoChecklistMappingProfileRead(BaseModel):
    id: int
    name: str
    version: int
    status: str
    key: str


class ResearchVideoChecklistAnnotationSetRead(BaseModel):
    annotation_set_id: int
    status: str
    version: int
    protocol_id: int
    protocol_name: str
    segment_count: int
    coverage_percent: float
    error_count: int
    warning_count: int
    updated_at: datetime
    submitted_at: datetime | None = None
    available_mapping_profiles: list[ResearchVideoChecklistMappingProfileRead] = Field(default_factory=list)


class ResearchVideoChecklistPhaseRead(BaseModel):
    annotation_set_count: int = 0
    draft_count: int = 0
    submitted_count: int = 0
    latest_annotation_set_id: int | None = None
    latest_status: str | None = None
    latest_version: int | None = None
    latest_protocol_id: int | None = None
    latest_protocol_name: str | None = None
    latest_segment_count: int = 0
    latest_coverage_percent: float = 0.0
    latest_error_count: int = 0
    latest_warning_count: int = 0
    latest_updated_at: datetime | None = None
    latest_submitted_at: datetime | None = None
    sets: list[ResearchVideoChecklistAnnotationSetRead] = Field(default_factory=list)


class ResearchVideoChecklistItemRead(BaseModel):
    video: ResearchVideoChecklistVideoRead
    trim: ResearchVideoChecklistTrimRead
    phase: ResearchVideoChecklistPhaseRead


class ResearchVideoChecklistStatsRead(BaseModel):
    total_videos: int = 0
    trimmed_videos: int = 0
    source_with_derivatives: int = 0
    phase_submitted: int = 0
    phase_not_started: int = 0


class ResearchVideoChecklistPageRead(BaseModel):
    items: list[ResearchVideoChecklistItemRead]
    page: int
    page_size: int
    total: int
    stats: ResearchVideoChecklistStatsRead = Field(default_factory=ResearchVideoChecklistStatsRead)


class ResearchVideoChecklistDefaultPhaseSelectionRead(BaseModel):
    video_id: int
    annotation_set_id: int
    status: str
    version: int
    submitted_at: datetime | None = None
    protocol_id: int
    protocol_name: str


class ResearchVideoBatchPhaseExportRequest(BaseModel):
    annotation_set_id: int
    mapping_profile_id: int | None = None


class ResearchVideoBatchExportItemRequest(BaseModel):
    video_id: int
    include_trim_info: bool = False
    phase_exports: list[ResearchVideoBatchPhaseExportRequest] = Field(default_factory=list)


class ResearchVideoBatchExportRequest(BaseModel):
    items: list[ResearchVideoBatchExportItemRequest] = Field(default_factory=list)
    include_summary_csv: bool = True
    batch_name: str | None = Field(default=None, max_length=255)


class ResearchVideoBatchExportInvalidItemRead(BaseModel):
    video_id: int | None = None
    annotation_set_id: int | None = None
    mapping_profile_id: int | None = None
    message: str


class ResearchVideoBatchExportPreviewRead(BaseModel):
    video_count: int
    trim_export_count: int
    phase_export_count: int
    original_phase_export_count: int = 0
    mapped_phase_export_count: int = 0
    archive_entry_count: int
    warnings: list[str] = Field(default_factory=list)
    invalid_items: list[ResearchVideoBatchExportInvalidItemRead] = Field(default_factory=list)
    suggested_filename: str
