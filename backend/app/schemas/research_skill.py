from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ResearchSkillRubricStatus = Literal["draft", "active", "archived"]
ResearchSkillAssessmentStatus = Literal["draft", "submitted", "reviewed", "locked"]
ResearchSkillCriterionScope = Literal["overall", "phase"]
ResearchSkillScoreType = Literal["integer_scale", "number", "single_choice", "boolean", "text"]
ResearchSkillTargetType = Literal["overall", "phase_segment"]
ResearchSkillMutationAction = Literal[
    "created",
    "updated",
    "deleted",
    "unchanged",
    "evidence_created",
    "evidence_updated",
    "evidence_deleted",
]
ResearchSkillStatusMutationAction = Literal["submitted", "reopened"]
ResearchSkillValidationSeverity = Literal["error", "warning", "info"]
ResearchSkillValidationIssueType = Literal[
    "missing_required_score",
    "invalid_value",
    "na_not_allowed",
    "phase_score_without_segment",
    "segment_not_in_selected_phase_set",
    "criterion_not_applicable",
    "assessment_phase_set_missing",
    "assessment_phase_set_draft",
    "rubric_not_active",
    "inactive_criterion",
    "evidence_out_of_bounds",
    "incomplete_phase_criteria",
]


class ResearchSkillPhaseLabelResponse(BaseModel):
    id: int
    key: str
    name: str
    color: str

    model_config = {"from_attributes": True}


class ResearchSkillCriterionResponse(BaseModel):
    id: int
    rubric_id: int
    key: str
    name: str
    description: str | None = None
    scope: ResearchSkillCriterionScope
    score_type: ResearchSkillScoreType
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    options_json: list[dict[str, Any]] | None = None
    required: bool
    allow_na: bool
    weight: float | None = None
    display_order: int
    is_active: bool
    phase_label_ids: list[int] = Field(default_factory=list)
    phase_labels: list[ResearchSkillPhaseLabelResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ResearchSkillRubricSummary(BaseModel):
    id: int
    name: str
    version: int
    description: str | None = None
    status: ResearchSkillRubricStatus
    phase_protocol_id: int | None = None
    created_by_id: int | None = None
    criterion_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ResearchSkillRubricDetail(ResearchSkillRubricSummary):
    criteria: list[ResearchSkillCriterionResponse] = Field(default_factory=list)


class CreateResearchSkillRubricRequest(BaseModel):
    name: str = Field(max_length=255)
    version: int = Field(default=1, ge=1)
    description: str | None = None
    phase_protocol_id: int | None = None
    username: str | None = Field(default=None, max_length=255)


class UpdateResearchSkillRubricRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    phase_protocol_id: int | None = None
    clear_phase_protocol: bool = False


class CloneResearchSkillRubricRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None


class CreateResearchSkillCriterionRequest(BaseModel):
    key: str = Field(max_length=120)
    name: str = Field(max_length=255)
    description: str | None = None
    scope: ResearchSkillCriterionScope
    score_type: ResearchSkillScoreType
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    options_json: list[dict[str, Any]] | None = None
    required: bool = False
    allow_na: bool = False
    weight: float | None = None
    display_order: int = Field(ge=0)
    is_active: bool = True
    phase_label_ids: list[int] = Field(default_factory=list)


class UpdateResearchSkillCriterionRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    options_json: list[dict[str, Any]] | None = None
    required: bool | None = None
    allow_na: bool | None = None
    weight: float | None = None
    clear_weight: bool = False
    display_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    phase_label_ids: list[int] | None = None


class ActivateResearchSkillRubricResponse(BaseModel):
    rubric: ResearchSkillRubricDetail


class ArchiveResearchSkillRubricResponse(BaseModel):
    rubric: ResearchSkillRubricDetail


class ResearchSkillVideoSummary(BaseModel):
    id: int
    name: str
    fps: float | None = None
    frame_count: int
    duration_ms: int | None = None


class ResearchSkillPhaseSegmentSummary(BaseModel):
    id: int
    phase_label_id: int
    phase_key: str
    phase_name: str
    start_frame: int
    end_frame_exclusive: int | None = None


class ResearchSkillPhaseAnnotationSetSummary(BaseModel):
    id: int
    protocol_id: int
    status: str
    revision: int
    segments: list[ResearchSkillPhaseSegmentSummary] = Field(default_factory=list)


class ResearchSkillEvidenceResponse(BaseModel):
    id: int
    skill_score_id: int
    start_frame: int
    end_frame_exclusive: int | None = None
    comment: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ResearchSkillScoreResponse(BaseModel):
    id: int
    assessment_id: int
    criterion_id: int
    criterion_key: str
    criterion_name: str
    scope: ResearchSkillCriterionScope
    score_type: ResearchSkillScoreType
    target_key: str
    phase_segment_id: int | None = None
    value: Any | None = None
    is_na: bool
    comment: str | None = None
    evidence: list[ResearchSkillEvidenceResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ResearchSkillCompletionResponse(BaseModel):
    required_total: int
    required_completed: int
    overall_required_total: int
    overall_required_completed: int
    phase_required_total: int
    phase_required_completed: int
    completion_percent: float


class ResearchSkillAssessmentSummary(BaseModel):
    id: int
    video_id: int
    rubric_id: int
    rater_id: int
    phase_annotation_set_id: int | None = None
    status: ResearchSkillAssessmentStatus
    revision: int
    overall_comment: str | None = None
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    locked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    rubric_name: str
    rubric_version: int
    rater_username: str
    score_count: int = 0

    model_config = {"from_attributes": True}


class ResearchSkillAssessmentDetail(ResearchSkillAssessmentSummary):
    video: ResearchSkillVideoSummary
    rubric: ResearchSkillRubricDetail
    phase_annotation_set: ResearchSkillPhaseAnnotationSetSummary | None = None
    scores: list[ResearchSkillScoreResponse] = Field(default_factory=list)
    completion: ResearchSkillCompletionResponse


class CreateResearchSkillAssessmentRequest(BaseModel):
    rubric_id: int
    username: str = Field(max_length=255)
    phase_annotation_set_id: int | None = None


class CreateResearchSkillAssessmentResponse(BaseModel):
    created: bool
    assessment: ResearchSkillAssessmentDetail


class UpdateResearchSkillAssessmentRequest(BaseModel):
    overall_comment: str | None = Field(default=None, max_length=10000)
    clear_overall_comment: bool = False
    phase_annotation_set_id: int | None = None
    clear_phase_annotation_set: bool = False
    expected_revision: int = Field(ge=1)


class UpsertResearchSkillScoreRequest(BaseModel):
    target_type: ResearchSkillTargetType
    phase_segment_id: int | None = None
    value: Any | None = None
    is_na: bool = False
    comment: str | None = Field(default=None, max_length=10000)
    clear_comment: bool = False
    expected_revision: int = Field(ge=1)


class CreateResearchSkillEvidenceRequest(BaseModel):
    start_frame: int
    end_frame_exclusive: int | None = None
    comment: str | None = Field(default=None, max_length=5000)
    expected_revision: int = Field(ge=1)


class UpdateResearchSkillEvidenceRequest(BaseModel):
    start_frame: int | None = None
    end_frame_exclusive: int | None = None
    clear_end_frame: bool = False
    comment: str | None = Field(default=None, max_length=5000)
    clear_comment: bool = False
    expected_revision: int = Field(ge=1)


class ResearchSkillMutationResponse(BaseModel):
    action: ResearchSkillMutationAction
    assessment: ResearchSkillAssessmentDetail
    changed_score_ids: list[int] = Field(default_factory=list)
    created_score_ids: list[int] = Field(default_factory=list)
    deleted_score_ids: list[int] = Field(default_factory=list)
    changed_evidence_ids: list[int] = Field(default_factory=list)
    created_evidence_ids: list[int] = Field(default_factory=list)
    deleted_evidence_ids: list[int] = Field(default_factory=list)


class ResearchSkillValidationIssue(BaseModel):
    issue_type: ResearchSkillValidationIssueType
    severity: ResearchSkillValidationSeverity
    message: str
    criterion_id: int | None = None
    score_id: int | None = None
    phase_segment_id: int | None = None
    evidence_id: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ResearchSkillValidationIssueCounts(BaseModel):
    error: int
    warning: int
    info: int


class ResearchSkillValidationResponse(BaseModel):
    assessment_id: int
    revision: int
    status: ResearchSkillAssessmentStatus
    required_total: int
    required_completed: int
    completion_percent: float
    issue_counts: ResearchSkillValidationIssueCounts
    issues: list[ResearchSkillValidationIssue] = Field(default_factory=list)
    is_valid: bool
    can_submit: bool
    requires_warning_confirmation: bool


class SubmitResearchSkillAssessmentRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    confirm_warnings: bool = False


class ReopenResearchSkillAssessmentRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class ResearchSkillStatusMutationResponse(BaseModel):
    action: ResearchSkillStatusMutationAction
    assessment: ResearchSkillAssessmentDetail
    validation: ResearchSkillValidationResponse | None = None
