from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ResearchPhaseAnnotationSet,
    ResearchPhaseLabel,
    ResearchPhaseProtocol,
    ResearchPhaseSegment,
    ResearchSkillAssessment,
    ResearchSkillCriterion,
    ResearchSkillCriterionPhaseLabel,
    ResearchSkillEvidence,
    ResearchSkillRubric,
    ResearchSkillScore,
    ResearchVideo,
    User,
)
from app.schemas.research_skill import (
    ActivateResearchSkillRubricResponse,
    ArchiveResearchSkillRubricResponse,
    CloneResearchSkillRubricRequest,
    CreateResearchSkillAssessmentRequest,
    CreateResearchSkillAssessmentResponse,
    CreateResearchSkillCriterionRequest,
    CreateResearchSkillEvidenceRequest,
    CreateResearchSkillRubricRequest,
    ReopenResearchSkillAssessmentRequest,
    ResearchSkillAssessmentDetail,
    ResearchSkillAssessmentSummary,
    ResearchSkillCompletionResponse,
    ResearchSkillCriterionResponse,
    ResearchSkillEvidenceResponse,
    ResearchSkillMutationResponse,
    ResearchSkillPhaseAnnotationSetSummary,
    ResearchSkillPhaseLabelResponse,
    ResearchSkillPhaseSegmentSummary,
    ResearchSkillRubricDetail,
    ResearchSkillRubricSummary,
    ResearchSkillScoreResponse,
    ResearchSkillStatusMutationResponse,
    SubmitResearchSkillAssessmentRequest,
    UpdateResearchSkillAssessmentRequest,
    UpdateResearchSkillCriterionRequest,
    UpdateResearchSkillEvidenceRequest,
    UpdateResearchSkillRubricRequest,
    UpsertResearchSkillScoreRequest,
)
from app.services.research_skill_validation_service import validate_skill_assessment

VALID_RUBRIC_STATUSES = {"draft", "active", "archived"}
VALID_SCOPES = {"overall", "phase"}
VALID_SCORE_TYPES = {"integer_scale", "number", "single_choice", "boolean", "text"}
REVISION_CONFLICT_DETAIL = "Skill assessment revision conflict."
TEXT_SCORE_MAX_LENGTH = 5000


def list_skill_rubrics(
    db: Session,
    status_filter: str | None = None,
    include_archived: bool = False,
) -> list[ResearchSkillRubricSummary]:
    normalized_status = _normalize_status_filter(status_filter)
    criteria_counts = (
        select(
            ResearchSkillCriterion.rubric_id.label("rubric_id"),
            func.count(ResearchSkillCriterion.id).label("criterion_count"),
        )
        .group_by(ResearchSkillCriterion.rubric_id)
        .subquery()
    )
    stmt = (
        select(
            ResearchSkillRubric.id,
            ResearchSkillRubric.name,
            ResearchSkillRubric.version,
            ResearchSkillRubric.description,
            ResearchSkillRubric.status,
            ResearchSkillRubric.phase_protocol_id,
            ResearchSkillRubric.created_by_id,
            ResearchSkillRubric.created_at,
            ResearchSkillRubric.updated_at,
            func.coalesce(criteria_counts.c.criterion_count, 0).label("criterion_count"),
        )
        .outerjoin(criteria_counts, criteria_counts.c.rubric_id == ResearchSkillRubric.id)
        .order_by(ResearchSkillRubric.name.asc(), ResearchSkillRubric.version.desc(), ResearchSkillRubric.id.asc())
    )
    if normalized_status is not None:
        stmt = stmt.where(ResearchSkillRubric.status == normalized_status)
    elif not include_archived:
        stmt = stmt.where(ResearchSkillRubric.status.in_(("draft", "active")))
    return [_rubric_summary_from_row(row) for row in db.execute(stmt).mappings().all()]


def get_skill_rubric(db: Session, rubric_id: int) -> ResearchSkillRubricDetail:
    return _rubric_detail_from_entity(_get_rubric_or_404(db, rubric_id))


def create_skill_rubric(db: Session, payload: CreateResearchSkillRubricRequest) -> ResearchSkillRubricDetail:
    name = _normalize_required_string(payload.name, "Rubric name cannot be empty.")
    created_by_id = None
    if payload.username is not None and payload.username.strip():
        created_by_id = _get_user_by_username(db, payload.username.strip()).id
    if payload.phase_protocol_id is not None:
        _get_phase_protocol_or_404(db, payload.phase_protocol_id)
    rubric = ResearchSkillRubric(
        name=name,
        version=payload.version,
        description=_normalize_optional_string(payload.description),
        status="draft",
        phase_protocol_id=payload.phase_protocol_id,
        created_by_id=created_by_id,
    )
    db.add(rubric)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill rubric name and version must be unique.")
    return get_skill_rubric(db, rubric.id)


def update_skill_rubric(
    db: Session,
    rubric_id: int,
    payload: UpdateResearchSkillRubricRequest,
) -> ResearchSkillRubricDetail:
    rubric = _get_rubric_or_404(db, rubric_id)
    _require_draft_rubric(rubric)
    if payload.name is not None:
        rubric.name = _normalize_required_string(payload.name, "Rubric name cannot be empty.")
    if payload.description is not None:
        rubric.description = _normalize_optional_string(payload.description)
    if payload.clear_phase_protocol:
        if any(criterion.scope == "phase" for criterion in rubric.criteria):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phase criteria require a phase protocol.")
        rubric.phase_protocol_id = None
    elif payload.phase_protocol_id is not None:
        _get_phase_protocol_or_404(db, payload.phase_protocol_id)
        rubric.phase_protocol_id = payload.phase_protocol_id
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill rubric name and version must be unique.")
    return get_skill_rubric(db, rubric.id)


def clone_skill_rubric(
    db: Session,
    rubric_id: int,
    payload: CloneResearchSkillRubricRequest,
) -> ResearchSkillRubricDetail:
    source = _get_rubric_or_404(db, rubric_id)
    name = _normalize_required_string(payload.name, "Rubric name cannot be empty.") if payload.name is not None else source.name
    next_version = (
        db.scalar(select(func.max(ResearchSkillRubric.version)).where(ResearchSkillRubric.name == name))
        or 0
    ) + 1
    cloned = ResearchSkillRubric(
        name=name,
        version=next_version,
        description=payload.description if payload.description is not None else source.description,
        status="draft",
        phase_protocol_id=source.phase_protocol_id,
        created_by_id=source.created_by_id,
    )
    db.add(cloned)
    db.flush()
    for criterion in _sorted_criteria(source.criteria):
        new_criterion = ResearchSkillCriterion(
            rubric_id=cloned.id,
            key=criterion.key,
            name=criterion.name,
            description=criterion.description,
            scope=criterion.scope,
            score_type=criterion.score_type,
            min_value=criterion.min_value,
            max_value=criterion.max_value,
            step=criterion.step,
            options_json=criterion.options_json,
            required=criterion.required,
            allow_na=criterion.allow_na,
            weight=criterion.weight,
            display_order=criterion.display_order,
            is_active=criterion.is_active,
        )
        db.add(new_criterion)
        db.flush()
        for link in criterion.phase_label_links:
            db.add(ResearchSkillCriterionPhaseLabel(criterion_id=new_criterion.id, phase_label_id=link.phase_label_id))
    db.commit()
    return get_skill_rubric(db, cloned.id)


def activate_skill_rubric(db: Session, rubric_id: int) -> ActivateResearchSkillRubricResponse:
    rubric = _get_rubric_or_404(db, rubric_id)
    if rubric.status == "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Archived skill rubrics cannot be activated.")
    if rubric.status != "draft":
        return ActivateResearchSkillRubricResponse(rubric=_rubric_detail_from_entity(rubric))
    _validate_rubric_configuration(rubric, require_active_criterion=True)
    rubric.status = "active"
    db.commit()
    return ActivateResearchSkillRubricResponse(rubric=get_skill_rubric(db, rubric.id))


def archive_skill_rubric(db: Session, rubric_id: int) -> ArchiveResearchSkillRubricResponse:
    rubric = _get_rubric_or_404(db, rubric_id)
    rubric.status = "archived"
    db.commit()
    return ArchiveResearchSkillRubricResponse(rubric=get_skill_rubric(db, rubric.id))


def create_skill_criterion(
    db: Session,
    rubric_id: int,
    payload: CreateResearchSkillCriterionRequest,
) -> ResearchSkillCriterionResponse:
    rubric = _get_rubric_or_404(db, rubric_id)
    _require_draft_rubric(rubric)
    data = payload.model_dump()
    phase_label_ids = data.pop("phase_label_ids")
    criterion = ResearchSkillCriterion(
        rubric_id=rubric.id,
        key=_normalize_required_string(data["key"], "Criterion key cannot be empty."),
        name=_normalize_required_string(data["name"], "Criterion name cannot be empty."),
        description=_normalize_optional_string(data["description"]),
        scope=data["scope"],
        score_type=data["score_type"],
        min_value=data["min_value"],
        max_value=data["max_value"],
        step=data["step"],
        options_json=data["options_json"],
        required=data["required"],
        allow_na=data["allow_na"],
        weight=data["weight"],
        display_order=data["display_order"],
        is_active=data["is_active"],
    )
    _validate_criterion_configuration(rubric, criterion, phase_label_ids)
    db.add(criterion)
    db.flush()
    _replace_criterion_phase_labels(db, criterion, phase_label_ids)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill criterion key and name must be unique within a rubric.")
    return _criterion_to_response(_get_criterion_or_404(db, criterion.id))


def update_skill_criterion(
    db: Session,
    criterion_id: int,
    payload: UpdateResearchSkillCriterionRequest,
) -> ResearchSkillCriterionResponse:
    criterion = _get_criterion_or_404(db, criterion_id)
    rubric = criterion.rubric
    _require_draft_rubric(rubric)
    if payload.name is not None:
        criterion.name = _normalize_required_string(payload.name, "Criterion name cannot be empty.")
    if payload.description is not None:
        criterion.description = _normalize_optional_string(payload.description)
    for field in ("min_value", "max_value", "step", "options_json", "required", "allow_na", "display_order", "is_active"):
        value = getattr(payload, field)
        if value is not None:
            setattr(criterion, field, value)
    if payload.clear_weight:
        criterion.weight = None
    elif payload.weight is not None:
        criterion.weight = payload.weight
    phase_label_ids = payload.phase_label_ids
    _validate_criterion_configuration(rubric, criterion, phase_label_ids)
    if phase_label_ids is not None:
        _replace_criterion_phase_labels(db, criterion, phase_label_ids)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill criterion key and name must be unique within a rubric.")
    return _criterion_to_response(_get_criterion_or_404(db, criterion.id))


def list_video_skill_assessments(db: Session, video_id: int) -> list[ResearchSkillAssessmentSummary]:
    _get_video_or_404(db, video_id)
    score_counts = (
        select(ResearchSkillScore.assessment_id.label("assessment_id"), func.count(ResearchSkillScore.id).label("score_count"))
        .group_by(ResearchSkillScore.assessment_id)
        .subquery()
    )
    stmt = (
        select(
            ResearchSkillAssessment.id,
            ResearchSkillAssessment.video_id,
            ResearchSkillAssessment.rubric_id,
            ResearchSkillAssessment.rater_id,
            ResearchSkillAssessment.phase_annotation_set_id,
            ResearchSkillAssessment.status,
            ResearchSkillAssessment.revision,
            ResearchSkillAssessment.overall_comment,
            ResearchSkillAssessment.submitted_at,
            ResearchSkillAssessment.reviewed_at,
            ResearchSkillAssessment.locked_at,
            ResearchSkillAssessment.created_at,
            ResearchSkillAssessment.updated_at,
            ResearchSkillRubric.name.label("rubric_name"),
            ResearchSkillRubric.version.label("rubric_version"),
            User.username.label("rater_username"),
            func.coalesce(score_counts.c.score_count, 0).label("score_count"),
        )
        .join(ResearchSkillRubric, ResearchSkillAssessment.rubric_id == ResearchSkillRubric.id)
        .join(User, ResearchSkillAssessment.rater_id == User.id)
        .outerjoin(score_counts, score_counts.c.assessment_id == ResearchSkillAssessment.id)
        .where(ResearchSkillAssessment.video_id == video_id)
        .order_by(ResearchSkillAssessment.updated_at.desc(), ResearchSkillAssessment.id.desc())
    )
    return [_assessment_summary_from_row(row) for row in db.execute(stmt).mappings().all()]


def get_or_create_skill_assessment(
    db: Session,
    video_id: int,
    payload: CreateResearchSkillAssessmentRequest,
) -> CreateResearchSkillAssessmentResponse:
    username = _normalize_username(payload.username)
    user = _get_user_by_username(db, username)
    video = _get_video_or_404(db, video_id)
    rubric = _get_rubric_or_404(db, payload.rubric_id)
    if rubric.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="New assessments can only use an active skill rubric.")
    phase_set = _validate_assessment_phase_set(db, video, rubric, payload.phase_annotation_set_id)
    existing = _get_assessment_by_unique_key(db, video_id=video.id, rubric_id=rubric.id, rater_id=user.id)
    if existing is not None:
        return CreateResearchSkillAssessmentResponse(created=False, assessment=get_skill_assessment(db, existing.id))
    assessment = ResearchSkillAssessment(
        video_id=video.id,
        rubric_id=rubric.id,
        rater_id=user.id,
        phase_annotation_set_id=phase_set.id if phase_set is not None else None,
        status="draft",
        revision=1,
    )
    db.add(assessment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _get_assessment_by_unique_key(db, video_id=video.id, rubric_id=rubric.id, rater_id=user.id)
        if existing is not None:
            return CreateResearchSkillAssessmentResponse(created=False, assessment=get_skill_assessment(db, existing.id))
        raise
    return CreateResearchSkillAssessmentResponse(created=True, assessment=get_skill_assessment(db, assessment.id))


def get_skill_assessment(db: Session, assessment_id: int) -> ResearchSkillAssessmentDetail:
    return _assessment_detail_from_entity(_get_assessment_or_404(db, assessment_id))


def update_skill_assessment(
    db: Session,
    assessment_id: int,
    payload: UpdateResearchSkillAssessmentRequest,
) -> ResearchSkillMutationResponse:
    assessment = _get_assessment_or_404(db, assessment_id)
    _require_draft_assessment(assessment)
    _ensure_assessment_revision_matches_current(assessment, payload.expected_revision)
    next_comment = assessment.overall_comment
    next_phase_set_id = assessment.phase_annotation_set_id
    if payload.clear_overall_comment:
        next_comment = None
    elif payload.overall_comment is not None:
        next_comment = _normalize_optional_string(payload.overall_comment)
    if payload.clear_phase_annotation_set:
        if any(score.phase_segment_id is not None for score in assessment.scores):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phase scores must be removed before clearing the phase annotation set.")
        next_phase_set_id = None
    elif payload.phase_annotation_set_id is not None:
        phase_set = _validate_assessment_phase_set(db, assessment.video, assessment.rubric, payload.phase_annotation_set_id)
        next_phase_set_id = phase_set.id if phase_set is not None else None
    if next_comment == assessment.overall_comment and next_phase_set_id == assessment.phase_annotation_set_id:
        return _build_mutation_response(db, action="unchanged", assessment_id=assessment.id)
    assessment.overall_comment = next_comment
    assessment.phase_annotation_set_id = next_phase_set_id
    try:
        db.flush()
        _claim_assessment_revision(db, assessment.id, payload.expected_revision)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return _build_mutation_response(db, action="updated", assessment_id=assessment.id)


def upsert_skill_score(
    db: Session,
    assessment_id: int,
    criterion_id: int,
    payload: UpsertResearchSkillScoreRequest,
) -> ResearchSkillMutationResponse:
    assessment = _get_assessment_or_404(db, assessment_id)
    _require_draft_assessment(assessment)
    _ensure_assessment_revision_matches_current(assessment, payload.expected_revision)
    criterion = _get_criterion_or_404(db, criterion_id)
    if criterion.rubric_id != assessment.rubric_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Skill criterion does not belong to the assessment rubric.")
    target_key, segment = _resolve_score_target(db, assessment, criterion, payload.target_type, payload.phase_segment_id)
    score = _get_score_by_unique_key(db, assessment.id, criterion.id, target_key)
    created = score is None
    submitted_fields = payload.model_fields_set
    value_submitted = "value" in submitted_fields
    is_na_submitted = "is_na" in submitted_fields
    comment_submitted = "comment" in submitted_fields
    if not created and not value_submitted and not is_na_submitted:
        value = score.value_json
        is_na = score.is_na
    else:
        is_na = payload.is_na
        value = _validate_score_value(criterion, payload.value, is_na)
    if not created and not payload.clear_comment and not comment_submitted:
        comment = score.comment
    else:
        comment = None if payload.clear_comment else _normalize_optional_string(payload.comment)
    if score is None:
        score = ResearchSkillScore(assessment_id=assessment.id, criterion_id=criterion.id, target_key=target_key)
        db.add(score)
    if (
        not created
        and score.phase_segment_id == (segment.id if segment is not None else None)
        and score.value_json == value
        and score.is_na == is_na
        and score.comment == comment
    ):
        return _build_mutation_response(db, action="unchanged", assessment_id=assessment.id)
    score.phase_segment_id = segment.id if segment is not None else None
    score.value_json = value
    score.is_na = is_na
    score.comment = comment
    try:
        db.flush()
        _claim_assessment_revision(db, assessment.id, payload.expected_revision)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return _build_mutation_response(
        db,
        action="created" if created else "updated",
        assessment_id=assessment.id,
        changed_score_ids=[] if created else [score.id],
        created_score_ids=[score.id] if created else [],
    )


def delete_skill_score(db: Session, score_id: int, expected_revision: int) -> ResearchSkillMutationResponse:
    score = _get_score_or_404(db, score_id)
    assessment = _get_assessment_or_404(db, score.assessment_id)
    _require_draft_assessment(assessment)
    _ensure_assessment_revision_matches_current(assessment, expected_revision)
    deleted_id = score.id
    db.delete(score)
    try:
        db.flush()
        _claim_assessment_revision(db, assessment.id, expected_revision)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return _build_mutation_response(db, action="deleted", assessment_id=assessment.id, deleted_score_ids=[deleted_id])


def create_skill_evidence(
    db: Session,
    score_id: int,
    payload: CreateResearchSkillEvidenceRequest,
) -> ResearchSkillMutationResponse:
    score = _get_score_or_404(db, score_id)
    assessment = _get_assessment_or_404(db, score.assessment_id)
    _require_draft_assessment(assessment)
    _ensure_assessment_revision_matches_current(assessment, payload.expected_revision)
    _validate_evidence_range(assessment.video, payload.start_frame, payload.end_frame_exclusive)
    evidence = ResearchSkillEvidence(
        skill_score_id=score.id,
        start_frame=payload.start_frame,
        end_frame_exclusive=payload.end_frame_exclusive,
        comment=_normalize_optional_string(payload.comment),
    )
    db.add(evidence)
    try:
        db.flush()
        _claim_assessment_revision(db, assessment.id, payload.expected_revision)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return _build_mutation_response(
        db,
        action="evidence_created",
        assessment_id=assessment.id,
        changed_score_ids=[score.id],
        created_evidence_ids=[evidence.id],
    )


def update_skill_evidence(
    db: Session,
    evidence_id: int,
    payload: UpdateResearchSkillEvidenceRequest,
) -> ResearchSkillMutationResponse:
    evidence = _get_evidence_or_404(db, evidence_id)
    assessment = _get_assessment_or_404(db, evidence.score.assessment_id)
    _require_draft_assessment(assessment)
    _ensure_assessment_revision_matches_current(assessment, payload.expected_revision)
    next_start = evidence.start_frame if payload.start_frame is None else payload.start_frame
    next_end = None if payload.clear_end_frame else (evidence.end_frame_exclusive if payload.end_frame_exclusive is None else payload.end_frame_exclusive)
    next_comment = None if payload.clear_comment else (evidence.comment if payload.comment is None else _normalize_optional_string(payload.comment))
    _validate_evidence_range(assessment.video, next_start, next_end)
    if next_start == evidence.start_frame and next_end == evidence.end_frame_exclusive and next_comment == evidence.comment:
        return _build_mutation_response(db, action="unchanged", assessment_id=assessment.id)
    evidence.start_frame = next_start
    evidence.end_frame_exclusive = next_end
    evidence.comment = next_comment
    try:
        db.flush()
        _claim_assessment_revision(db, assessment.id, payload.expected_revision)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return _build_mutation_response(
        db,
        action="evidence_updated",
        assessment_id=assessment.id,
        changed_score_ids=[evidence.skill_score_id],
        changed_evidence_ids=[evidence.id],
    )


def delete_skill_evidence(db: Session, evidence_id: int, expected_revision: int) -> ResearchSkillMutationResponse:
    evidence = _get_evidence_or_404(db, evidence_id)
    assessment = _get_assessment_or_404(db, evidence.score.assessment_id)
    _require_draft_assessment(assessment)
    _ensure_assessment_revision_matches_current(assessment, expected_revision)
    score_id = evidence.skill_score_id
    deleted_id = evidence.id
    db.delete(evidence)
    try:
        db.flush()
        _claim_assessment_revision(db, assessment.id, expected_revision)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return _build_mutation_response(
        db,
        action="evidence_deleted",
        assessment_id=assessment.id,
        changed_score_ids=[score_id],
        deleted_evidence_ids=[deleted_id],
    )


def submit_skill_assessment(
    db: Session,
    assessment_id: int,
    payload: SubmitResearchSkillAssessmentRequest,
) -> ResearchSkillStatusMutationResponse:
    assessment = _get_assessment_or_404(db, assessment_id)
    _ensure_assessment_revision_matches_current(assessment, payload.expected_revision)
    if assessment.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft skill assessments can be submitted.")
    validation = validate_skill_assessment(db, assessment_id)
    if validation.issue_counts.error > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Skill assessment has validation errors.", "validation": validation.model_dump(mode="json")},
        )
    if validation.issue_counts.warning > 0 and not payload.confirm_warnings:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Skill assessment has warnings that require confirmation.", "validation": validation.model_dump(mode="json")},
        )
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(ResearchSkillAssessment)
        .where(
            ResearchSkillAssessment.id == assessment_id,
            ResearchSkillAssessment.revision == payload.expected_revision,
            ResearchSkillAssessment.status == "draft",
        )
        .values(status="submitted", revision=ResearchSkillAssessment.revision + 1, submitted_at=now, updated_at=now)
    )
    if result.rowcount != 1:
        db.rollback()
        _raise_submit_conflict(db, assessment_id, payload.expected_revision)
    db.commit()
    return ResearchSkillStatusMutationResponse(
        action="submitted",
        assessment=get_skill_assessment(db, assessment_id),
        validation=validate_skill_assessment(db, assessment_id),
    )


def reopen_skill_assessment(
    db: Session,
    assessment_id: int,
    payload: ReopenResearchSkillAssessmentRequest,
) -> ResearchSkillStatusMutationResponse:
    assessment = _get_assessment_or_404(db, assessment_id)
    _ensure_assessment_revision_matches_current(assessment, payload.expected_revision)
    if assessment.status != "submitted":
        _raise_reopen_status_conflict(assessment.status)
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(ResearchSkillAssessment)
        .where(
            ResearchSkillAssessment.id == assessment_id,
            ResearchSkillAssessment.revision == payload.expected_revision,
            ResearchSkillAssessment.status == "submitted",
        )
        .values(status="draft", revision=ResearchSkillAssessment.revision + 1, submitted_at=None, updated_at=now)
    )
    if result.rowcount != 1:
        db.rollback()
        _raise_reopen_conflict(db, assessment_id, payload.expected_revision)
    db.commit()
    return ResearchSkillStatusMutationResponse(action="reopened", assessment=get_skill_assessment(db, assessment_id), validation=None)


def _get_assessment_or_404(db: Session, assessment_id: int) -> ResearchSkillAssessment:
    assessment = db.scalar(
        select(ResearchSkillAssessment)
        .where(ResearchSkillAssessment.id == assessment_id)
        .options(
            selectinload(ResearchSkillAssessment.video),
            selectinload(ResearchSkillAssessment.rater),
            selectinload(ResearchSkillAssessment.rubric)
            .selectinload(ResearchSkillRubric.criteria)
            .selectinload(ResearchSkillCriterion.phase_label_links)
            .selectinload(ResearchSkillCriterionPhaseLabel.phase_label),
            selectinload(ResearchSkillAssessment.phase_annotation_set)
            .selectinload(ResearchPhaseAnnotationSet.segments)
            .selectinload(ResearchPhaseSegment.phase_label),
            selectinload(ResearchSkillAssessment.scores).selectinload(ResearchSkillScore.criterion),
            selectinload(ResearchSkillAssessment.scores).selectinload(ResearchSkillScore.phase_segment).selectinload(ResearchPhaseSegment.phase_label),
            selectinload(ResearchSkillAssessment.scores).selectinload(ResearchSkillScore.evidence),
        )
    )
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill assessment not found.")
    return assessment


def _get_rubric_or_404(db: Session, rubric_id: int) -> ResearchSkillRubric:
    rubric = db.scalar(
        select(ResearchSkillRubric)
        .where(ResearchSkillRubric.id == rubric_id)
        .options(
            selectinload(ResearchSkillRubric.phase_protocol).selectinload(ResearchPhaseProtocol.labels),
            selectinload(ResearchSkillRubric.criteria)
            .selectinload(ResearchSkillCriterion.phase_label_links)
            .selectinload(ResearchSkillCriterionPhaseLabel.phase_label)
        )
    )
    if rubric is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill rubric not found.")
    return rubric


def _get_criterion_or_404(db: Session, criterion_id: int) -> ResearchSkillCriterion:
    criterion = db.scalar(
        select(ResearchSkillCriterion)
        .where(ResearchSkillCriterion.id == criterion_id)
        .options(
            selectinload(ResearchSkillCriterion.rubric)
            .selectinload(ResearchSkillRubric.phase_protocol)
            .selectinload(ResearchPhaseProtocol.labels),
            selectinload(ResearchSkillCriterion.rubric).selectinload(ResearchSkillRubric.criteria),
            selectinload(ResearchSkillCriterion.phase_label_links).selectinload(ResearchSkillCriterionPhaseLabel.phase_label),
        )
    )
    if criterion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill criterion not found.")
    return criterion


def _get_score_or_404(db: Session, score_id: int) -> ResearchSkillScore:
    score = db.scalar(
        select(ResearchSkillScore)
        .where(ResearchSkillScore.id == score_id)
        .options(selectinload(ResearchSkillScore.evidence), selectinload(ResearchSkillScore.criterion))
    )
    if score is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill score not found.")
    return score


def _get_evidence_or_404(db: Session, evidence_id: int) -> ResearchSkillEvidence:
    evidence = db.scalar(
        select(ResearchSkillEvidence)
        .where(ResearchSkillEvidence.id == evidence_id)
        .options(selectinload(ResearchSkillEvidence.score))
    )
    if evidence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill evidence not found.")
    return evidence


def _get_video_or_404(db: Session, video_id: int) -> ResearchVideo:
    video = db.get(ResearchVideo, video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research video not found.")
    return video


def _get_user_by_username(db: Session, username: str) -> User:
    user = db.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


def _get_phase_protocol_or_404(db: Session, protocol_id: int) -> ResearchPhaseProtocol:
    protocol = db.get(ResearchPhaseProtocol, protocol_id)
    if protocol is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phase protocol not found.")
    return protocol


def _get_phase_set_or_404(db: Session, phase_set_id: int) -> ResearchPhaseAnnotationSet:
    phase_set = db.scalar(
        select(ResearchPhaseAnnotationSet)
        .where(ResearchPhaseAnnotationSet.id == phase_set_id)
        .options(selectinload(ResearchPhaseAnnotationSet.segments).selectinload(ResearchPhaseSegment.phase_label))
    )
    if phase_set is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phase annotation set not found.")
    return phase_set


def _get_phase_segment_or_404(db: Session, segment_id: int) -> ResearchPhaseSegment:
    segment = db.scalar(select(ResearchPhaseSegment).where(ResearchPhaseSegment.id == segment_id).options(selectinload(ResearchPhaseSegment.phase_label)))
    if segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phase segment not found.")
    return segment


def _normalize_username(username: str) -> str:
    normalized = username.strip()
    if not normalized:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Username cannot be empty.")
    return normalized


def _normalize_required_string(value: str, message: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)
    return normalized


def _normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_status_filter(status_filter: str | None) -> str | None:
    if status_filter is None:
        return None
    normalized = status_filter.strip().lower()
    if normalized not in VALID_RUBRIC_STATUSES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid skill rubric status filter.")
    return normalized


def _require_draft_rubric(rubric: ResearchSkillRubric) -> None:
    if rubric.status == "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Active skill rubrics must be cloned before editing.")
    if rubric.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft skill rubrics can be modified.")


def _require_draft_assessment(assessment: ResearchSkillAssessment) -> None:
    if assessment.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft skill assessments can be modified.")


def _ensure_assessment_revision_matches_current(assessment: ResearchSkillAssessment, expected_revision: int) -> None:
    if assessment.revision != expected_revision:
        _raise_revision_conflict(assessment.revision)


def _raise_revision_conflict(current_revision: int | None) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"message": REVISION_CONFLICT_DETAIL, "current_revision": current_revision},
    )


def _claim_assessment_revision(db: Session, assessment_id: int, expected_revision: int) -> None:
    result = db.execute(
        update(ResearchSkillAssessment)
        .where(ResearchSkillAssessment.id == assessment_id, ResearchSkillAssessment.revision == expected_revision, ResearchSkillAssessment.status == "draft")
        .values(revision=ResearchSkillAssessment.revision + 1, updated_at=func.now())
    )
    if result.rowcount == 1:
        return
    current = db.get(ResearchSkillAssessment, assessment_id)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill assessment not found.")
    if current.revision != expected_revision:
        _raise_revision_conflict(current.revision)
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft skill assessments can be modified.")


def _raise_submit_conflict(db: Session, assessment_id: int, expected_revision: int) -> None:
    current = db.get(ResearchSkillAssessment, assessment_id)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill assessment not found.")
    if current.revision != expected_revision:
        _raise_revision_conflict(current.revision)
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft skill assessments can be submitted.")


def _raise_reopen_conflict(db: Session, assessment_id: int, expected_revision: int) -> None:
    current = db.get(ResearchSkillAssessment, assessment_id)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill assessment not found.")
    if current.revision != expected_revision:
        _raise_revision_conflict(current.revision)
    _raise_reopen_status_conflict(current.status)


def _raise_reopen_status_conflict(status_value: str) -> None:
    if status_value == "reviewed":
        detail = "Reviewed skill assessments cannot be reopened."
    elif status_value == "locked":
        detail = "Locked skill assessments cannot be reopened."
    else:
        detail = "Only submitted skill assessments can be reopened."
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _validate_assessment_phase_set(
    db: Session,
    video: ResearchVideo,
    rubric: ResearchSkillRubric,
    phase_set_id: int | None,
) -> ResearchPhaseAnnotationSet | None:
    if phase_set_id is None:
        return None
    if rubric.phase_protocol_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This skill rubric is not linked to a phase protocol.")
    phase_set = _get_phase_set_or_404(db, phase_set_id)
    if phase_set.video_id != video.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The selected phase annotation set does not belong to this video.")
    if phase_set.protocol_id != rubric.phase_protocol_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The selected phase annotation set uses a different phase protocol.")
    return phase_set


def _validate_criterion_configuration(
    rubric: ResearchSkillRubric,
    criterion: ResearchSkillCriterion,
    phase_label_ids: list[int] | None,
) -> None:
    if criterion.scope not in VALID_SCOPES or criterion.score_type not in VALID_SCORE_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid rubric configuration.")
    if criterion.weight is not None and criterion.weight < 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid rubric configuration.")
    label_ids = phase_label_ids if phase_label_ids is not None else [link.phase_label_id for link in criterion.phase_label_links]
    if criterion.scope == "overall" and label_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid rubric configuration.")
    if criterion.scope == "phase" and rubric.phase_protocol_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid rubric configuration.")
    if label_ids:
        labels = {label.id: label for label in rubric.phase_protocol.labels} if rubric.phase_protocol is not None else {}
        for label_id in label_ids:
            label = labels.get(label_id)
            if label is None:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid rubric configuration.")
    if criterion.score_type in {"integer_scale", "number"}:
        if criterion.min_value is None or criterion.max_value is None or criterion.step is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid rubric configuration.")
        if criterion.min_value >= criterion.max_value or criterion.step <= 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid rubric configuration.")
        if criterion.score_type == "integer_scale" and not all(float(value).is_integer() for value in (criterion.min_value, criterion.max_value, criterion.step)):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid rubric configuration.")
    elif criterion.score_type == "single_choice":
        _validate_single_choice_options(criterion.options_json)
    elif criterion.score_type in {"boolean", "text"}:
        if criterion.min_value is not None or criterion.max_value is not None or criterion.step is not None or criterion.options_json is not None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid rubric configuration.")


def _validate_rubric_configuration(rubric: ResearchSkillRubric, *, require_active_criterion: bool) -> None:
    active_criteria = [criterion for criterion in rubric.criteria if criterion.is_active]
    if require_active_criterion and not active_criteria:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid rubric configuration.")
    for criterion in rubric.criteria:
        _validate_criterion_configuration(rubric, criterion, None)


def _validate_single_choice_options(options: list[dict[str, Any]] | None) -> None:
    if not options or len(options) < 2:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid rubric configuration.")
    values: set[str] = set()
    for option in options:
        value = str(option.get("value", "")).strip()
        label = str(option.get("label", "")).strip()
        if not value or not label or value in values:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid rubric configuration.")
        values.add(value)


def _replace_criterion_phase_labels(
    db: Session,
    criterion: ResearchSkillCriterion,
    phase_label_ids: list[int],
) -> None:
    criterion.phase_label_links.clear()
    db.flush()
    for label_id in sorted(set(phase_label_ids)):
        criterion.phase_label_links.append(ResearchSkillCriterionPhaseLabel(criterion_id=criterion.id, phase_label_id=label_id))


def _resolve_score_target(
    db: Session,
    assessment: ResearchSkillAssessment,
    criterion: ResearchSkillCriterion,
    target_type: str,
    phase_segment_id: int | None,
) -> tuple[str, ResearchPhaseSegment | None]:
    if criterion.scope == "overall":
        if target_type != "overall" or phase_segment_id is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This criterion requires an overall score.")
        return "overall", None
    if target_type != "phase_segment" or phase_segment_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This criterion requires a phase segment score.")
    if assessment.phase_annotation_set_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This criterion requires a phase segment score.")
    segment = _get_phase_segment_or_404(db, phase_segment_id)
    if segment.annotation_set_id != assessment.phase_annotation_set_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This criterion does not apply to the selected phase segment.")
    applicable_label_ids = {link.phase_label_id for link in criterion.phase_label_links}
    if applicable_label_ids and segment.phase_label_id not in applicable_label_ids:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This criterion does not apply to the selected phase segment.")
    return f"segment:{segment.id}", segment


def _validate_score_value(criterion: ResearchSkillCriterion, value: Any, is_na: bool) -> Any | None:
    if is_na:
        if not criterion.allow_na:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="This criterion does not allow N/A.")
        if value is not None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid score value.")
        return None
    if value is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid score value.")
    if criterion.score_type == "integer_scale":
        if isinstance(value, bool) or not isinstance(value, int):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid score value.")
        _validate_numeric_bounds(float(value), criterion)
        return value
    if criterion.score_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid score value.")
        _validate_numeric_bounds(float(value), criterion)
        return value
    if criterion.score_type == "single_choice":
        allowed = {str(option["value"]) for option in (criterion.options_json or [])}
        if not isinstance(value, str) or value not in allowed:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid score value.")
        return value
    if criterion.score_type == "boolean":
        if not isinstance(value, bool):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid score value.")
        return value
    if criterion.score_type == "text":
        if not isinstance(value, str) or not value.strip() or len(value) > TEXT_SCORE_MAX_LENGTH:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid score value.")
        return value
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid score value.")


def _validate_numeric_bounds(value: float, criterion: ResearchSkillCriterion) -> None:
    if criterion.min_value is not None and value < criterion.min_value:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid score value.")
    if criterion.max_value is not None and value > criterion.max_value:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid score value.")
    if criterion.step is not None and criterion.step > 0 and criterion.min_value is not None:
        quotient = (value - criterion.min_value) / criterion.step
        if abs(quotient - round(quotient)) > 1e-7:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid score value.")


def _validate_evidence_range(video: ResearchVideo, start_frame: int, end_frame_exclusive: int | None) -> None:
    if start_frame < 0 or start_frame >= video.frame_count:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Evidence frame is outside the video range.")
    if end_frame_exclusive is None:
        return
    if end_frame_exclusive <= start_frame or end_frame_exclusive > video.frame_count:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Evidence frame is outside the video range.")


def _get_assessment_by_unique_key(db: Session, *, video_id: int, rubric_id: int, rater_id: int) -> ResearchSkillAssessment | None:
    return db.scalar(
        select(ResearchSkillAssessment).where(
            ResearchSkillAssessment.video_id == video_id,
            ResearchSkillAssessment.rubric_id == rubric_id,
            ResearchSkillAssessment.rater_id == rater_id,
        )
    )


def _get_score_by_unique_key(db: Session, assessment_id: int, criterion_id: int, target_key: str) -> ResearchSkillScore | None:
    return db.scalar(
        select(ResearchSkillScore).where(
            ResearchSkillScore.assessment_id == assessment_id,
            ResearchSkillScore.criterion_id == criterion_id,
            ResearchSkillScore.target_key == target_key,
        )
    )


def _build_mutation_response(
    db: Session,
    *,
    action: str,
    assessment_id: int,
    changed_score_ids: list[int] | None = None,
    created_score_ids: list[int] | None = None,
    deleted_score_ids: list[int] | None = None,
    changed_evidence_ids: list[int] | None = None,
    created_evidence_ids: list[int] | None = None,
    deleted_evidence_ids: list[int] | None = None,
) -> ResearchSkillMutationResponse:
    db.expire_all()
    return ResearchSkillMutationResponse(
        action=action,
        assessment=get_skill_assessment(db, assessment_id),
        changed_score_ids=changed_score_ids or [],
        created_score_ids=created_score_ids or [],
        deleted_score_ids=deleted_score_ids or [],
        changed_evidence_ids=changed_evidence_ids or [],
        created_evidence_ids=created_evidence_ids or [],
        deleted_evidence_ids=deleted_evidence_ids or [],
    )


def calculate_assessment_completion(assessment: ResearchSkillAssessment) -> ResearchSkillCompletionResponse:
    required_overall = [criterion for criterion in assessment.rubric.criteria if criterion.is_active and criterion.required and criterion.scope == "overall"]
    required_phase = [criterion for criterion in assessment.rubric.criteria if criterion.is_active and criterion.required and criterion.scope == "phase"]
    scores_by_key = {(score.criterion_id, score.target_key): score for score in assessment.scores}
    phase_segments = _assessment_phase_segments(assessment)
    overall_completed = sum(1 for criterion in required_overall if _score_complete(scores_by_key.get((criterion.id, "overall"))))
    phase_total = 0
    phase_completed = 0
    for criterion in required_phase:
        for segment in phase_segments:
            if not _criterion_applies_to_segment(criterion, segment):
                continue
            phase_total += 1
            if _score_complete(scores_by_key.get((criterion.id, f"segment:{segment.id}"))):
                phase_completed += 1
    total = len(required_overall) + phase_total
    completed = overall_completed + phase_completed
    percent = round((completed / total) * 100, 2) if total else 100.0
    return ResearchSkillCompletionResponse(
        required_total=total,
        required_completed=completed,
        overall_required_total=len(required_overall),
        overall_required_completed=overall_completed,
        phase_required_total=phase_total,
        phase_required_completed=phase_completed,
        completion_percent=percent,
    )


def _assessment_phase_segments(assessment: ResearchSkillAssessment) -> list[ResearchPhaseSegment]:
    if assessment.phase_annotation_set is None:
        return []
    return sorted(assessment.phase_annotation_set.segments, key=lambda segment: (segment.start_frame, segment.id))


def _criterion_applies_to_segment(criterion: ResearchSkillCriterion, segment: ResearchPhaseSegment) -> bool:
    applicable_label_ids = {link.phase_label_id for link in criterion.phase_label_links}
    return not applicable_label_ids or segment.phase_label_id in applicable_label_ids


def _score_complete(score: ResearchSkillScore | None) -> bool:
    return score is not None and (score.is_na or score.value_json is not None)


def _rubric_summary_from_row(row) -> ResearchSkillRubricSummary:
    return ResearchSkillRubricSummary(
        id=row["id"],
        name=row["name"],
        version=row["version"],
        description=row["description"],
        status=row["status"],
        phase_protocol_id=row["phase_protocol_id"],
        created_by_id=row["created_by_id"],
        criterion_count=int(row["criterion_count"] or 0),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _rubric_summary_from_entity(rubric: ResearchSkillRubric) -> ResearchSkillRubricSummary:
    return ResearchSkillRubricSummary(
        id=rubric.id,
        name=rubric.name,
        version=rubric.version,
        description=rubric.description,
        status=rubric.status,
        phase_protocol_id=rubric.phase_protocol_id,
        created_by_id=rubric.created_by_id,
        criterion_count=len(rubric.criteria),
        created_at=rubric.created_at,
        updated_at=rubric.updated_at,
    )


def _rubric_detail_from_entity(rubric: ResearchSkillRubric) -> ResearchSkillRubricDetail:
    return ResearchSkillRubricDetail(
        **_rubric_summary_from_entity(rubric).model_dump(),
        criteria=[_criterion_to_response(criterion) for criterion in _sorted_criteria(rubric.criteria)],
    )


def _sorted_criteria(criteria: list[ResearchSkillCriterion]) -> list[ResearchSkillCriterion]:
    return sorted(criteria, key=lambda criterion: (criterion.display_order, criterion.id))


def _criterion_to_response(criterion: ResearchSkillCriterion) -> ResearchSkillCriterionResponse:
    links = sorted(criterion.phase_label_links, key=lambda link: (link.phase_label.display_order if link.phase_label else 0, link.phase_label_id))
    return ResearchSkillCriterionResponse(
        id=criterion.id,
        rubric_id=criterion.rubric_id,
        key=criterion.key,
        name=criterion.name,
        description=criterion.description,
        scope=criterion.scope,
        score_type=criterion.score_type,
        min_value=criterion.min_value,
        max_value=criterion.max_value,
        step=criterion.step,
        options_json=criterion.options_json,
        required=criterion.required,
        allow_na=criterion.allow_na,
        weight=criterion.weight,
        display_order=criterion.display_order,
        is_active=criterion.is_active,
        phase_label_ids=[link.phase_label_id for link in links],
        phase_labels=[
            ResearchSkillPhaseLabelResponse(
                id=link.phase_label.id,
                key=link.phase_label.key,
                name=link.phase_label.name,
                color=link.phase_label.color,
            )
            for link in links
            if link.phase_label is not None
        ],
        created_at=criterion.created_at,
        updated_at=criterion.updated_at,
    )


def _assessment_summary_from_row(row) -> ResearchSkillAssessmentSummary:
    return ResearchSkillAssessmentSummary(
        id=row["id"],
        video_id=row["video_id"],
        rubric_id=row["rubric_id"],
        rater_id=row["rater_id"],
        phase_annotation_set_id=row["phase_annotation_set_id"],
        status=row["status"],
        revision=row["revision"],
        overall_comment=row["overall_comment"],
        submitted_at=row["submitted_at"],
        reviewed_at=row["reviewed_at"],
        locked_at=row["locked_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        rubric_name=row["rubric_name"],
        rubric_version=row["rubric_version"],
        rater_username=row["rater_username"],
        score_count=int(row["score_count"] or 0),
    )


def _assessment_detail_from_entity(assessment: ResearchSkillAssessment) -> ResearchSkillAssessmentDetail:
    scores = sorted(
        assessment.scores,
        key=lambda score: (score.criterion.display_order if score.criterion else 0, score.target_key, score.id),
    )
    return ResearchSkillAssessmentDetail(
        id=assessment.id,
        video_id=assessment.video_id,
        rubric_id=assessment.rubric_id,
        rater_id=assessment.rater_id,
        phase_annotation_set_id=assessment.phase_annotation_set_id,
        status=assessment.status,
        revision=assessment.revision,
        overall_comment=assessment.overall_comment,
        submitted_at=assessment.submitted_at,
        reviewed_at=assessment.reviewed_at,
        locked_at=assessment.locked_at,
        created_at=assessment.created_at,
        updated_at=assessment.updated_at,
        rubric_name=assessment.rubric.name,
        rubric_version=assessment.rubric.version,
        rater_username=assessment.rater.username,
        score_count=len(assessment.scores),
        video={
            "id": assessment.video.id,
            "name": assessment.video.name,
            "fps": assessment.video.fps,
            "frame_count": assessment.video.frame_count,
            "duration_ms": assessment.video.duration_ms,
        },
        rubric=_rubric_detail_from_entity(assessment.rubric),
        phase_annotation_set=_phase_set_summary(assessment.phase_annotation_set),
        scores=[_score_to_response(score) for score in scores],
        completion=calculate_assessment_completion(assessment),
    )


def _phase_set_summary(phase_set: ResearchPhaseAnnotationSet | None) -> ResearchSkillPhaseAnnotationSetSummary | None:
    if phase_set is None:
        return None
    return ResearchSkillPhaseAnnotationSetSummary(
        id=phase_set.id,
        protocol_id=phase_set.protocol_id,
        status=phase_set.status,
        revision=phase_set.revision,
        segments=[
            ResearchSkillPhaseSegmentSummary(
                id=segment.id,
                phase_label_id=segment.phase_label_id,
                phase_key=segment.phase_label.key,
                phase_name=segment.phase_label.name,
                start_frame=segment.start_frame,
                end_frame_exclusive=segment.end_frame_exclusive,
            )
            for segment in sorted(phase_set.segments, key=lambda segment: (segment.start_frame, segment.id))
        ],
    )


def _score_to_response(score: ResearchSkillScore) -> ResearchSkillScoreResponse:
    criterion = score.criterion
    return ResearchSkillScoreResponse(
        id=score.id,
        assessment_id=score.assessment_id,
        criterion_id=score.criterion_id,
        criterion_key=criterion.key,
        criterion_name=criterion.name,
        scope=criterion.scope,
        score_type=criterion.score_type,
        target_key=score.target_key,
        phase_segment_id=score.phase_segment_id,
        value=score.value_json,
        is_na=score.is_na,
        comment=score.comment,
        evidence=[
            ResearchSkillEvidenceResponse.model_validate(evidence)
            for evidence in sorted(score.evidence, key=lambda item: (item.start_frame, item.id))
        ],
        created_at=score.created_at,
        updated_at=score.updated_at,
    )
