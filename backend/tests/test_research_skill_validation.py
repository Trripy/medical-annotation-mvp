from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.db.base import Base
from app.models import ResearchSkillAssessment, ResearchSkillEvidence, ResearchSkillRubric, ResearchSkillScore
from app.schemas.research_skill import (
    ReopenResearchSkillAssessmentRequest,
    SubmitResearchSkillAssessmentRequest,
    UpsertResearchSkillScoreRequest,
)
from app.services.research_skill_service import (
    reopen_skill_assessment,
    submit_skill_assessment,
    upsert_skill_score,
)
from app.services.research_skill_validation_service import validate_skill_assessment
from tests._research_skill_test_utils import create_skill_session_factory, seed_skill_data


@pytest.fixture()
def skill_db(tmp_path):
    engine, session_factory = create_skill_session_factory(tmp_path)
    seeded = seed_skill_data(session_factory)
    try:
        with session_factory() as db:
            yield db, seeded
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def complete_required_scores(db, seeded, *, expected_revision: int = 1) -> int:
    response = upsert_skill_score(
        db,
        seeded.active_assessment_id,
        seeded.overall_required_criterion_id,
        UpsertResearchSkillScoreRequest(target_type="overall", value=4, expected_revision=expected_revision),
    )
    revision = response.assessment.revision
    for segment_key in ("incision", "phaco"):
        response = upsert_skill_score(
            db,
            seeded.active_assessment_id,
            seeded.phase_required_criterion_id,
            UpsertResearchSkillScoreRequest(
                target_type="phase_segment",
                phase_segment_id=seeded.segment_ids[segment_key],
                value=8,
                expected_revision=revision,
            ),
        )
        revision = response.assessment.revision
    return revision


def test_validate_missing_required_phase_expansion_and_completion(skill_db) -> None:
    db, seeded = skill_db

    validation = validate_skill_assessment(db, seeded.active_assessment_id)

    assert validation.revision == 1
    assert validation.required_total == 3
    assert validation.required_completed == 0
    assert validation.completion_percent == 0
    assert validation.issue_counts.error == 3
    assert {issue.issue_type for issue in validation.issues} >= {"missing_required_score", "assessment_phase_set_draft"}
    phase_missing = [issue for issue in validation.issues if issue.phase_segment_id is not None]
    assert {issue.phase_segment_id for issue in phase_missing} == {seeded.segment_ids["incision"], seeded.segment_ids["phaco"]}
    assert seeded.segment_ids["idle"] not in {issue.phase_segment_id for issue in phase_missing}


def test_validate_na_counts_as_complete_and_read_only(skill_db) -> None:
    db, seeded = skill_db
    response = upsert_skill_score(
        db,
        seeded.active_assessment_id,
        seeded.overall_required_criterion_id,
        UpsertResearchSkillScoreRequest(target_type="overall", value=4, expected_revision=1),
    )
    response = upsert_skill_score(
        db,
        seeded.active_assessment_id,
        seeded.phase_required_criterion_id,
        UpsertResearchSkillScoreRequest(
            target_type="phase_segment",
            phase_segment_id=seeded.segment_ids["incision"],
            is_na=True,
            expected_revision=response.assessment.revision,
        ),
    )
    before_revision = response.assessment.revision

    validation = validate_skill_assessment(db, seeded.active_assessment_id)

    assert validation.required_completed == 2
    assert validation.required_total == 3
    assert validation.revision == before_revision
    assert db.get(ResearchSkillAssessment, seeded.active_assessment_id).revision == before_revision


def test_validate_detects_invalid_stored_score_missing_phase_set_inactive_criterion_and_evidence_bounds(skill_db) -> None:
    db, seeded = skill_db
    assessment = db.get(ResearchSkillAssessment, seeded.active_assessment_id)
    assert assessment is not None
    assessment.phase_annotation_set_id = None
    score = ResearchSkillScore(
        assessment_id=seeded.active_assessment_id,
        criterion_id=seeded.overall_required_criterion_id,
        target_key="overall",
        value_json=True,
    )
    inactive_score = ResearchSkillScore(
        assessment_id=seeded.active_assessment_id,
        criterion_id=seeded.text_criterion_id,
        target_key="text_target",
        value_json="Stored",
    )
    db.add_all([score, inactive_score])
    db.flush()
    criterion = inactive_score.criterion
    criterion.is_active = False
    db.add(ResearchSkillEvidence(skill_score_id=score.id, start_frame=10, end_frame_exclusive=999))
    db.commit()

    validation = validate_skill_assessment(db, seeded.active_assessment_id)
    issue_types = {issue.issue_type for issue in validation.issues}

    assert "invalid_value" in issue_types
    assert "assessment_phase_set_missing" in issue_types
    assert "inactive_criterion" in issue_types
    assert "evidence_out_of_bounds" in issue_types
    assert validation.can_submit is False


def test_submit_errors_warnings_confirmation_and_reopen(skill_db) -> None:
    db, seeded = skill_db

    with pytest.raises(HTTPException) as validation_error:
        submit_skill_assessment(
            db,
            seeded.active_assessment_id,
            SubmitResearchSkillAssessmentRequest(expected_revision=1, confirm_warnings=True),
        )
    assert validation_error.value.status_code == 409
    assert validation_error.value.detail["message"] == "Skill assessment has validation errors."

    revision = complete_required_scores(db, seeded)
    with pytest.raises(HTTPException) as warning_error:
        submit_skill_assessment(
            db,
            seeded.active_assessment_id,
            SubmitResearchSkillAssessmentRequest(expected_revision=revision),
        )
    assert warning_error.value.status_code == 409
    assert warning_error.value.detail["message"] == "Skill assessment has warnings that require confirmation."
    assert warning_error.value.detail["validation"]["requires_warning_confirmation"] is True

    submitted = submit_skill_assessment(
        db,
        seeded.active_assessment_id,
        SubmitResearchSkillAssessmentRequest(expected_revision=revision, confirm_warnings=True),
    )
    before_score_ids = [score.id for score in submitted.assessment.scores]
    reopened = reopen_skill_assessment(
        db,
        seeded.active_assessment_id,
        ReopenResearchSkillAssessmentRequest(expected_revision=submitted.assessment.revision),
    )

    assert submitted.action == "submitted"
    assert submitted.assessment.status == "submitted"
    assert submitted.assessment.revision == revision + 1
    assert submitted.assessment.submitted_at is not None
    assert [score.id for score in submitted.assessment.scores] == before_score_ids
    assert reopened.action == "reopened"
    assert reopened.assessment.status == "draft"
    assert reopened.assessment.revision == revision + 2
    assert reopened.assessment.submitted_at is None
    assert [score.id for score in reopened.assessment.scores] == before_score_ids


def test_archived_rubric_is_warning_for_existing_assessment(skill_db) -> None:
    db, seeded = skill_db
    revision = complete_required_scores(db, seeded)
    rubric = db.get(ResearchSkillRubric, seeded.active_rubric_id)
    assert rubric is not None
    rubric.status = "archived"
    db.commit()

    validation = validate_skill_assessment(db, seeded.active_assessment_id)
    submitted = submit_skill_assessment(
        db,
        seeded.active_assessment_id,
        SubmitResearchSkillAssessmentRequest(expected_revision=revision, confirm_warnings=True),
    )

    assert any(issue.issue_type == "rubric_not_active" and issue.severity == "warning" for issue in validation.issues)
    assert validation.issue_counts.error == 0
    assert submitted.assessment.status == "submitted"


def test_submit_revision_conflict_and_submitted_write_rejected(skill_db) -> None:
    db, seeded = skill_db
    revision = complete_required_scores(db, seeded)
    submitted = submit_skill_assessment(
        db,
        seeded.active_assessment_id,
        SubmitResearchSkillAssessmentRequest(expected_revision=revision, confirm_warnings=True),
    )

    with pytest.raises(HTTPException) as conflict:
        reopen_skill_assessment(
            db,
            seeded.active_assessment_id,
            ReopenResearchSkillAssessmentRequest(expected_revision=revision),
        )
    assert conflict.value.detail["message"] == "Skill assessment revision conflict."

    with pytest.raises(HTTPException) as read_only:
        upsert_skill_score(
            db,
            seeded.active_assessment_id,
            seeded.choice_criterion_id,
            UpsertResearchSkillScoreRequest(target_type="overall", value="good", expected_revision=submitted.assessment.revision),
        )
    assert read_only.value.status_code == 409
