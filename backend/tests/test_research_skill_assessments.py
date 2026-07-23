from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.db.base import Base
from app.models import ResearchSkillAssessment, ResearchSkillScore
from app.schemas.research_skill import CreateResearchSkillAssessmentRequest, UpdateResearchSkillAssessmentRequest
from app.services.research_skill_service import (
    get_or_create_skill_assessment,
    get_skill_assessment,
    update_skill_assessment,
)
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


def test_create_assessment_get_or_create_and_detail(skill_db) -> None:
    db, seeded = skill_db

    first = get_or_create_skill_assessment(
        db,
        seeded.video_id,
        CreateResearchSkillAssessmentRequest(
            rubric_id=seeded.active_rubric_id,
            username="reviewer",
            phase_annotation_set_id=seeded.submitted_phase_set_id,
        ),
    )
    second = get_or_create_skill_assessment(
        db,
        seeded.video_id,
        CreateResearchSkillAssessmentRequest(
            rubric_id=seeded.active_rubric_id,
            username="reviewer",
            phase_annotation_set_id=seeded.submitted_phase_set_id,
        ),
    )
    detail = get_skill_assessment(db, first.assessment.id)

    assert first.created is True
    assert second.created is False
    assert second.assessment.id == first.assessment.id
    assert first.assessment.rater_id == seeded.reviewer_user_id
    assert first.assessment.id != seeded.active_assessment_id
    assert detail.phase_annotation_set is not None
    assert detail.phase_annotation_set.id == seeded.submitted_phase_set_id
    assert detail.scores == []
    assert detail.completion.required_total >= 1


def test_create_assessment_rejects_missing_or_non_active_inputs(skill_db) -> None:
    db, seeded = skill_db
    cases = [
        (999999, CreateResearchSkillAssessmentRequest(rubric_id=seeded.active_rubric_id, username="reader"), 404),
        (seeded.video_id, CreateResearchSkillAssessmentRequest(rubric_id=seeded.active_rubric_id, username="missing"), 404),
        (seeded.video_id, CreateResearchSkillAssessmentRequest(rubric_id=seeded.draft_rubric_id, username="reader"), 409),
        (seeded.video_id, CreateResearchSkillAssessmentRequest(rubric_id=seeded.archived_rubric_id, username="reader"), 409),
        (seeded.video_id, CreateResearchSkillAssessmentRequest(rubric_id=seeded.active_rubric_id, username=" "), 422),
    ]

    for video_id, payload, expected_status in cases:
        with pytest.raises(HTTPException) as exc_info:
            get_or_create_skill_assessment(db, video_id, payload)
        assert exc_info.value.status_code == expected_status


def test_create_assessment_phase_set_validation(skill_db) -> None:
    db, seeded = skill_db

    with pytest.raises(HTTPException) as cross_video:
        get_or_create_skill_assessment(
            db,
            seeded.video_id,
            CreateResearchSkillAssessmentRequest(
                rubric_id=seeded.active_rubric_id,
                username="reviewer",
                phase_annotation_set_id=seeded.other_video_phase_set_id,
            ),
        )
    assert cross_video.value.status_code == 409
    assert cross_video.value.detail == "The selected phase annotation set does not belong to this video."


def test_update_assessment_comment_and_clear_phase_set_rules(skill_db) -> None:
    db, seeded = skill_db

    updated = update_skill_assessment(
        db,
        seeded.active_assessment_id,
        UpdateResearchSkillAssessmentRequest(overall_comment="Updated", expected_revision=1),
    )
    unchanged = update_skill_assessment(
        db,
        seeded.active_assessment_id,
        UpdateResearchSkillAssessmentRequest(overall_comment="Updated", expected_revision=2),
    )
    cleared = update_skill_assessment(
        db,
        seeded.active_assessment_id,
        UpdateResearchSkillAssessmentRequest(clear_overall_comment=True, clear_phase_annotation_set=True, expected_revision=2),
    )

    assert updated.action == "updated"
    assert updated.assessment.revision == 2
    assert unchanged.action == "unchanged"
    assert unchanged.assessment.revision == 2
    assert cleared.assessment.overall_comment is None
    assert cleared.assessment.phase_annotation_set_id is None
    assert cleared.assessment.revision == 3


def test_clear_phase_set_rejects_existing_phase_scores(skill_db) -> None:
    db, seeded = skill_db
    db.add(
        ResearchSkillScore(
            assessment_id=seeded.active_assessment_id,
            criterion_id=seeded.phase_required_criterion_id,
            target_key=f"segment:{seeded.segment_ids['incision']}",
            phase_segment_id=seeded.segment_ids["incision"],
            value_json=8,
        )
    )
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        update_skill_assessment(
            db,
            seeded.active_assessment_id,
            UpdateResearchSkillAssessmentRequest(clear_phase_annotation_set=True, expected_revision=1),
        )

    assert exc_info.value.status_code == 409


def test_assessment_revision_conflict_and_submitted_read_only(skill_db) -> None:
    db, seeded = skill_db

    with pytest.raises(HTTPException) as conflict:
        update_skill_assessment(
            db,
            seeded.active_assessment_id,
            UpdateResearchSkillAssessmentRequest(overall_comment="Conflict", expected_revision=99),
        )
    assert conflict.value.status_code == 409
    assert conflict.value.detail["message"] == "Skill assessment revision conflict."
    assert conflict.value.detail["current_revision"] == 1

    assessment = db.get(ResearchSkillAssessment, seeded.active_assessment_id)
    assert assessment is not None
    assessment.status = "submitted"
    db.commit()

    with pytest.raises(HTTPException) as read_only:
        update_skill_assessment(
            db,
            seeded.active_assessment_id,
            UpdateResearchSkillAssessmentRequest(overall_comment="No", expected_revision=1),
        )
    assert read_only.value.status_code == 409
    assert read_only.value.detail == "Only draft skill assessments can be modified."
