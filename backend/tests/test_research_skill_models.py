from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.models import (
    ResearchSkillAssessment,
    ResearchSkillCriterion,
    ResearchSkillEvidence,
    ResearchSkillRubric,
    ResearchSkillScore,
)
from tests._research_skill_test_utils import create_skill_session_factory, seed_skill_data


def test_research_skill_tables_are_registered_in_metadata() -> None:
    assert {
        "research_skill_rubrics",
        "research_skill_criteria",
        "research_skill_criterion_phase_labels",
        "research_skill_assessments",
        "research_skill_scores",
        "research_skill_evidence",
    }.issubset(Base.metadata.tables)


@pytest.mark.parametrize(
    "entity",
    [
        ResearchSkillRubric(name="Core Cataract Skill", version=1, status="draft"),
        ResearchSkillCriterion(rubric_id=1, key="global_rating", name="Duplicate", scope="overall", score_type="integer_scale", min_value=1, max_value=5, step=1, display_order=10),
        ResearchSkillAssessment(video_id=1, rubric_id=1, rater_id=1, revision=1, status="draft"),
    ],
)
def test_research_skill_unique_constraints(tmp_path, entity) -> None:
    engine, session_factory = create_skill_session_factory(tmp_path)
    seed_skill_data(session_factory)
    try:
        with session_factory() as db:
            db.add(entity)
            with pytest.raises(IntegrityError):
                db.commit()
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_research_skill_score_unique_constraint(tmp_path) -> None:
    engine, session_factory = create_skill_session_factory(tmp_path)
    seeded = seed_skill_data(session_factory)
    try:
        with session_factory() as db:
            db.add(
                ResearchSkillScore(
                    assessment_id=seeded.active_assessment_id,
                    criterion_id=seeded.overall_required_criterion_id,
                    target_key="overall",
                    value_json=4,
                )
            )
            db.commit()
            db.add(
                ResearchSkillScore(
                    assessment_id=seeded.active_assessment_id,
                    criterion_id=seeded.overall_required_criterion_id,
                    target_key="overall",
                    value_json=5,
                )
            )
            with pytest.raises(IntegrityError):
                db.commit()
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.mark.parametrize(
    "entity",
    [
        ResearchSkillRubric(name="Bad Version", version=0, status="draft"),
        ResearchSkillRubric(name="Bad Status", version=1, status="invalid"),
        ResearchSkillCriterion(rubric_id=1, key="bad_scope", name="Bad Scope", scope="bad", score_type="text", display_order=0),
        ResearchSkillCriterion(rubric_id=1, key="bad_type", name="Bad Type", scope="overall", score_type="bad", display_order=0),
        ResearchSkillCriterion(rubric_id=1, key="bad_order", name="Bad Order", scope="overall", score_type="text", display_order=-1),
        ResearchSkillCriterion(rubric_id=1, key="bad_weight", name="Bad Weight", scope="overall", score_type="text", display_order=0, weight=-0.1),
        ResearchSkillAssessment(video_id=1, rubric_id=1, rater_id=1, revision=0, status="draft"),
        ResearchSkillAssessment(video_id=1, rubric_id=1, rater_id=1, revision=1, status="bad"),
        ResearchSkillEvidence(skill_score_id=1, start_frame=-1),
        ResearchSkillEvidence(skill_score_id=1, start_frame=5, end_frame_exclusive=5),
    ],
)
def test_research_skill_check_constraints(tmp_path, entity) -> None:
    engine, session_factory = create_skill_session_factory(tmp_path)
    seed_skill_data(session_factory)
    try:
        with session_factory() as db:
            db.add(entity)
            with pytest.raises(IntegrityError):
                db.commit()
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_research_skill_fk_delete_policies(tmp_path) -> None:
    engine, session_factory = create_skill_session_factory(tmp_path)
    seeded = seed_skill_data(session_factory)
    try:
        with session_factory() as db:
            rubric = db.get(ResearchSkillRubric, seeded.active_rubric_id)
            assert rubric is not None
            db.delete(rubric)
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()

            assessment = db.get(ResearchSkillAssessment, seeded.active_assessment_id)
            assert assessment is not None
            db.delete(assessment)
            db.commit()
            assert db.get(ResearchSkillAssessment, seeded.active_assessment_id) is None
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
