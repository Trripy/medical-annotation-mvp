from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.db.base import Base
from app.models import ResearchSkillAssessment, ResearchSkillEvidence
from app.schemas.research_skill import (
    CreateResearchSkillEvidenceRequest,
    UpdateResearchSkillEvidenceRequest,
    UpsertResearchSkillScoreRequest,
)
from app.services.research_skill_service import (
    create_skill_evidence,
    delete_skill_evidence,
    update_skill_evidence,
    upsert_skill_score,
)
from tests._research_skill_test_utils import create_skill_session_factory, seed_skill_data


@pytest.fixture()
def skill_db(tmp_path):
    engine, session_factory = create_skill_session_factory(tmp_path)
    seeded = seed_skill_data(session_factory)
    try:
        with session_factory() as db:
            score_response = upsert_skill_score(
                db,
                seeded.active_assessment_id,
                seeded.overall_required_criterion_id,
                UpsertResearchSkillScoreRequest(target_type="overall", value=4, expected_revision=1),
            )
            yield db, seeded, score_response.created_score_ids[0]
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_point_interval_update_and_delete_evidence(skill_db) -> None:
    db, seeded, score_id = skill_db

    point = create_skill_evidence(
        db,
        score_id,
        CreateResearchSkillEvidenceRequest(start_frame=10, comment="point", expected_revision=2),
    )
    evidence_id = point.created_evidence_ids[0]
    interval = update_skill_evidence(
        db,
        evidence_id,
        UpdateResearchSkillEvidenceRequest(start_frame=12, end_frame_exclusive=20, comment="interval", expected_revision=3),
    )
    point_again = update_skill_evidence(
        db,
        evidence_id,
        UpdateResearchSkillEvidenceRequest(clear_end_frame=True, clear_comment=True, expected_revision=4),
    )
    deleted = delete_skill_evidence(db, evidence_id, expected_revision=5)

    assert point.action == "evidence_created"
    assert point.assessment.revision == 3
    assert interval.action == "evidence_updated"
    assert interval.assessment.revision == 4
    assert point_again.assessment.scores[0].evidence[0].end_frame_exclusive is None
    assert point_again.assessment.scores[0].evidence[0].comment is None
    assert point_again.assessment.revision == 5
    assert deleted.action == "evidence_deleted"
    assert deleted.assessment.revision == 6
    assert db.get(ResearchSkillEvidence, evidence_id) is None
    assert db.get(ResearchSkillAssessment, seeded.active_assessment_id).revision == 6


@pytest.mark.parametrize(
    ("start_frame", "end_frame_exclusive"),
    [
        (-1, None),
        (300, None),
        (10, 10),
        (10, 301),
    ],
)
def test_evidence_range_validation_rollback(skill_db, start_frame, end_frame_exclusive) -> None:
    db, seeded, score_id = skill_db

    with pytest.raises(HTTPException) as exc_info:
        create_skill_evidence(
            db,
            score_id,
            CreateResearchSkillEvidenceRequest(
                start_frame=start_frame,
                end_frame_exclusive=end_frame_exclusive,
                expected_revision=2,
            ),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Evidence frame is outside the video range."
    assert db.get(ResearchSkillAssessment, seeded.active_assessment_id).revision == 2
    assert db.query(ResearchSkillEvidence).count() == 0


def test_evidence_revision_conflict_and_submitted_read_only(skill_db) -> None:
    db, seeded, score_id = skill_db
    created = create_skill_evidence(
        db,
        score_id,
        CreateResearchSkillEvidenceRequest(start_frame=5, expected_revision=2),
    )
    evidence_id = created.created_evidence_ids[0]

    with pytest.raises(HTTPException) as conflict:
        update_skill_evidence(
            db,
            evidence_id,
            UpdateResearchSkillEvidenceRequest(start_frame=6, expected_revision=99),
        )
    assert conflict.value.status_code == 409
    assert conflict.value.detail["message"] == "Skill assessment revision conflict."

    assessment = db.get(ResearchSkillAssessment, seeded.active_assessment_id)
    assert assessment is not None
    assessment.status = "submitted"
    db.commit()
    with pytest.raises(HTTPException) as read_only:
        delete_skill_evidence(db, evidence_id, expected_revision=3)
    assert read_only.value.status_code == 409
