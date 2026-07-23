from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.db.base import Base
from app.models import ResearchSkillAssessment, ResearchSkillScore
from app.schemas.research_skill import UpsertResearchSkillScoreRequest
from app.services.research_skill_service import delete_skill_score, upsert_skill_score
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


def test_overall_score_create_update_unchanged_and_delete(skill_db) -> None:
    db, seeded = skill_db

    created = upsert_skill_score(
        db,
        seeded.active_assessment_id,
        seeded.overall_required_criterion_id,
        UpsertResearchSkillScoreRequest(target_type="overall", value=4, expected_revision=1),
    )
    score_id = created.created_score_ids[0]
    updated = upsert_skill_score(
        db,
        seeded.active_assessment_id,
        seeded.overall_required_criterion_id,
        UpsertResearchSkillScoreRequest(target_type="overall", value=5, comment="Good\ncomment", expected_revision=2),
    )
    unchanged = upsert_skill_score(
        db,
        seeded.active_assessment_id,
        seeded.overall_required_criterion_id,
        UpsertResearchSkillScoreRequest(target_type="overall", value=5, comment="Good\ncomment", expected_revision=3),
    )
    deleted = delete_skill_score(db, score_id, expected_revision=3)

    assert created.action == "created"
    assert created.assessment.revision == 2
    assert updated.action == "updated"
    assert updated.assessment.revision == 3
    assert unchanged.action == "unchanged"
    assert unchanged.assessment.revision == 3
    assert deleted.action == "deleted"
    assert deleted.assessment.revision == 4
    assert db.get(ResearchSkillScore, score_id) is None


def test_score_comment_only_update_preserves_existing_value(skill_db) -> None:
    db, seeded = skill_db

    created = upsert_skill_score(
        db,
        seeded.active_assessment_id,
        seeded.overall_required_criterion_id,
        UpsertResearchSkillScoreRequest(target_type="overall", value=4, expected_revision=1),
    )
    score_id = created.created_score_ids[0]

    updated = upsert_skill_score(
        db,
        seeded.active_assessment_id,
        seeded.overall_required_criterion_id,
        UpsertResearchSkillScoreRequest(target_type="overall", comment="Comment only", expected_revision=2),
    )
    unchanged = upsert_skill_score(
        db,
        seeded.active_assessment_id,
        seeded.overall_required_criterion_id,
        UpsertResearchSkillScoreRequest(target_type="overall", comment="Comment only", expected_revision=3),
    )
    cleared = upsert_skill_score(
        db,
        seeded.active_assessment_id,
        seeded.overall_required_criterion_id,
        UpsertResearchSkillScoreRequest(target_type="overall", clear_comment=True, expected_revision=3),
    )

    assert updated.action == "updated"
    assert updated.assessment.revision == 3
    assert unchanged.action == "unchanged"
    assert unchanged.assessment.revision == 3
    assert cleared.action == "updated"
    assert cleared.assessment.revision == 4
    score = db.get(ResearchSkillScore, score_id)
    assert score is not None
    assert score.value_json == 4
    assert score.is_na is False
    assert score.comment is None


def test_phase_score_and_applicable_label_validation(skill_db) -> None:
    db, seeded = skill_db

    created = upsert_skill_score(
        db,
        seeded.active_assessment_id,
        seeded.phase_required_criterion_id,
        UpsertResearchSkillScoreRequest(
            target_type="phase_segment",
            phase_segment_id=seeded.segment_ids["incision"],
            value=8.5,
            expected_revision=1,
        ),
    )
    with pytest.raises(HTTPException) as wrong_segment:
        upsert_skill_score(
            db,
            seeded.active_assessment_id,
            seeded.phase_required_criterion_id,
            UpsertResearchSkillScoreRequest(
                target_type="phase_segment",
                phase_segment_id=seeded.segment_ids["idle"],
                value=8,
                expected_revision=2,
            ),
        )

    assert created.action == "created"
    assert created.assessment.scores[0].target_key == f"segment:{seeded.segment_ids['incision']}"
    assert wrong_segment.value.status_code == 409
    assert wrong_segment.value.detail == "This criterion does not apply to the selected phase segment."
    assert created.assessment.revision == 2
    assert db.get(ResearchSkillAssessment, seeded.active_assessment_id).revision == 2


@pytest.mark.parametrize(
    ("criterion_attr", "value"),
    [
        ("overall_required_criterion_id", 3),
        ("choice_criterion_id", "good"),
        ("boolean_criterion_id", False),
        ("text_criterion_id", "Competent"),
    ],
)
def test_score_type_validation_accepts_valid_values(skill_db, criterion_attr, value) -> None:
    db, seeded = skill_db

    response = upsert_skill_score(
        db,
        seeded.active_assessment_id,
        getattr(seeded, criterion_attr),
        UpsertResearchSkillScoreRequest(target_type="overall", value=value, expected_revision=1),
    )

    assert response.action == "created"
    assert response.assessment.scores[0].value == value


@pytest.mark.parametrize(
    ("criterion_attr", "value"),
    [
        ("overall_required_criterion_id", True),
        ("overall_required_criterion_id", 3.5),
        ("choice_criterion_id", "missing"),
        ("boolean_criterion_id", 1),
        ("text_criterion_id", ""),
    ],
)
def test_score_type_validation_rejects_invalid_values(skill_db, criterion_attr, value) -> None:
    db, seeded = skill_db

    with pytest.raises(HTTPException) as exc_info:
        upsert_skill_score(
            db,
            seeded.active_assessment_id,
            getattr(seeded, criterion_attr),
            UpsertResearchSkillScoreRequest(target_type="overall", value=value, expected_revision=1),
        )

    assert exc_info.value.status_code == 422
    assert db.get(ResearchSkillAssessment, seeded.active_assessment_id).revision == 1


def test_na_rules_and_target_type_errors(skill_db) -> None:
    db, seeded = skill_db

    na = upsert_skill_score(
        db,
        seeded.active_assessment_id,
        seeded.text_criterion_id,
        UpsertResearchSkillScoreRequest(target_type="overall", is_na=True, expected_revision=1),
    )
    with pytest.raises(HTTPException) as na_not_allowed:
        upsert_skill_score(
            db,
            seeded.active_assessment_id,
            seeded.overall_required_criterion_id,
            UpsertResearchSkillScoreRequest(target_type="overall", is_na=True, expected_revision=2),
        )
    with pytest.raises(HTTPException) as na_with_value:
        upsert_skill_score(
            db,
            seeded.active_assessment_id,
            seeded.text_criterion_id,
            UpsertResearchSkillScoreRequest(target_type="overall", is_na=True, value="x", expected_revision=2),
        )
    with pytest.raises(HTTPException) as wrong_target:
        upsert_skill_score(
            db,
            seeded.active_assessment_id,
            seeded.overall_required_criterion_id,
            UpsertResearchSkillScoreRequest(target_type="phase_segment", phase_segment_id=seeded.segment_ids["incision"], value=4, expected_revision=2),
        )

    assert na.action == "created"
    assert na.assessment.revision == 2
    assert na_not_allowed.value.status_code == 422
    assert na_with_value.value.status_code == 422
    assert wrong_target.value.status_code == 409
    assert db.get(ResearchSkillAssessment, seeded.active_assessment_id).revision == 2


def test_revision_conflict_submitted_read_only_and_failed_mutation_rollback(skill_db) -> None:
    db, seeded = skill_db

    with pytest.raises(HTTPException) as conflict:
        upsert_skill_score(
            db,
            seeded.active_assessment_id,
            seeded.overall_required_criterion_id,
            UpsertResearchSkillScoreRequest(target_type="overall", value=4, expected_revision=99),
        )
    assert conflict.value.detail["message"] == "Skill assessment revision conflict."
    assert db.query(ResearchSkillScore).count() == 0

    assessment = db.get(ResearchSkillAssessment, seeded.active_assessment_id)
    assert assessment is not None
    assessment.status = "submitted"
    db.commit()
    with pytest.raises(HTTPException) as read_only:
        upsert_skill_score(
            db,
            seeded.active_assessment_id,
            seeded.overall_required_criterion_id,
            UpsertResearchSkillScoreRequest(target_type="overall", value=4, expected_revision=1),
        )
    assert read_only.value.status_code == 409
