from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ResearchPhaseProtocolStatus = Literal["draft", "active", "archived"]
ResearchPhaseLabelMappingProfileStatus = Literal["draft", "published", "archived"]
ResearchPhaseAnnotationSetStatus = Literal["draft", "submitted", "reviewed", "locked"]
ResearchPhaseSegmentSource = Literal["manual", "model_suggestion", "model_corrected", "imported"]
ResearchPhaseMutationAction = Literal[
    "created",
    "filled_gaps",
    "transitioned",
    "closed",
    "updated",
    "unchanged",
    "deleted",
    "split",
    "merged",
]
ResearchPhaseStatusMutationAction = Literal["submitted", "reopened"]
ResearchPhaseValidationSeverity = Literal["error", "warning", "info"]
ResearchPhaseGapType = Literal["leading", "internal", "trailing"]
ResearchPhaseValidationIssueType = Literal[
    "no_segments",
    "open_segment",
    "overlap",
    "gap",
    "zero_length",
    "out_of_bounds",
    "inactive_label",
    "adjacent_same_label",
    "unusual_order",
    "very_short_segment",
    "video_end_not_covered",
    "duplicate_start",
]


class ResearchPhaseLabelResponse(BaseModel):
    id: int
    protocol_id: int
    key: str
    name: str
    color: str
    display_order: int
    shortcut: str | None = None
    description: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}


class ResearchPhaseProtocolSummary(BaseModel):
    id: int
    name: str
    version: int
    description: str | None = None
    status: ResearchPhaseProtocolStatus
    is_default: bool
    label_count: int = 0

    model_config = {"from_attributes": True}


class ResearchPhaseProtocolDetail(ResearchPhaseProtocolSummary):
    labels: list[ResearchPhaseLabelResponse] = Field(default_factory=list)


class ResearchPhaseLabelMappingSourceLabelResponse(BaseModel):
    id: int
    key: str
    name: str
    color: str
    display_order: int

    model_config = {"from_attributes": True}


class ResearchPhaseLabelMappingTargetResponse(BaseModel):
    id: int
    profile_id: int
    key: str
    name: str
    color: str
    order_index: int
    source_labels: list[ResearchPhaseLabelMappingSourceLabelResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ResearchPhaseLabelMappingProfileSummary(BaseModel):
    id: int
    protocol_id: int
    name: str
    description: str | None = None
    version: int
    status: ResearchPhaseLabelMappingProfileStatus
    created_by_id: int | None = None
    created_at: datetime
    updated_at: datetime
    source_label_count: int = 0
    target_count: int = 0
    merged_group_count: int = 0
    unmapped_label_count: int = 0

    model_config = {"from_attributes": True}


class ResearchPhaseLabelMappingProfileDetail(ResearchPhaseLabelMappingProfileSummary):
    targets: list[ResearchPhaseLabelMappingTargetResponse] = Field(default_factory=list)


class CreateResearchPhaseLabelMappingProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    version: int = Field(default=1, ge=1)
    created_by_id: int | None = None
    initialize_identity_mapping: bool = True


class UpdateResearchPhaseLabelMappingProfileRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)


class MergeResearchPhaseMappingClassesRequest(BaseModel):
    source_label_ids: list[int] = Field(min_length=2)
    target_key: str = Field(min_length=1, max_length=120)
    target_name: str = Field(min_length=1, max_length=255)
    target_color: str = Field(min_length=1, max_length=16)


class UnmergeResearchPhaseMappingTargetRequest(BaseModel):
    target_id: int


class DuplicateResearchPhaseLabelMappingProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)


class ResearchPhaseSegmentPhaseLabelResponse(BaseModel):
    id: int
    key: str
    name: str
    color: str

    model_config = {"from_attributes": True}


class ResearchPhaseSegmentResponse(BaseModel):
    id: int
    annotation_set_id: int
    phase_label_id: int
    start_frame: int
    end_frame_exclusive: int | None = None
    source: ResearchPhaseSegmentSource
    confidence: float | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    phase_label: ResearchPhaseSegmentPhaseLabelResponse

    model_config = {"from_attributes": True}


class ResearchPhaseAnnotationSetSummary(BaseModel):
    id: int
    video_id: int
    protocol_id: int
    annotator_id: int
    status: ResearchPhaseAnnotationSetStatus
    revision: int
    submitted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    protocol_name: str
    protocol_version: int
    annotator_username: str
    segment_count: int = 0
    has_open_segment: bool = False

    model_config = {"from_attributes": True}


class ResearchPhaseAnnotationSetDetail(ResearchPhaseAnnotationSetSummary):
    protocol: ResearchPhaseProtocolDetail
    segments: list[ResearchPhaseSegmentResponse] = Field(default_factory=list)


class CreateResearchPhaseAnnotationSetRequest(BaseModel):
    protocol_id: int
    username: str = Field(max_length=255)


class CreateResearchPhaseAnnotationSetResponse(BaseModel):
    created: bool
    annotation_set: ResearchPhaseAnnotationSetDetail


class CreateResearchPhaseSegmentRequest(BaseModel):
    phase_label_id: int
    start_frame: int
    end_frame_exclusive: int | None = None
    source: ResearchPhaseSegmentSource = "manual"
    confidence: float | None = None
    notes: str | None = Field(default=None, max_length=4000)
    expected_revision: int = Field(ge=1)


class TransitionResearchPhaseRequest(BaseModel):
    phase_label_id: int
    current_frame: int
    expected_revision: int = Field(ge=1)


class CloseActivePhaseSegmentRequest(BaseModel):
    end_frame_exclusive: int
    expected_revision: int = Field(ge=1)


class UpdateResearchPhaseSegmentRequest(BaseModel):
    phase_label_id: int | None = None
    start_frame: int | None = None
    end_frame_exclusive: int | None = None
    clear_end_frame: bool = False
    source: ResearchPhaseSegmentSource | None = None
    confidence: float | None = None
    clear_confidence: bool = False
    notes: str | None = Field(default=None, max_length=4000)
    clear_notes: bool = False
    expected_revision: int = Field(ge=1)


class SplitResearchPhaseSegmentRequest(BaseModel):
    split_frame: int
    expected_revision: int = Field(ge=1)


class MergeResearchPhaseSegmentsRequest(BaseModel):
    left_segment_id: int
    right_segment_id: int
    expected_revision: int = Field(ge=1)


class FillResearchPhaseGapsRequest(BaseModel):
    phase_label_id: int
    expected_revision: int = Field(ge=1)


class ResearchPhaseGapResponse(BaseModel):
    start_frame: int
    end_frame_exclusive: int
    frame_count: int
    gap_type: ResearchPhaseGapType


class ResearchPhaseGapFillPreviewResponse(BaseModel):
    annotation_set_id: int
    current_revision: int
    phase_label_id: int
    phase_label_name: str
    video_frame_count: int
    gap_count: int
    total_gap_frames: int
    total_gap_duration_ms: int | None = None
    leading_gap_count: int
    internal_gap_count: int
    trailing_gap_count: int
    gaps: list[ResearchPhaseGapResponse] = Field(default_factory=list)
    truncated: bool = False


class SubmitResearchPhaseAnnotationSetRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    confirm_warnings: bool = False


class ReopenResearchPhaseAnnotationSetRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class ResearchPhaseMutationResponse(BaseModel):
    action: ResearchPhaseMutationAction
    annotation_set: ResearchPhaseAnnotationSetDetail
    changed_segment_ids: list[int] = Field(default_factory=list)
    created_segment_ids: list[int] = Field(default_factory=list)
    deleted_segment_ids: list[int] = Field(default_factory=list)


class ResearchPhaseValidationIssue(BaseModel):
    issue_type: ResearchPhaseValidationIssueType
    severity: ResearchPhaseValidationSeverity
    message: str
    segment_id: int | None = None
    related_segment_id: int | None = None
    frame_start: int | None = None
    frame_end_exclusive: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ResearchPhaseValidationIssueCounts(BaseModel):
    error: int
    warning: int
    info: int


class ResearchPhaseValidationResponse(BaseModel):
    annotation_set_id: int
    video_id: int
    revision: int
    status: ResearchPhaseAnnotationSetStatus
    frame_count: int
    segment_count: int
    closed_segment_count: int
    open_segment_count: int
    closed_covered_frame_count: int
    closed_coverage_percent: float
    issue_counts: ResearchPhaseValidationIssueCounts
    issues: list[ResearchPhaseValidationIssue] = Field(default_factory=list)
    is_valid: bool
    can_submit: bool
    requires_warning_confirmation: bool


class ResearchPhaseStatusMutationResponse(BaseModel):
    action: ResearchPhaseStatusMutationAction
    annotation_set: ResearchPhaseAnnotationSetDetail
    validation: ResearchPhaseValidationResponse | None = None
