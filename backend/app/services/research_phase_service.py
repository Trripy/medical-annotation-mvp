from __future__ import annotations

from datetime import datetime, timezone
import math

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from fastapi import HTTPException, status

from app.models import (
    ResearchPhaseAnnotationSet,
    ResearchPhaseLabel,
    ResearchPhaseProtocol,
    ResearchPhaseSegment,
    ResearchVideo,
    User,
)
from app.schemas.research_phase import (
    CloseActivePhaseSegmentRequest,
    CreateResearchPhaseAnnotationSetResponse,
    CreateResearchPhaseSegmentRequest,
    FillResearchPhaseGapsRequest,
    MergeResearchPhaseSegmentsRequest,
    ReopenResearchPhaseAnnotationSetRequest,
    ResearchPhaseAnnotationSetDetail,
    ResearchPhaseGapFillPreviewResponse,
    ResearchPhaseGapResponse,
    ResearchPhaseAnnotationSetSummary,
    ResearchPhaseLabelResponse,
    ResearchPhaseMutationResponse,
    ResearchPhaseProtocolDetail,
    ResearchPhaseProtocolSummary,
    ResearchPhaseSegmentPhaseLabelResponse,
    ResearchPhaseSegmentResponse,
    ResearchPhaseStatusMutationResponse,
    ResearchPhaseValidationIssue,
    ResearchPhaseValidationIssueCounts,
    ResearchPhaseValidationResponse,
    SplitResearchPhaseSegmentRequest,
    SubmitResearchPhaseAnnotationSetRequest,
    TransitionResearchPhaseRequest,
    UpdateResearchPhaseSegmentRequest,
)

VALID_PROTOCOL_STATUSES = {"draft", "active", "archived"}
VALID_SEGMENT_SOURCES = {"manual", "model_suggestion", "model_corrected", "imported"}
NOTES_MAX_LENGTH = 4000
REVISION_CONFLICT_DETAIL = "Phase annotation set revision conflict."
VALIDATION_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
IDLE_PHASE_KEY = "idle"
MIN_SHORT_SEGMENT_FRAMES = 3
MAX_GAP_FILL_PREVIEW_GAPS = 1000


def list_phase_protocols(
    db: Session,
    status_filter: str | None = None,
    include_archived: bool = False,
) -> list[ResearchPhaseProtocolSummary]:
    normalized_status = _normalize_protocol_status_filter(status_filter)
    label_counts = (
        select(
            ResearchPhaseLabel.protocol_id.label("protocol_id"),
            func.count(ResearchPhaseLabel.id).label("label_count"),
        )
        .group_by(ResearchPhaseLabel.protocol_id)
        .subquery()
    )

    stmt = (
        select(
            ResearchPhaseProtocol.id,
            ResearchPhaseProtocol.name,
            ResearchPhaseProtocol.version,
            ResearchPhaseProtocol.description,
            ResearchPhaseProtocol.status,
            ResearchPhaseProtocol.is_default,
            func.coalesce(label_counts.c.label_count, 0).label("label_count"),
        )
        .outerjoin(label_counts, label_counts.c.protocol_id == ResearchPhaseProtocol.id)
        .order_by(
            ResearchPhaseProtocol.is_default.desc(),
            ResearchPhaseProtocol.name.asc(),
            ResearchPhaseProtocol.version.desc(),
            ResearchPhaseProtocol.id.asc(),
        )
    )

    if normalized_status is not None:
        stmt = stmt.where(ResearchPhaseProtocol.status == normalized_status)
    elif not include_archived:
        stmt = stmt.where(ResearchPhaseProtocol.status.in_(("draft", "active")))

    rows = db.execute(stmt).mappings().all()
    return [_protocol_summary_from_row(row) for row in rows]


def get_phase_protocol(db: Session, protocol_id: int) -> ResearchPhaseProtocolDetail:
    protocol = db.scalar(
        select(ResearchPhaseProtocol)
        .where(ResearchPhaseProtocol.id == protocol_id)
        .options(selectinload(ResearchPhaseProtocol.labels))
    )
    if protocol is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phase protocol not found.")
    return _protocol_detail_from_entity(protocol)


def list_video_phase_annotation_sets(db: Session, video_id: int) -> list[ResearchPhaseAnnotationSetSummary]:
    _get_video_or_404(db, video_id)

    segment_counts = (
        select(
            ResearchPhaseSegment.annotation_set_id.label("annotation_set_id"),
            func.count(ResearchPhaseSegment.id).label("segment_count"),
        )
        .group_by(ResearchPhaseSegment.annotation_set_id)
        .subquery()
    )
    open_segments = (
        select(ResearchPhaseSegment.annotation_set_id.label("annotation_set_id"))
        .where(ResearchPhaseSegment.end_frame_exclusive.is_(None))
        .distinct()
        .subquery()
    )

    stmt = (
        select(
            ResearchPhaseAnnotationSet.id,
            ResearchPhaseAnnotationSet.video_id,
            ResearchPhaseAnnotationSet.protocol_id,
            ResearchPhaseAnnotationSet.annotator_id,
            ResearchPhaseAnnotationSet.status,
            ResearchPhaseAnnotationSet.revision,
            ResearchPhaseAnnotationSet.submitted_at,
            ResearchPhaseAnnotationSet.created_at,
            ResearchPhaseAnnotationSet.updated_at,
            ResearchPhaseProtocol.name.label("protocol_name"),
            ResearchPhaseProtocol.version.label("protocol_version"),
            User.username.label("annotator_username"),
            func.coalesce(segment_counts.c.segment_count, 0).label("segment_count"),
            open_segments.c.annotation_set_id.is_not(None).label("has_open_segment"),
        )
        .join(ResearchPhaseProtocol, ResearchPhaseAnnotationSet.protocol_id == ResearchPhaseProtocol.id)
        .join(User, ResearchPhaseAnnotationSet.annotator_id == User.id)
        .outerjoin(segment_counts, segment_counts.c.annotation_set_id == ResearchPhaseAnnotationSet.id)
        .outerjoin(open_segments, open_segments.c.annotation_set_id == ResearchPhaseAnnotationSet.id)
        .where(ResearchPhaseAnnotationSet.video_id == video_id)
        .order_by(ResearchPhaseAnnotationSet.updated_at.desc(), ResearchPhaseAnnotationSet.id.desc())
    )

    rows = db.execute(stmt).mappings().all()
    return [_annotation_set_summary_from_row(row) for row in rows]


def get_phase_annotation_set(db: Session, annotation_set_id: int) -> ResearchPhaseAnnotationSetDetail:
    annotation_set = _get_annotation_set_or_404(db, annotation_set_id)
    return _annotation_set_detail_from_entity(annotation_set)


def validate_phase_annotation_set(
    db: Session,
    annotation_set_id: int,
) -> ResearchPhaseValidationResponse:
    annotation_set = _get_annotation_set_or_404(db, annotation_set_id)
    video = annotation_set.video
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research video not found.")

    segments = sorted(annotation_set.segments, key=lambda segment: (segment.start_frame, segment.id))
    frame_count = int(video.frame_count or 0)
    closed_segment_count = sum(1 for segment in segments if segment.end_frame_exclusive is not None)
    open_segment_count = len(segments) - closed_segment_count

    issues: list[ResearchPhaseValidationIssue] = []
    issues.extend(_validate_segment_bounds(segments, frame_count))
    issues.extend(_find_open_segment_issues(segments))
    issues.extend(_find_duplicate_start_issues(segments))
    issues.extend(_find_overlap_issues(segments))
    issues.extend(_find_inactive_label_issues(segments))
    issues.extend(_find_adjacent_same_label_issues(segments))
    issues.extend(_find_unusual_order_issues(segments))
    issues.extend(_find_short_segment_issues(segments, video.fps))

    if not segments:
        issues.append(
            _build_validation_issue(
                issue_type="no_segments",
                severity="error",
                message="No phase segments have been annotated.",
            )
        )
    else:
        issues.extend(_find_gap_issues(segments, frame_count))
        issues.extend(_find_video_end_not_covered_issues(segments, frame_count))

    issues = _sort_validation_issues(issues)
    issue_counts = _count_validation_issues(issues)
    closed_covered_frame_count = _calculate_closed_coverage(segments, frame_count)
    closed_coverage_percent = _calculate_closed_coverage_percent(closed_covered_frame_count, frame_count)
    has_error = issue_counts.error > 0
    has_warning = issue_counts.warning > 0

    return ResearchPhaseValidationResponse(
        annotation_set_id=annotation_set.id,
        video_id=annotation_set.video_id,
        revision=annotation_set.revision,
        status=annotation_set.status,
        frame_count=frame_count,
        segment_count=len(segments),
        closed_segment_count=closed_segment_count,
        open_segment_count=open_segment_count,
        closed_covered_frame_count=closed_covered_frame_count,
        closed_coverage_percent=closed_coverage_percent,
        issue_counts=issue_counts,
        issues=issues,
        is_valid=not has_error,
        can_submit=not has_error,
        requires_warning_confirmation=not has_error and has_warning,
    )


def submit_phase_annotation_set(
    db: Session,
    annotation_set_id: int,
    payload: SubmitResearchPhaseAnnotationSetRequest,
) -> ResearchPhaseStatusMutationResponse:
    annotation_set = _get_annotation_set_or_404(db, annotation_set_id)
    _validate_expected_revision(payload.expected_revision)
    _ensure_annotation_set_revision_matches_current(annotation_set, payload.expected_revision)

    if annotation_set.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft phase annotation sets can be submitted.",
        )

    validation = validate_phase_annotation_set(db, annotation_set_id)
    if validation.issue_counts.error > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Phase annotation set has validation errors.",
                "validation": validation.model_dump(mode="json"),
            },
        )
    if validation.issue_counts.warning > 0 and not payload.confirm_warnings:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Phase annotation set has warnings that require confirmation.",
                "validation": validation.model_dump(mode="json"),
            },
        )

    now = datetime.now(timezone.utc)
    try:
        result = db.execute(
            update(ResearchPhaseAnnotationSet)
            .where(
                ResearchPhaseAnnotationSet.id == annotation_set_id,
                ResearchPhaseAnnotationSet.revision == payload.expected_revision,
                ResearchPhaseAnnotationSet.status == "draft",
            )
            .values(
                status="submitted",
                revision=ResearchPhaseAnnotationSet.revision + 1,
                submitted_at=now,
                updated_at=now,
            )
        )
        if result.rowcount != 1:
            db.rollback()
            _raise_submit_conflict(db, annotation_set_id, payload.expected_revision)
        db.commit()
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise

    db.expire_all()
    return ResearchPhaseStatusMutationResponse(
        action="submitted",
        annotation_set=get_phase_annotation_set(db, annotation_set_id),
        validation=validate_phase_annotation_set(db, annotation_set_id),
    )


def reopen_phase_annotation_set(
    db: Session,
    annotation_set_id: int,
    payload: ReopenResearchPhaseAnnotationSetRequest,
) -> ResearchPhaseStatusMutationResponse:
    annotation_set = _get_annotation_set_or_404(db, annotation_set_id)
    _validate_expected_revision(payload.expected_revision)
    _ensure_annotation_set_revision_matches_current(annotation_set, payload.expected_revision)

    if annotation_set.status != "submitted":
        _raise_reopen_status_conflict(annotation_set.status)

    now = datetime.now(timezone.utc)
    try:
        result = db.execute(
            update(ResearchPhaseAnnotationSet)
            .where(
                ResearchPhaseAnnotationSet.id == annotation_set_id,
                ResearchPhaseAnnotationSet.revision == payload.expected_revision,
                ResearchPhaseAnnotationSet.status == "submitted",
            )
            .values(
                status="draft",
                revision=ResearchPhaseAnnotationSet.revision + 1,
                submitted_at=None,
                updated_at=now,
            )
        )
        if result.rowcount != 1:
            db.rollback()
            _raise_reopen_conflict(db, annotation_set_id, payload.expected_revision)
        db.commit()
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise

    db.expire_all()
    return ResearchPhaseStatusMutationResponse(
        action="reopened",
        annotation_set=get_phase_annotation_set(db, annotation_set_id),
        validation=None,
    )


def get_or_create_phase_annotation_set(
    db: Session,
    video_id: int,
    protocol_id: int,
    username: str,
) -> CreateResearchPhaseAnnotationSetResponse:
    normalized_username = _normalize_username(username)
    user = _get_user_by_username(db, normalized_username)
    _get_video_or_404(db, video_id)
    protocol = _get_protocol_or_404(db, protocol_id)

    existing = _get_annotation_set_by_unique_key(
        db,
        video_id=video_id,
        protocol_id=protocol.id,
        annotator_id=user.id,
    )
    if existing is not None:
        return CreateResearchPhaseAnnotationSetResponse(
            created=False,
            annotation_set=get_phase_annotation_set(db, existing.id),
        )

    if protocol.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="New annotation sets can only use an active phase protocol.",
        )

    annotation_set = ResearchPhaseAnnotationSet(
        video_id=video_id,
        protocol_id=protocol.id,
        annotator_id=user.id,
        status="draft",
        revision=1,
    )
    db.add(annotation_set)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _get_annotation_set_by_unique_key(
            db,
            video_id=video_id,
            protocol_id=protocol.id,
            annotator_id=user.id,
        )
        if existing is not None:
            return CreateResearchPhaseAnnotationSetResponse(
                created=False,
                annotation_set=get_phase_annotation_set(db, existing.id),
            )
        raise

    db.refresh(annotation_set)
    return CreateResearchPhaseAnnotationSetResponse(
        created=True,
        annotation_set=get_phase_annotation_set(db, annotation_set.id),
    )


def create_phase_segment(
    db: Session,
    annotation_set_id: int,
    payload: CreateResearchPhaseSegmentRequest,
) -> ResearchPhaseMutationResponse:
    annotation_set = _get_annotation_set_for_mutation(db, annotation_set_id)
    _require_draft_annotation_set(annotation_set)
    _validate_expected_revision(payload.expected_revision)

    label = _validate_phase_label_for_set(db, annotation_set, payload.phase_label_id)
    _validate_frame_range(
        annotation_set.video,
        payload.start_frame,
        payload.end_frame_exclusive,
    )
    _validate_source(payload.source)
    _validate_confidence(payload.confidence)
    notes = _normalize_notes(payload.notes)

    _check_segment_overlap(
        annotation_set,
        payload.start_frame,
        payload.end_frame_exclusive,
    )

    new_segment = ResearchPhaseSegment(
        annotation_set_id=annotation_set.id,
        phase_label_id=label.id,
        start_frame=payload.start_frame,
        end_frame_exclusive=payload.end_frame_exclusive,
        source=payload.source,
        confidence=payload.confidence,
        notes=notes,
    )
    db.add(new_segment)

    try:
        db.flush()
        _claim_annotation_set_revision(db, annotation_set.id, payload.expected_revision)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    return _build_mutation_response(
        db,
        action="created",
        annotation_set_id=annotation_set.id,
        changed_segment_ids=[new_segment.id],
        created_segment_ids=[new_segment.id],
    )


def preview_phase_gap_fill(
    db: Session,
    annotation_set_id: int,
    payload: FillResearchPhaseGapsRequest,
) -> ResearchPhaseGapFillPreviewResponse:
    annotation_set = _get_annotation_set_or_404(db, annotation_set_id)
    _require_draft_annotation_set(annotation_set)
    _validate_expected_revision(payload.expected_revision)
    label = _validate_phase_label_for_set(db, annotation_set, payload.phase_label_id)
    return _build_gap_fill_preview(annotation_set, label)


def fill_phase_gaps(
    db: Session,
    annotation_set_id: int,
    payload: FillResearchPhaseGapsRequest,
) -> ResearchPhaseMutationResponse:
    db.execute(
        select(ResearchPhaseAnnotationSet.id)
        .where(ResearchPhaseAnnotationSet.id == annotation_set_id)
        .with_for_update()
    ).scalar_one_or_none()
    annotation_set = _get_annotation_set_for_mutation(db, annotation_set_id)
    _require_draft_annotation_set(annotation_set)
    _validate_expected_revision(payload.expected_revision)
    _ensure_annotation_set_revision_matches_current(annotation_set, payload.expected_revision)
    label = _validate_phase_label_for_set(db, annotation_set, payload.phase_label_id)
    gaps = calculate_phase_annotation_gaps(annotation_set.video.frame_count if annotation_set.video else 0, annotation_set.segments)

    if not gaps:
        return _build_mutation_response(
            db,
            action="unchanged",
            annotation_set_id=annotation_set.id,
        )

    created_segments: list[ResearchPhaseSegment] = []
    for gap in gaps:
        segment = ResearchPhaseSegment(
            annotation_set_id=annotation_set.id,
            phase_label_id=label.id,
            start_frame=gap.start_frame,
            end_frame_exclusive=gap.end_frame_exclusive,
            source="manual",
            confidence=None,
            notes=None,
        )
        db.add(segment)
        created_segments.append(segment)

    try:
        db.flush()
        created_segment_ids = [segment.id for segment in created_segments]
        _claim_annotation_set_revision(db, annotation_set.id, payload.expected_revision)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    return _build_mutation_response(
        db,
        action="filled_gaps",
        annotation_set_id=annotation_set.id,
        changed_segment_ids=created_segment_ids,
        created_segment_ids=created_segment_ids,
    )


def transition_phase(
    db: Session,
    annotation_set_id: int,
    payload: TransitionResearchPhaseRequest,
) -> ResearchPhaseMutationResponse:
    annotation_set = _get_annotation_set_for_mutation(db, annotation_set_id)
    _require_draft_annotation_set(annotation_set)
    _validate_expected_revision(payload.expected_revision)
    _validate_transition_frame(annotation_set.video, payload.current_frame)

    label = _validate_phase_label_for_set(db, annotation_set, payload.phase_label_id)
    active_segment = _find_active_segment(annotation_set)

    if active_segment is not None and active_segment.phase_label_id == label.id:
        return _build_mutation_response(
            db,
            action="unchanged",
            annotation_set_id=annotation_set.id,
        )

    if payload.current_frame >= annotation_set.video.frame_count:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Current frame must be before the video end frame.",
        )

    changed_segment_ids: list[int] = []
    created_segment_ids: list[int] = []

    if active_segment is not None:
        if payload.current_frame <= active_segment.start_frame:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Current frame must be after the active segment start frame.",
            )
        active_segment.end_frame_exclusive = payload.current_frame
        _check_segment_overlap(
            annotation_set,
            active_segment.start_frame,
            active_segment.end_frame_exclusive,
            exclude_segment_id=active_segment.id,
        )
        changed_segment_ids.append(active_segment.id)

    _check_segment_overlap(
        annotation_set,
        payload.current_frame,
        None,
    )
    new_segment = ResearchPhaseSegment(
        annotation_set_id=annotation_set.id,
        phase_label_id=label.id,
        start_frame=payload.current_frame,
        end_frame_exclusive=None,
        source="manual",
        confidence=None,
        notes=None,
    )
    db.add(new_segment)

    try:
        db.flush()
        changed_segment_ids.append(new_segment.id)
        created_segment_ids.append(new_segment.id)
        _claim_annotation_set_revision(db, annotation_set.id, payload.expected_revision)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    return _build_mutation_response(
        db,
        action="transitioned",
        annotation_set_id=annotation_set.id,
        changed_segment_ids=changed_segment_ids,
        created_segment_ids=created_segment_ids,
    )


def close_active_phase_segment(
    db: Session,
    annotation_set_id: int,
    payload: CloseActivePhaseSegmentRequest,
) -> ResearchPhaseMutationResponse:
    annotation_set = _get_annotation_set_for_mutation(db, annotation_set_id)
    _require_draft_annotation_set(annotation_set)
    _validate_expected_revision(payload.expected_revision)

    active_segment = _find_active_segment(annotation_set)
    if active_segment is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No active phase segment exists.",
        )

    _validate_end_frame_for_close(
        annotation_set.video,
        active_segment.start_frame,
        payload.end_frame_exclusive,
    )
    active_segment.end_frame_exclusive = payload.end_frame_exclusive
    _check_segment_overlap(
        annotation_set,
        active_segment.start_frame,
        active_segment.end_frame_exclusive,
        exclude_segment_id=active_segment.id,
    )

    try:
        db.flush()
        _claim_annotation_set_revision(db, annotation_set.id, payload.expected_revision)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    return _build_mutation_response(
        db,
        action="closed",
        annotation_set_id=annotation_set.id,
        changed_segment_ids=[active_segment.id],
    )


def update_phase_segment(
    db: Session,
    segment_id: int,
    payload: UpdateResearchPhaseSegmentRequest,
) -> ResearchPhaseMutationResponse:
    segment, annotation_set = _get_segment_for_mutation(db, segment_id)
    _require_draft_annotation_set(annotation_set)
    _validate_expected_revision(payload.expected_revision)

    new_phase_label_id = segment.phase_label_id
    new_start_frame = segment.start_frame
    new_end_frame_exclusive = segment.end_frame_exclusive
    new_source = segment.source
    new_confidence = segment.confidence
    new_notes = segment.notes

    if payload.phase_label_id is not None:
        label = _validate_phase_label_for_set(db, annotation_set, payload.phase_label_id)
        new_phase_label_id = label.id

    if payload.start_frame is not None:
        new_start_frame = payload.start_frame

    if payload.clear_end_frame:
        new_end_frame_exclusive = None
    elif payload.end_frame_exclusive is not None:
        new_end_frame_exclusive = payload.end_frame_exclusive

    if payload.source is not None:
        _validate_source(payload.source)
        new_source = payload.source

    if payload.clear_confidence:
        new_confidence = None
    elif payload.confidence is not None:
        _validate_confidence(payload.confidence)
        new_confidence = payload.confidence

    if payload.clear_notes:
        new_notes = None
    elif payload.notes is not None:
        new_notes = _normalize_notes(payload.notes)

    _validate_frame_range(
        annotation_set.video,
        new_start_frame,
        new_end_frame_exclusive,
    )
    _check_segment_overlap(
        annotation_set,
        new_start_frame,
        new_end_frame_exclusive,
        exclude_segment_id=segment.id,
    )

    if (
        new_phase_label_id == segment.phase_label_id
        and new_start_frame == segment.start_frame
        and new_end_frame_exclusive == segment.end_frame_exclusive
        and new_source == segment.source
        and new_confidence == segment.confidence
        and new_notes == segment.notes
    ):
        return _build_mutation_response(
            db,
            action="unchanged",
            annotation_set_id=annotation_set.id,
        )

    segment.phase_label_id = new_phase_label_id
    segment.start_frame = new_start_frame
    segment.end_frame_exclusive = new_end_frame_exclusive
    segment.source = new_source
    segment.confidence = new_confidence
    segment.notes = new_notes

    try:
        db.flush()
        _claim_annotation_set_revision(db, annotation_set.id, payload.expected_revision)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    return _build_mutation_response(
        db,
        action="updated",
        annotation_set_id=annotation_set.id,
        changed_segment_ids=[segment.id],
    )


def delete_phase_segment(
    db: Session,
    segment_id: int,
    expected_revision: int,
) -> ResearchPhaseMutationResponse:
    segment, annotation_set = _get_segment_for_mutation(db, segment_id)
    _require_draft_annotation_set(annotation_set)
    _validate_expected_revision(expected_revision)

    # Future skill assessments will reference phase segments. Add a 409 guard here once
    # the skill schema and foreign keys exist; for now there is no skill table to query.
    deleted_segment_id = segment.id
    db.delete(segment)

    try:
        db.flush()
        _claim_annotation_set_revision(db, annotation_set.id, expected_revision)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    return _build_mutation_response(
        db,
        action="deleted",
        annotation_set_id=annotation_set.id,
        deleted_segment_ids=[deleted_segment_id],
    )


def split_phase_segment(
    db: Session,
    segment_id: int,
    payload: SplitResearchPhaseSegmentRequest,
) -> ResearchPhaseMutationResponse:
    segment, annotation_set = _get_segment_for_mutation(db, segment_id)
    _require_draft_annotation_set(annotation_set)
    _validate_expected_revision(payload.expected_revision)

    split_frame = payload.split_frame
    if split_frame <= segment.start_frame:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Split frame must be after the segment start frame.",
        )

    original_end_frame = segment.end_frame_exclusive
    if original_end_frame is None:
        video = annotation_set.video
        if video is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research video not found.")
        if split_frame >= video.frame_count:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Split frame must be before the video end frame.",
            )
    elif split_frame >= original_end_frame:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Split frame must be before the segment end frame.",
        )

    segment.end_frame_exclusive = split_frame
    new_segment = ResearchPhaseSegment(
        annotation_set_id=annotation_set.id,
        phase_label_id=segment.phase_label_id,
        start_frame=split_frame,
        end_frame_exclusive=original_end_frame,
        source=segment.source,
        confidence=segment.confidence,
        notes=segment.notes,
    )
    _check_segment_overlap(
        annotation_set,
        new_segment.start_frame,
        new_segment.end_frame_exclusive,
        exclude_segment_id=segment.id,
    )
    db.add(new_segment)

    try:
        db.flush()
        _claim_annotation_set_revision(db, annotation_set.id, payload.expected_revision)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    return _build_mutation_response(
        db,
        action="split",
        annotation_set_id=annotation_set.id,
        changed_segment_ids=[segment.id],
        created_segment_ids=[new_segment.id],
    )


def merge_phase_segments(
    db: Session,
    annotation_set_id: int,
    payload: MergeResearchPhaseSegmentsRequest,
) -> ResearchPhaseMutationResponse:
    annotation_set = _get_annotation_set_for_mutation(db, annotation_set_id)
    _require_draft_annotation_set(annotation_set)
    _validate_expected_revision(payload.expected_revision)

    left_segment = _get_segment_or_404(db, payload.left_segment_id)
    right_segment = _get_segment_or_404(db, payload.right_segment_id)

    if left_segment.id == right_segment.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Left and right segments must be different.",
        )
    if left_segment.annotation_set_id != annotation_set.id or right_segment.annotation_set_id != annotation_set.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Both segments must belong to the requested annotation set.",
        )

    left_segment, _ = _get_segment_for_mutation(db, left_segment.id)
    right_segment, _ = _get_segment_for_mutation(db, right_segment.id)

    if left_segment.start_frame >= right_segment.start_frame:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Left segment must start before right segment.",
        )
    if left_segment.end_frame_exclusive is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Left segment must be closed before merging.",
        )
    if left_segment.end_frame_exclusive != right_segment.start_frame:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Phase segments must be strictly adjacent to merge.",
        )
    if left_segment.phase_label_id != right_segment.phase_label_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only adjacent segments with the same phase label can be merged.",
        )

    right_segment_id = right_segment.id
    left_segment.end_frame_exclusive = right_segment.end_frame_exclusive
    left_segment.notes = _merge_segment_notes(left_segment.notes, right_segment.notes)
    db.delete(right_segment)

    try:
        db.flush()
        _claim_annotation_set_revision(db, annotation_set.id, payload.expected_revision)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    return _build_mutation_response(
        db,
        action="merged",
        annotation_set_id=annotation_set.id,
        changed_segment_ids=[left_segment.id],
        deleted_segment_ids=[right_segment_id],
    )


def _build_validation_issue(
    *,
    issue_type: str,
    severity: str,
    message: str,
    segment_id: int | None = None,
    related_segment_id: int | None = None,
    frame_start: int | None = None,
    frame_end_exclusive: int | None = None,
    details: dict[str, Any] | None = None,
) -> ResearchPhaseValidationIssue:
    return ResearchPhaseValidationIssue(
        issue_type=issue_type,
        severity=severity,
        message=message,
        segment_id=segment_id,
        related_segment_id=related_segment_id,
        frame_start=frame_start,
        frame_end_exclusive=frame_end_exclusive,
        details=details or {},
    )


def _validate_segment_bounds(
    segments: list[ResearchPhaseSegment],
    frame_count: int,
) -> list[ResearchPhaseValidationIssue]:
    issues: list[ResearchPhaseValidationIssue] = []
    if frame_count <= 0:
        issues.append(
            _build_validation_issue(
                issue_type="out_of_bounds",
                severity="error",
                message="The research video has an invalid frame count.",
                details={"frame_count": frame_count},
            )
        )

    for segment in segments:
        end_frame = segment.end_frame_exclusive
        if end_frame is not None and end_frame <= segment.start_frame:
            issues.append(
                _build_validation_issue(
                    issue_type="zero_length",
                    severity="error",
                    message="Phase segment must have a positive duration.",
                    segment_id=segment.id,
                    frame_start=segment.start_frame,
                    frame_end_exclusive=end_frame,
                )
            )

        if segment.start_frame < 0:
            issues.append(
                _build_validation_issue(
                    issue_type="out_of_bounds",
                    severity="error",
                    message="Phase segment starts outside the video frame range.",
                    segment_id=segment.id,
                    frame_start=segment.start_frame,
                    frame_end_exclusive=end_frame,
                )
            )
        elif frame_count > 0 and segment.start_frame >= frame_count:
            issues.append(
                _build_validation_issue(
                    issue_type="out_of_bounds",
                    severity="error",
                    message="Phase segment starts outside the video frame range.",
                    segment_id=segment.id,
                    frame_start=segment.start_frame,
                    frame_end_exclusive=end_frame,
                    details={"frame_count": frame_count},
                )
            )

        if end_frame is not None and frame_count > 0 and end_frame > frame_count:
            issues.append(
                _build_validation_issue(
                    issue_type="out_of_bounds",
                    severity="error",
                    message="Phase segment ends outside the video frame range.",
                    segment_id=segment.id,
                    frame_start=segment.start_frame,
                    frame_end_exclusive=end_frame,
                    details={"frame_count": frame_count},
                )
            )

    return issues


def _find_open_segment_issues(segments: list[ResearchPhaseSegment]) -> list[ResearchPhaseValidationIssue]:
    return [
        _build_validation_issue(
            issue_type="open_segment",
            severity="error",
            message="The active phase segment must be closed before submission.",
            segment_id=segment.id,
            frame_start=segment.start_frame,
            frame_end_exclusive=None,
        )
        for segment in segments
        if segment.end_frame_exclusive is None
    ]


def _find_duplicate_start_issues(
    segments: list[ResearchPhaseSegment],
) -> list[ResearchPhaseValidationIssue]:
    grouped: dict[int, list[ResearchPhaseSegment]] = {}
    for segment in segments:
        grouped.setdefault(segment.start_frame, []).append(segment)

    issues: list[ResearchPhaseValidationIssue] = []
    for start_frame in sorted(grouped):
        duplicate_segments = sorted(grouped[start_frame], key=lambda segment: segment.id)
        if len(duplicate_segments) < 2:
            continue
        issues.append(
            _build_validation_issue(
                issue_type="duplicate_start",
                severity="error",
                message="Multiple phase segments start at the same frame.",
                segment_id=duplicate_segments[0].id,
                related_segment_id=duplicate_segments[1].id,
                frame_start=start_frame,
                details={"segment_ids": [segment.id for segment in duplicate_segments]},
            )
        )
    return issues


def _find_overlap_issues(segments: list[ResearchPhaseSegment]) -> list[ResearchPhaseValidationIssue]:
    candidates = [
        segment
        for segment in segments
        if segment.end_frame_exclusive is None or segment.end_frame_exclusive > segment.start_frame
    ]
    if not candidates:
        return []

    issues: list[ResearchPhaseValidationIssue] = []
    active_segment = candidates[0]
    active_end = math.inf if active_segment.end_frame_exclusive is None else float(active_segment.end_frame_exclusive)

    for segment in candidates[1:]:
        current_end = math.inf if segment.end_frame_exclusive is None else float(segment.end_frame_exclusive)
        if segment.start_frame < active_end and active_segment.start_frame < current_end:
            overlap_start = max(active_segment.start_frame, segment.start_frame)
            overlap_end = _resolve_overlap_end(active_segment, segment)
            issues.append(
                _build_validation_issue(
                    issue_type="overlap",
                    severity="error",
                    message="Phase segments overlap in time.",
                    segment_id=active_segment.id,
                    related_segment_id=segment.id,
                    frame_start=overlap_start,
                    frame_end_exclusive=overlap_end,
                    details={
                        "left_segment_id": active_segment.id,
                        "right_segment_id": segment.id,
                    },
                )
            )
            if current_end > active_end:
                active_segment = segment
                active_end = current_end
            continue

        active_segment = segment
        active_end = current_end

    return issues


def _resolve_overlap_end(
    left_segment: ResearchPhaseSegment,
    right_segment: ResearchPhaseSegment,
) -> int | None:
    if left_segment.end_frame_exclusive is None and right_segment.end_frame_exclusive is None:
        return None
    if left_segment.end_frame_exclusive is None:
        return right_segment.end_frame_exclusive
    if right_segment.end_frame_exclusive is None:
        return left_segment.end_frame_exclusive
    return min(left_segment.end_frame_exclusive, right_segment.end_frame_exclusive)


def _find_gap_issues(
    segments: list[ResearchPhaseSegment],
    frame_count: int,
) -> list[ResearchPhaseValidationIssue]:
    if frame_count <= 0:
        return []

    structural_segments = _collect_structural_segments(segments, frame_count)
    if not structural_segments:
        return []

    issues: list[ResearchPhaseValidationIssue] = []
    first_segment, first_start, first_end = structural_segments[0]
    if first_start > 0:
        issues.append(
            _build_validation_issue(
                issue_type="gap",
                severity="warning",
                message="There is an unlabeled gap at the beginning of the video.",
                segment_id=first_segment.id,
                frame_start=0,
                frame_end_exclusive=first_start,
            )
        )

    coverage_end = first_end
    previous_segment = first_segment
    for segment, start_frame, end_frame in structural_segments[1:]:
        if coverage_end is None:
            break
        if start_frame > coverage_end:
            issues.append(
                _build_validation_issue(
                    issue_type="gap",
                    severity="warning",
                    message="There is an unlabeled gap between phase segments.",
                    segment_id=previous_segment.id,
                    related_segment_id=segment.id,
                    frame_start=coverage_end,
                    frame_end_exclusive=start_frame,
                )
            )
            coverage_end = end_frame
            previous_segment = segment
            continue

        if end_frame is None or coverage_end is None:
            coverage_end = None
        else:
            coverage_end = max(coverage_end, end_frame)
            previous_segment = segment

    return issues


def _find_video_end_not_covered_issues(
    segments: list[ResearchPhaseSegment],
    frame_count: int,
) -> list[ResearchPhaseValidationIssue]:
    if frame_count <= 0 or not segments or any(segment.end_frame_exclusive is None for segment in segments):
        return []

    structural_segments = _collect_structural_segments(segments, frame_count)
    if not structural_segments:
        return []

    coverage_end = structural_segments[0][2]
    for _segment, start_frame, end_frame in structural_segments[1:]:
        if coverage_end is None:
            return []
        if start_frame > coverage_end:
            coverage_end = end_frame
            continue
        if end_frame is None:
            return []
        coverage_end = max(coverage_end, end_frame)

    if coverage_end is None or coverage_end >= frame_count:
        return []

    last_segment = structural_segments[-1][0]
    return [
        _build_validation_issue(
            issue_type="video_end_not_covered",
            severity="warning",
            message="The end of the video is not covered by a phase segment.",
            segment_id=last_segment.id,
            frame_start=coverage_end,
            frame_end_exclusive=frame_count,
        )
    ]


def _find_inactive_label_issues(
    segments: list[ResearchPhaseSegment],
) -> list[ResearchPhaseValidationIssue]:
    issues: list[ResearchPhaseValidationIssue] = []
    for segment in segments:
        label = segment.phase_label
        if label is None or label.is_active:
            continue
        issues.append(
            _build_validation_issue(
                issue_type="inactive_label",
                severity="warning",
                message="This segment uses an inactive phase label.",
                segment_id=segment.id,
                frame_start=segment.start_frame,
                frame_end_exclusive=segment.end_frame_exclusive,
                details={
                    "phase_label_id": label.id,
                    "phase_key": label.key,
                    "phase_name": label.name,
                },
            )
        )
    return issues


def _find_adjacent_same_label_issues(
    segments: list[ResearchPhaseSegment],
) -> list[ResearchPhaseValidationIssue]:
    issues: list[ResearchPhaseValidationIssue] = []
    for left_segment, right_segment in zip(segments, segments[1:]):
        if left_segment.end_frame_exclusive is None:
            continue
        if left_segment.end_frame_exclusive <= left_segment.start_frame:
            continue
        if left_segment.end_frame_exclusive != right_segment.start_frame:
            continue
        if left_segment.phase_label_id != right_segment.phase_label_id:
            continue
        issues.append(
            _build_validation_issue(
                issue_type="adjacent_same_label",
                severity="warning",
                message="Adjacent segments use the same phase label and can be merged.",
                segment_id=left_segment.id,
                related_segment_id=right_segment.id,
                frame_start=left_segment.start_frame,
                frame_end_exclusive=right_segment.end_frame_exclusive,
            )
        )
    return issues


def _find_unusual_order_issues(
    segments: list[ResearchPhaseSegment],
) -> list[ResearchPhaseValidationIssue]:
    non_idle_segments = [
        segment
        for segment in segments
        if segment.phase_label is not None and segment.phase_label.key != IDLE_PHASE_KEY
    ]

    issues: list[ResearchPhaseValidationIssue] = []
    for previous_segment, current_segment in zip(non_idle_segments, non_idle_segments[1:]):
        previous_label = previous_segment.phase_label
        current_label = current_segment.phase_label
        if previous_label is None or current_label is None:
            continue
        if current_label.display_order < previous_label.display_order:
            issues.append(
                _build_validation_issue(
                    issue_type="unusual_order",
                    severity="warning",
                    message="The phase sequence moves backward relative to the protocol order.",
                    segment_id=previous_segment.id,
                    related_segment_id=current_segment.id,
                    frame_start=current_segment.start_frame,
                    frame_end_exclusive=current_segment.end_frame_exclusive,
                    details={
                        "previous_phase_key": previous_label.key,
                        "previous_display_order": previous_label.display_order,
                        "current_phase_key": current_label.key,
                        "current_display_order": current_label.display_order,
                    },
                )
            )
    return issues


def _find_short_segment_issues(
    segments: list[ResearchPhaseSegment],
    fps: float | None,
) -> list[ResearchPhaseValidationIssue]:
    threshold_frames = _short_segment_threshold_frames(fps)
    issues: list[ResearchPhaseValidationIssue] = []
    for segment in segments:
        label = segment.phase_label
        end_frame = segment.end_frame_exclusive
        if label is None or label.key == IDLE_PHASE_KEY or end_frame is None or end_frame <= segment.start_frame:
            continue

        duration_frames = end_frame - segment.start_frame
        if duration_frames >= threshold_frames:
            continue

        issues.append(
            _build_validation_issue(
                issue_type="very_short_segment",
                severity="warning",
                message="This phase segment is unusually short.",
                segment_id=segment.id,
                frame_start=segment.start_frame,
                frame_end_exclusive=end_frame,
                details={
                    "duration_frames": duration_frames,
                    "threshold_frames": threshold_frames,
                    "fps": fps,
                },
            )
        )
    return issues


def _short_segment_threshold_frames(fps: float | None) -> int:
    if fps is None or fps <= 0:
        return MIN_SHORT_SEGMENT_FRAMES
    return max(MIN_SHORT_SEGMENT_FRAMES, math.ceil(fps * 0.1))


def _collect_structural_segments(
    segments: list[ResearchPhaseSegment],
    frame_count: int,
) -> list[tuple[ResearchPhaseSegment, int, int | None]]:
    structural_segments: list[tuple[ResearchPhaseSegment, int, int | None]] = []
    if frame_count <= 0:
        return structural_segments

    for segment in segments:
        end_frame = segment.end_frame_exclusive
        if end_frame is not None and end_frame <= segment.start_frame:
            continue

        clamped_start = max(0, min(segment.start_frame, frame_count))
        if end_frame is None:
            if clamped_start >= frame_count:
                continue
            structural_segments.append((segment, clamped_start, None))
            continue

        clamped_end = max(0, min(end_frame, frame_count))
        if clamped_end <= clamped_start:
            continue
        structural_segments.append((segment, clamped_start, clamped_end))

    return structural_segments


def _calculate_closed_coverage(
    segments: list[ResearchPhaseSegment],
    frame_count: int,
) -> int:
    if frame_count <= 0:
        return 0

    intervals: list[tuple[int, int]] = []
    for segment in segments:
        end_frame = segment.end_frame_exclusive
        if end_frame is None or end_frame <= segment.start_frame:
            continue

        start_frame = max(0, min(segment.start_frame, frame_count))
        clamped_end = max(0, min(end_frame, frame_count))
        if clamped_end <= start_frame:
            continue
        intervals.append((start_frame, clamped_end))

    if not intervals:
        return 0

    intervals.sort()
    covered_frame_count = 0
    current_start, current_end = intervals[0]
    for start_frame, end_frame in intervals[1:]:
        if start_frame <= current_end:
            current_end = max(current_end, end_frame)
            continue

        covered_frame_count += current_end - current_start
        current_start, current_end = start_frame, end_frame

    covered_frame_count += current_end - current_start
    return max(0, min(covered_frame_count, frame_count))


def _calculate_closed_coverage_percent(closed_covered_frame_count: int, frame_count: int) -> float:
    if frame_count <= 0:
        return 0.0
    coverage = (closed_covered_frame_count / frame_count) * 100
    return round(max(0.0, min(coverage, 100.0)), 2)


def _count_validation_issues(
    issues: list[ResearchPhaseValidationIssue],
) -> ResearchPhaseValidationIssueCounts:
    counts = {"error": 0, "warning": 0, "info": 0}
    for issue in issues:
        counts[issue.severity] += 1
    return ResearchPhaseValidationIssueCounts(**counts)


def _sort_validation_issues(
    issues: list[ResearchPhaseValidationIssue],
) -> list[ResearchPhaseValidationIssue]:
    return sorted(
        issues,
        key=lambda issue: (
            VALIDATION_SEVERITY_ORDER[issue.severity],
            issue.frame_start is None,
            issue.frame_start if issue.frame_start is not None else math.inf,
            issue.segment_id is None,
            issue.segment_id if issue.segment_id is not None else math.inf,
            issue.issue_type,
            issue.related_segment_id is None,
            issue.related_segment_id if issue.related_segment_id is not None else math.inf,
            issue.frame_end_exclusive is None,
            issue.frame_end_exclusive if issue.frame_end_exclusive is not None else math.inf,
        ),
    )


def _normalize_protocol_status_filter(status_filter: str | None) -> str | None:
    if status_filter is None:
        return None

    normalized = status_filter.strip().lower()
    if normalized not in VALID_PROTOCOL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid protocol status filter.",
        )
    return normalized


def _normalize_username(username: str) -> str:
    normalized = username.strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Username cannot be empty.",
        )
    return normalized


def _normalize_notes(notes: str | None) -> str | None:
    if notes is None:
        return None
    normalized = notes.strip()
    if len(normalized) > NOTES_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Notes cannot exceed {NOTES_MAX_LENGTH} characters.",
        )
    return normalized or None


def _validate_expected_revision(expected_revision: int) -> None:
    if expected_revision < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Expected revision must be at least 1.",
        )


def _ensure_annotation_set_revision_matches_current(
    annotation_set: ResearchPhaseAnnotationSet,
    expected_revision: int,
) -> None:
    if annotation_set.revision != expected_revision:
        _raise_revision_conflict(annotation_set.revision)


def _raise_revision_conflict(current_revision: int | None) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": REVISION_CONFLICT_DETAIL,
            "current_revision": current_revision,
        },
    )


def _raise_submit_conflict(db: Session, annotation_set_id: int, expected_revision: int) -> None:
    current = db.get(ResearchPhaseAnnotationSet, annotation_set_id)
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Phase annotation set not found.",
        )
    if current.revision != expected_revision:
        _raise_revision_conflict(current.revision)
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Only draft phase annotation sets can be submitted.",
    )


def _raise_reopen_conflict(db: Session, annotation_set_id: int, expected_revision: int) -> None:
    current = db.get(ResearchPhaseAnnotationSet, annotation_set_id)
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Phase annotation set not found.",
        )
    if current.revision != expected_revision:
        _raise_revision_conflict(current.revision)
    _raise_reopen_status_conflict(current.status)


def _raise_reopen_status_conflict(status_value: str) -> None:
    if status_value == "draft":
        detail = "Only submitted phase annotation sets can be reopened."
    elif status_value == "reviewed":
        detail = "Reviewed phase annotation sets cannot be reopened."
    elif status_value == "locked":
        detail = "Locked phase annotation sets cannot be reopened."
    else:
        detail = "Only submitted phase annotation sets can be reopened."

    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _get_user_by_username(db: Session, username: str) -> User:
    user = db.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


def _get_video_or_404(db: Session, video_id: int) -> ResearchVideo:
    video = db.get(ResearchVideo, video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research video not found.")
    return video


def _get_protocol_or_404(db: Session, protocol_id: int) -> ResearchPhaseProtocol:
    protocol = db.get(ResearchPhaseProtocol, protocol_id)
    if protocol is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phase protocol not found.")
    return protocol


def _get_annotation_set_by_unique_key(
    db: Session,
    *,
    video_id: int,
    protocol_id: int,
    annotator_id: int,
) -> ResearchPhaseAnnotationSet | None:
    return db.scalar(
        select(ResearchPhaseAnnotationSet).where(
            ResearchPhaseAnnotationSet.video_id == video_id,
            ResearchPhaseAnnotationSet.protocol_id == protocol_id,
            ResearchPhaseAnnotationSet.annotator_id == annotator_id,
        )
    )


def _get_annotation_set_or_404(db: Session, annotation_set_id: int) -> ResearchPhaseAnnotationSet:
    annotation_set = db.scalar(
        select(ResearchPhaseAnnotationSet)
        .where(ResearchPhaseAnnotationSet.id == annotation_set_id)
        .options(
            selectinload(ResearchPhaseAnnotationSet.video),
            selectinload(ResearchPhaseAnnotationSet.protocol).selectinload(ResearchPhaseProtocol.labels),
            selectinload(ResearchPhaseAnnotationSet.annotator),
            selectinload(ResearchPhaseAnnotationSet.segments).selectinload(ResearchPhaseSegment.phase_label),
        )
    )
    if annotation_set is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Phase annotation set not found.",
        )
    return annotation_set


def _get_annotation_set_for_mutation(db: Session, annotation_set_id: int) -> ResearchPhaseAnnotationSet:
    return _get_annotation_set_or_404(db, annotation_set_id)


def _get_segment_or_404(db: Session, segment_id: int) -> ResearchPhaseSegment:
    segment = db.scalar(
        select(ResearchPhaseSegment).where(ResearchPhaseSegment.id == segment_id)
    )
    if segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phase segment not found.")
    return segment


def _get_segment_for_mutation(
    db: Session,
    segment_id: int,
) -> tuple[ResearchPhaseSegment, ResearchPhaseAnnotationSet]:
    segment = _get_segment_or_404(db, segment_id)

    annotation_set = _get_annotation_set_for_mutation(db, segment.annotation_set_id)
    target_segment = next(
        (annotation_segment for annotation_segment in annotation_set.segments if annotation_segment.id == segment_id),
        None,
    )
    if target_segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phase segment not found.")
    return target_segment, annotation_set


def _require_draft_annotation_set(annotation_set: ResearchPhaseAnnotationSet) -> None:
    if annotation_set.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft phase annotation sets can be modified.",
        )


def _validate_phase_label_for_set(
    db: Session,
    annotation_set: ResearchPhaseAnnotationSet,
    phase_label_id: int,
) -> ResearchPhaseLabel:
    label = db.get(ResearchPhaseLabel, phase_label_id)
    if label is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phase label not found.")
    if label.protocol_id != annotation_set.protocol_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Phase label does not belong to the annotation set protocol.",
        )
    if not label.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Inactive phase labels cannot be used.",
        )
    return label


def _validate_source(source: str) -> None:
    if source not in VALID_SEGMENT_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid phase segment source.",
        )


def _validate_confidence(confidence: float | None) -> None:
    if confidence is None:
        return
    if confidence < 0 or confidence > 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Confidence must be between 0 and 1.",
        )


def _validate_frame_range(
    video: ResearchVideo | None,
    start_frame: int,
    end_frame_exclusive: int | None,
) -> None:
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research video not found.")
    if start_frame < 0 or start_frame >= video.frame_count:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Start frame is out of bounds.",
        )
    if end_frame_exclusive is None:
        return
    if end_frame_exclusive <= start_frame:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="End frame must be greater than start frame.",
        )
    if end_frame_exclusive > video.frame_count:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="End frame is out of bounds.",
        )


def _validate_transition_frame(video: ResearchVideo | None, current_frame: int) -> None:
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research video not found.")
    if current_frame < 0 or current_frame > video.frame_count:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Current frame is out of bounds.",
        )


def _validate_end_frame_for_close(
    video: ResearchVideo | None,
    start_frame: int,
    end_frame_exclusive: int,
) -> None:
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research video not found.")
    if end_frame_exclusive <= start_frame:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="End frame must be greater than the active segment start frame.",
        )
    if end_frame_exclusive > video.frame_count:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="End frame is out of bounds.",
        )


def _find_active_segment(annotation_set: ResearchPhaseAnnotationSet) -> ResearchPhaseSegment | None:
    active_segments = [
        segment
        for segment in annotation_set.segments
        if segment.end_frame_exclusive is None
    ]
    if len(active_segments) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Phase annotation set has multiple active segments.",
        )
    if not active_segments:
        return None
    return active_segments[0]


def _check_segment_overlap(
    annotation_set: ResearchPhaseAnnotationSet,
    start_frame: int,
    end_frame_exclusive: int | None,
    *,
    exclude_segment_id: int | None = None,
) -> None:
    candidate_end = float("inf") if end_frame_exclusive is None else float(end_frame_exclusive)

    for segment in annotation_set.segments:
        if exclude_segment_id is not None and segment.id == exclude_segment_id:
            continue
        existing_end = float("inf") if segment.end_frame_exclusive is None else float(segment.end_frame_exclusive)
        if start_frame < existing_end and segment.start_frame < candidate_end:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Phase segment overlaps an existing segment.",
            )


def calculate_phase_annotation_gaps(
    video_frame_count: int,
    segments: list[ResearchPhaseSegment],
) -> list[ResearchPhaseGapResponse]:
    if video_frame_count <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Video frame count must be positive.",
        )

    sorted_segments = sorted(segments, key=lambda segment: (
        segment.start_frame,
        segment.end_frame_exclusive if segment.end_frame_exclusive is not None else video_frame_count + 1,
        segment.id or 0,
    ))
    cursor = 0
    gaps: list[ResearchPhaseGapResponse] = []
    closed_segment_count = len([segment for segment in sorted_segments if segment.end_frame_exclusive is not None])
    closed_index = 0

    for segment in sorted_segments:
        if segment.end_frame_exclusive is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "open_phase_segment_exists",
                    "message": "Please close the active phase segment before filling gaps.",
                },
            )
        if segment.start_frame < 0 or segment.end_frame_exclusive > video_frame_count or segment.end_frame_exclusive <= segment.start_frame:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Existing phase segment range is invalid.",
            )
        if segment.start_frame < cursor:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "phase_segment_overlap",
                    "message": "Existing phase segments overlap.",
                },
            )
        if cursor < segment.start_frame:
            gap_type = "leading" if closed_index == 0 else "internal"
            gaps.append(ResearchPhaseGapResponse(
                start_frame=cursor,
                end_frame_exclusive=segment.start_frame,
                frame_count=segment.start_frame - cursor,
                gap_type=gap_type,
            ))
        cursor = max(cursor, segment.end_frame_exclusive)
        closed_index += 1

    if cursor < video_frame_count:
        gap_type = "leading" if closed_segment_count == 0 else "trailing"
        gaps.append(ResearchPhaseGapResponse(
            start_frame=cursor,
            end_frame_exclusive=video_frame_count,
            frame_count=video_frame_count - cursor,
            gap_type=gap_type,
        ))

    return gaps


def _build_gap_fill_preview(
    annotation_set: ResearchPhaseAnnotationSet,
    label: ResearchPhaseLabel,
) -> ResearchPhaseGapFillPreviewResponse:
    video = annotation_set.video
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research video not found.")
    gaps = calculate_phase_annotation_gaps(int(video.frame_count or 0), annotation_set.segments)
    visible_gaps = gaps[:MAX_GAP_FILL_PREVIEW_GAPS]
    total_gap_frames = sum(gap.frame_count for gap in gaps)
    duration_ms = None
    if video.fps and video.fps > 0:
        duration_ms = int(round((total_gap_frames / video.fps) * 1000))
    return ResearchPhaseGapFillPreviewResponse(
        annotation_set_id=annotation_set.id,
        current_revision=annotation_set.revision,
        phase_label_id=label.id,
        phase_label_name=label.name,
        video_frame_count=int(video.frame_count or 0),
        gap_count=len(gaps),
        total_gap_frames=total_gap_frames,
        total_gap_duration_ms=duration_ms,
        leading_gap_count=sum(1 for gap in gaps if gap.gap_type == "leading"),
        internal_gap_count=sum(1 for gap in gaps if gap.gap_type == "internal"),
        trailing_gap_count=sum(1 for gap in gaps if gap.gap_type == "trailing"),
        gaps=visible_gaps,
        truncated=len(gaps) > len(visible_gaps),
    )


def _merge_segment_notes(left_notes: str | None, right_notes: str | None) -> str | None:
    normalized_left = _normalize_notes(left_notes)
    normalized_right = _normalize_notes(right_notes)

    if normalized_left is None and normalized_right is None:
        return None
    if normalized_left is None:
        return normalized_right
    if normalized_right is None:
        return normalized_left
    if normalized_left == normalized_right:
        return normalized_left
    return f"{normalized_left}\n{normalized_right}"


def _claim_annotation_set_revision(db: Session, annotation_set_id: int, expected_revision: int) -> None:
    result = db.execute(
        update(ResearchPhaseAnnotationSet)
        .where(
            ResearchPhaseAnnotationSet.id == annotation_set_id,
            ResearchPhaseAnnotationSet.revision == expected_revision,
        )
        .values(
            revision=ResearchPhaseAnnotationSet.revision + 1,
            updated_at=func.now(),
        )
    )
    if result.rowcount == 1:
        return

    db.rollback()
    current_revision = db.scalar(
        select(ResearchPhaseAnnotationSet.revision).where(
            ResearchPhaseAnnotationSet.id == annotation_set_id
        )
    )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": REVISION_CONFLICT_DETAIL,
            "current_revision": current_revision,
        },
    )


def _build_mutation_response(
    db: Session,
    *,
    action: str,
    annotation_set_id: int,
    changed_segment_ids: list[int] | None = None,
    created_segment_ids: list[int] | None = None,
    deleted_segment_ids: list[int] | None = None,
) -> ResearchPhaseMutationResponse:
    db.expire_all()
    annotation_set = get_phase_annotation_set(db, annotation_set_id)
    return ResearchPhaseMutationResponse(
        action=action,
        annotation_set=annotation_set,
        changed_segment_ids=changed_segment_ids or [],
        created_segment_ids=created_segment_ids or [],
        deleted_segment_ids=deleted_segment_ids or [],
    )


def _protocol_summary_from_row(row) -> ResearchPhaseProtocolSummary:
    return ResearchPhaseProtocolSummary(
        id=row["id"],
        name=row["name"],
        version=row["version"],
        description=row["description"],
        status=row["status"],
        is_default=bool(row["is_default"]),
        label_count=int(row["label_count"] or 0),
    )


def _protocol_detail_from_entity(protocol: ResearchPhaseProtocol) -> ResearchPhaseProtocolDetail:
    labels = sorted(protocol.labels, key=lambda label: (label.display_order, label.id))
    return ResearchPhaseProtocolDetail(
        id=protocol.id,
        name=protocol.name,
        version=protocol.version,
        description=protocol.description,
        status=protocol.status,
        is_default=protocol.is_default,
        label_count=len(labels),
        labels=[_label_to_response(label) for label in labels],
    )


def _label_to_response(label: ResearchPhaseLabel) -> ResearchPhaseLabelResponse:
    return ResearchPhaseLabelResponse(
        id=label.id,
        protocol_id=label.protocol_id,
        key=label.key,
        name=label.name,
        color=label.color,
        display_order=label.display_order,
        shortcut=label.shortcut,
        description=label.description,
        is_active=label.is_active,
    )


def _annotation_set_summary_from_row(row) -> ResearchPhaseAnnotationSetSummary:
    return ResearchPhaseAnnotationSetSummary(
        id=row["id"],
        video_id=row["video_id"],
        protocol_id=row["protocol_id"],
        annotator_id=row["annotator_id"],
        status=row["status"],
        revision=row["revision"],
        submitted_at=row["submitted_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        protocol_name=row["protocol_name"],
        protocol_version=row["protocol_version"],
        annotator_username=row["annotator_username"],
        segment_count=int(row["segment_count"] or 0),
        has_open_segment=bool(row["has_open_segment"]),
    )


def _annotation_set_detail_from_entity(annotation_set: ResearchPhaseAnnotationSet) -> ResearchPhaseAnnotationSetDetail:
    protocol = annotation_set.protocol
    if protocol is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phase protocol not found.")

    annotator = annotation_set.annotator
    if annotator is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    segments = sorted(annotation_set.segments, key=lambda segment: (segment.start_frame, segment.id))
    protocol_detail = _protocol_detail_from_entity(protocol)
    return ResearchPhaseAnnotationSetDetail(
        id=annotation_set.id,
        video_id=annotation_set.video_id,
        protocol_id=annotation_set.protocol_id,
        annotator_id=annotation_set.annotator_id,
        status=annotation_set.status,
        revision=annotation_set.revision,
        submitted_at=annotation_set.submitted_at,
        created_at=annotation_set.created_at,
        updated_at=annotation_set.updated_at,
        protocol_name=protocol.name,
        protocol_version=protocol.version,
        annotator_username=annotator.username,
        segment_count=len(segments),
        has_open_segment=any(segment.end_frame_exclusive is None for segment in segments),
        protocol=protocol_detail,
        segments=[_segment_to_response(segment) for segment in segments],
    )


def _segment_to_response(segment: ResearchPhaseSegment) -> ResearchPhaseSegmentResponse:
    phase_label = segment.phase_label
    if phase_label is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phase protocol not found.")

    return ResearchPhaseSegmentResponse(
        id=segment.id,
        annotation_set_id=segment.annotation_set_id,
        phase_label_id=segment.phase_label_id,
        start_frame=segment.start_frame,
        end_frame_exclusive=segment.end_frame_exclusive,
        source=segment.source,
        confidence=segment.confidence,
        notes=segment.notes,
        created_at=segment.created_at,
        updated_at=segment.updated_at,
        phase_label=ResearchPhaseSegmentPhaseLabelResponse(
            id=phase_label.id,
            key=phase_label.key,
            name=phase_label.name,
            color=phase_label.color,
        ),
    )
