from __future__ import annotations

import math
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ResearchPhaseAnnotationSet,
    ResearchSkillRubric,
    ResearchPhaseSegment,
    ResearchSkillAssessment,
    ResearchSkillCriterion,
    ResearchSkillCriterionPhaseLabel,
    ResearchSkillScore,
)
from app.schemas.research_skill import (
    ResearchSkillValidationIssue,
    ResearchSkillValidationIssueCounts,
    ResearchSkillValidationResponse,
)

VALIDATION_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def validate_skill_assessment(db: Session, assessment_id: int) -> ResearchSkillValidationResponse:
    assessment = _get_assessment_for_validation(db, assessment_id)
    issues: list[ResearchSkillValidationIssue] = []
    scores_by_key = {(score.criterion_id, score.target_key): score for score in assessment.scores}
    phase_segments = _phase_segments(assessment)
    required_total = 0
    required_completed = 0

    if assessment.rubric.status != "active":
        issues.append(
            _issue(
                issue_type="rubric_not_active",
                severity="warning",
                message="The skill rubric is not active.",
                details={"rubric_status": assessment.rubric.status},
            )
        )

    phase_criteria = [criterion for criterion in assessment.rubric.criteria if criterion.scope == "phase" and criterion.is_active]
    if phase_criteria and assessment.phase_annotation_set is None:
        issues.append(
            _issue(
                issue_type="assessment_phase_set_missing",
                severity="error",
                message="A phase annotation set is required for phase-level criteria.",
            )
        )
    if assessment.phase_annotation_set is not None and assessment.phase_annotation_set.status == "draft":
        issues.append(
            _issue(
                issue_type="assessment_phase_set_draft",
                severity="warning",
                message="The linked phase annotation set is still draft.",
                details={"phase_annotation_set_id": assessment.phase_annotation_set.id},
            )
        )

    for criterion in sorted(assessment.rubric.criteria, key=lambda item: (item.display_order, item.id)):
        if not criterion.is_active:
            if any(score.criterion_id == criterion.id for score in assessment.scores):
                issues.append(
                    _issue(
                        issue_type="inactive_criterion",
                        severity="warning",
                        message="This score uses an inactive criterion.",
                        criterion_id=criterion.id,
                    )
                )
            continue

        if criterion.required and criterion.scope == "overall":
            required_total += 1
            score = scores_by_key.get((criterion.id, "overall"))
            if _score_complete(score):
                required_completed += 1
            else:
                issues.append(
                    _issue(
                        issue_type="missing_required_score",
                        severity="error",
                        message="A required overall score is missing.",
                        criterion_id=criterion.id,
                    )
                )
        elif criterion.required and criterion.scope == "phase":
            applicable_segments = [segment for segment in phase_segments if _criterion_applies_to_segment(criterion, segment)]
            if assessment.phase_annotation_set is not None and not applicable_segments:
                issues.append(
                    _issue(
                        issue_type="incomplete_phase_criteria",
                        severity="error",
                        message="A required phase criterion has no applicable phase segments.",
                        criterion_id=criterion.id,
                    )
                )
            for segment in applicable_segments:
                required_total += 1
                score = scores_by_key.get((criterion.id, f"segment:{segment.id}"))
                if _score_complete(score):
                    required_completed += 1
                else:
                    issues.append(
                        _issue(
                            issue_type="missing_required_score",
                            severity="error",
                            message="A required phase score is missing.",
                            criterion_id=criterion.id,
                            phase_segment_id=segment.id,
                        )
                    )

    for score in assessment.scores:
        criterion = score.criterion
        issues.extend(_validate_stored_score(assessment, criterion, score))
        for evidence in score.evidence:
            if evidence.start_frame < 0 or evidence.start_frame >= assessment.video.frame_count:
                issues.append(
                    _issue(
                        issue_type="evidence_out_of_bounds",
                        severity="error",
                        message="Evidence frame is outside the video range.",
                        criterion_id=criterion.id,
                        score_id=score.id,
                        evidence_id=evidence.id,
                    )
                )
            elif evidence.end_frame_exclusive is not None and (
                evidence.end_frame_exclusive <= evidence.start_frame
                or evidence.end_frame_exclusive > assessment.video.frame_count
            ):
                issues.append(
                    _issue(
                        issue_type="evidence_out_of_bounds",
                        severity="error",
                        message="Evidence frame is outside the video range.",
                        criterion_id=criterion.id,
                        score_id=score.id,
                        evidence_id=evidence.id,
                    )
                )

    issues = _sort_issues(issues)
    counts = _count_issues(issues)
    completion_percent = round((required_completed / required_total) * 100, 2) if required_total else 100.0
    has_error = counts.error > 0
    has_warning = counts.warning > 0
    return ResearchSkillValidationResponse(
        assessment_id=assessment.id,
        revision=assessment.revision,
        status=assessment.status,
        required_total=required_total,
        required_completed=required_completed,
        completion_percent=completion_percent,
        issue_counts=counts,
        issues=issues,
        is_valid=not has_error,
        can_submit=not has_error,
        requires_warning_confirmation=not has_error and has_warning,
    )


def _get_assessment_for_validation(db: Session, assessment_id: int) -> ResearchSkillAssessment:
    assessment = db.scalar(
        select(ResearchSkillAssessment)
        .where(ResearchSkillAssessment.id == assessment_id)
        .options(
            selectinload(ResearchSkillAssessment.video),
            selectinload(ResearchSkillAssessment.rubric)
            .selectinload(ResearchSkillRubric.criteria)
            .selectinload(ResearchSkillCriterion.phase_label_links),
            selectinload(ResearchSkillAssessment.phase_annotation_set)
            .selectinload(ResearchPhaseAnnotationSet.segments)
            .selectinload(ResearchPhaseSegment.phase_label),
            selectinload(ResearchSkillAssessment.scores).selectinload(ResearchSkillScore.criterion),
            selectinload(ResearchSkillAssessment.scores).selectinload(ResearchSkillScore.phase_segment),
            selectinload(ResearchSkillAssessment.scores).selectinload(ResearchSkillScore.evidence),
        )
    )
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill assessment not found.")
    return assessment


def _issue(
    *,
    issue_type: str,
    severity: str,
    message: str,
    criterion_id: int | None = None,
    score_id: int | None = None,
    phase_segment_id: int | None = None,
    evidence_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> ResearchSkillValidationIssue:
    return ResearchSkillValidationIssue(
        issue_type=issue_type,
        severity=severity,
        message=message,
        criterion_id=criterion_id,
        score_id=score_id,
        phase_segment_id=phase_segment_id,
        evidence_id=evidence_id,
        details=details or {},
    )


def _phase_segments(assessment: ResearchSkillAssessment) -> list[ResearchPhaseSegment]:
    if assessment.phase_annotation_set is None:
        return []
    return sorted(assessment.phase_annotation_set.segments, key=lambda item: (item.start_frame, item.id))


def _criterion_applies_to_segment(criterion: ResearchSkillCriterion, segment: ResearchPhaseSegment) -> bool:
    label_ids = {link.phase_label_id for link in criterion.phase_label_links}
    return not label_ids or segment.phase_label_id in label_ids


def _score_complete(score: ResearchSkillScore | None) -> bool:
    return score is not None and (score.is_na or score.value_json is not None)


def _validate_stored_score(
    assessment: ResearchSkillAssessment,
    criterion: ResearchSkillCriterion,
    score: ResearchSkillScore,
) -> list[ResearchSkillValidationIssue]:
    issues: list[ResearchSkillValidationIssue] = []
    if score.is_na:
        if not criterion.allow_na:
            issues.append(_issue(issue_type="na_not_allowed", severity="error", message="This criterion does not allow N/A.", criterion_id=criterion.id, score_id=score.id))
        if score.value_json is not None:
            issues.append(_issue(issue_type="invalid_value", severity="error", message="N/A scores cannot also store a value.", criterion_id=criterion.id, score_id=score.id))
        return issues
    if not _stored_value_valid(criterion, score.value_json):
        issues.append(_issue(issue_type="invalid_value", severity="error", message="Stored score value is invalid.", criterion_id=criterion.id, score_id=score.id))
    if criterion.scope == "overall":
        if score.target_key != "overall" or score.phase_segment_id is not None:
            issues.append(_issue(issue_type="phase_score_without_segment", severity="error", message="Overall criteria must use the overall target.", criterion_id=criterion.id, score_id=score.id))
    else:
        if score.phase_segment_id is None:
            issues.append(_issue(issue_type="phase_score_without_segment", severity="error", message="Phase criteria require a phase segment.", criterion_id=criterion.id, score_id=score.id))
            return issues
        if assessment.phase_annotation_set_id is None:
            issues.append(_issue(issue_type="assessment_phase_set_missing", severity="error", message="A phase annotation set is required for phase-level scores.", criterion_id=criterion.id, score_id=score.id, phase_segment_id=score.phase_segment_id))
            return issues
        if score.phase_segment is None or score.phase_segment.annotation_set_id != assessment.phase_annotation_set_id:
            issues.append(_issue(issue_type="segment_not_in_selected_phase_set", severity="error", message="The scored segment is not in the selected phase annotation set.", criterion_id=criterion.id, score_id=score.id, phase_segment_id=score.phase_segment_id))
        elif not _criterion_applies_to_segment(criterion, score.phase_segment):
            issues.append(_issue(issue_type="criterion_not_applicable", severity="error", message="This criterion does not apply to the selected phase segment.", criterion_id=criterion.id, score_id=score.id, phase_segment_id=score.phase_segment_id))
    return issues


def _stored_value_valid(criterion: ResearchSkillCriterion, value: Any) -> bool:
    if value is None:
        return False
    if criterion.score_type == "integer_scale":
        return isinstance(value, int) and not isinstance(value, bool) and _numeric_value_valid(float(value), criterion)
    if criterion.score_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and _numeric_value_valid(float(value), criterion)
    if criterion.score_type == "single_choice":
        return isinstance(value, str) and value in {str(option.get("value")) for option in (criterion.options_json or [])}
    if criterion.score_type == "boolean":
        return isinstance(value, bool)
    if criterion.score_type == "text":
        return isinstance(value, str) and bool(value.strip()) and len(value) <= 5000
    return False


def _numeric_value_valid(value: float, criterion: ResearchSkillCriterion) -> bool:
    if criterion.min_value is not None and value < criterion.min_value:
        return False
    if criterion.max_value is not None and value > criterion.max_value:
        return False
    if criterion.step is not None and criterion.step > 0 and criterion.min_value is not None:
        quotient = (value - criterion.min_value) / criterion.step
        if abs(quotient - round(quotient)) > 1e-7:
            return False
    return True


def _count_issues(issues: list[ResearchSkillValidationIssue]) -> ResearchSkillValidationIssueCounts:
    counts = {"error": 0, "warning": 0, "info": 0}
    for issue in issues:
        counts[issue.severity] += 1
    return ResearchSkillValidationIssueCounts(**counts)


def _sort_issues(issues: list[ResearchSkillValidationIssue]) -> list[ResearchSkillValidationIssue]:
    return sorted(
        issues,
        key=lambda issue: (
            VALIDATION_SEVERITY_ORDER[issue.severity],
            issue.criterion_id is None,
            issue.criterion_id if issue.criterion_id is not None else math.inf,
            issue.phase_segment_id is None,
            issue.phase_segment_id if issue.phase_segment_id is not None else math.inf,
            issue.score_id is None,
            issue.score_id if issue.score_id is not None else math.inf,
            issue.evidence_id is None,
            issue.evidence_id if issue.evidence_id is not None else math.inf,
            issue.issue_type,
        ),
    )
