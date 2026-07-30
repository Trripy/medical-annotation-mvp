from __future__ import annotations

import pytest

from app.db.base import Base
from app.models import (
    ResearchSkillAssessment,
    ResearchSkillCriterion,
    ResearchSkillEvidence,
    ResearchSkillRubric,
    ResearchSkillScore,
)
from scripts.data.ico_cataract_skill_rubric_zh_cn import CRITERIA, RUBRIC, SCORE_OPTIONS
from scripts.seed_ico_cataract_skill_rubric import (
    compare_rubric,
    database_fingerprint,
    expected_fingerprint,
    fingerprint_payload,
    load_rubric,
    seed_ico_cataract_skill_rubric,
    validate_embedded_rubric_data,
)
from tests._research_skill_test_utils import create_skill_session_factory, seed_skill_data


@pytest.fixture()
def skill_db(tmp_path):
    engine, session_factory = create_skill_session_factory(tmp_path)
    seed_skill_data(session_factory)
    try:
        with session_factory() as db:
            yield db
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def counts(db) -> dict[str, int]:
    return {
        "rubrics": db.query(ResearchSkillRubric).count(),
        "criteria": db.query(ResearchSkillCriterion).count(),
        "assessments": db.query(ResearchSkillAssessment).count(),
        "scores": db.query(ResearchSkillScore).count(),
        "evidence": db.query(ResearchSkillEvidence).count(),
    }


def test_embedded_data_contains_20_complete_criteria() -> None:
    validate_embedded_rubric_data()

    keys = [criterion["key"] for criterion in CRITERIA]
    names = [criterion["name"] for criterion in CRITERIA]
    assert len(CRITERIA) == 20
    assert len(set(keys)) == 20
    assert len(set(names)) == 20
    assert [criterion["display_order"] for criterion in CRITERIA] == list(range(20))
    assert all(criterion["scope"] == "overall" for criterion in CRITERIA)
    assert all(criterion["score_type"] == "single_choice" for criterion in CRITERIA)
    assert all(criterion["required"] is True for criterion in CRITERIA)
    assert all(criterion["allow_na"] is False for criterion in CRITERIA)
    assert all(criterion["weight"] == 1.0 for criterion in CRITERIA)
    assert [option["value"] for option in SCORE_OPTIONS] == ["0", "2", "3", "4", "5"]
    for criterion in CRITERIA:
        assert [option["value"] for option in criterion["options_json"]] == ["0", "2", "3", "4", "5"]
        assert "1" not in [option["value"] for option in criterion["options_json"]]
        assert criterion["description"].startswith("评分标准：")
        for score_label in ("0 分", "2 分", "3 分", "4 分", "5 分"):
            assert score_label in criterion["description"]
        assert len(criterion["description"]) > 50


def test_fingerprint_is_stable() -> None:
    first = expected_fingerprint()
    second = expected_fingerprint()

    assert first == second
    assert len(first) == 64
    assert fingerprint_payload(RUBRIC) == first


def test_dry_run_does_not_write_database(skill_db) -> None:
    before = counts(skill_db)

    result = seed_ico_cataract_skill_rubric(
        skill_db,
        creator_username="reader",
        apply=False,
        activate=True,
    )

    assert result.action == "would_create"
    assert result.database_writes == 0
    assert counts(skill_db) == before


def test_first_import_creates_and_activates_rubric_without_assessments(skill_db) -> None:
    before = counts(skill_db)

    result = seed_ico_cataract_skill_rubric(
        skill_db,
        creator_username="reader",
        apply=True,
        activate=True,
    )
    rubric = load_rubric(skill_db)
    after = counts(skill_db)

    assert result.action == "created"
    assert result.match is True
    assert rubric is not None
    assert rubric.status == "active"
    assert rubric.name == RUBRIC["name"]
    assert rubric.version == RUBRIC["version"]
    assert rubric.phase_protocol_id is None
    assert len(rubric.criteria) == 20
    assert [criterion.display_order for criterion in rubric.criteria] == list(range(20))
    assert [option["value"] for option in rubric.criteria[0].options_json] == ["0", "2", "3", "4", "5"]
    assert after["rubrics"] == before["rubrics"] + 1
    assert after["criteria"] == before["criteria"] + 20
    assert after["assessments"] == before["assessments"]
    assert after["scores"] == before["scores"]
    assert after["evidence"] == before["evidence"]


def test_second_import_is_idempotent_for_matching_active_rubric(skill_db) -> None:
    seed_ico_cataract_skill_rubric(skill_db, creator_username="reader", apply=True, activate=True)
    before = counts(skill_db)

    result = seed_ico_cataract_skill_rubric(
        skill_db,
        creator_username="reader",
        apply=True,
        activate=True,
    )

    assert result.action == "already_exists"
    assert result.match is True
    assert counts(skill_db) == before


def test_active_rubric_with_different_content_is_not_modified(skill_db) -> None:
    seed_ico_cataract_skill_rubric(skill_db, creator_username="reader", apply=True, activate=True)
    rubric = load_rubric(skill_db)
    assert rubric is not None
    rubric.criteria[0].description = "changed"
    skill_db.commit()
    before = counts(skill_db)

    with pytest.raises(RuntimeError, match="Active iCO rubric exists but does not match"):
        seed_ico_cataract_skill_rubric(skill_db, creator_username="reader", apply=True, activate=True)

    assert counts(skill_db) == before


def test_draft_partial_import_is_repaired_and_activated(skill_db) -> None:
    rubric = ResearchSkillRubric(
        name=RUBRIC["name"],
        version=RUBRIC["version"],
        description="partial",
        status="draft",
    )
    skill_db.add(rubric)
    skill_db.commit()
    skill_db.add(
        ResearchSkillCriterion(
            rubric_id=rubric.id,
            key=CRITERIA[0]["key"],
            name="old name",
            description="old",
            scope="overall",
            score_type="single_choice",
            options_json=[{"value": "old", "label": "Old"}],
            required=False,
            allow_na=True,
            weight=2.0,
            display_order=9,
            is_active=False,
        )
    )
    skill_db.commit()

    result = seed_ico_cataract_skill_rubric(skill_db, creator_username="reader", apply=True, activate=True)
    repaired = load_rubric(skill_db)

    assert result.action == "updated"
    assert repaired is not None
    assert repaired.status == "active"
    assert len(repaired.criteria) == 20
    assert database_fingerprint(repaired) == expected_fingerprint()


def test_draft_with_extra_criterion_stops_without_deleting(skill_db) -> None:
    rubric = ResearchSkillRubric(name=RUBRIC["name"], version=RUBRIC["version"], status="draft")
    skill_db.add(rubric)
    skill_db.commit()
    skill_db.add(
        ResearchSkillCriterion(
            rubric_id=rubric.id,
            key="unexpected",
            name="Unexpected",
            scope="overall",
            score_type="text",
            display_order=0,
        )
    )
    skill_db.commit()
    before = counts(skill_db)

    with pytest.raises(RuntimeError, match="extra criterion keys"):
        seed_ico_cataract_skill_rubric(skill_db, creator_username="reader", apply=True, activate=True)

    assert counts(skill_db) == before
    assert compare_rubric(load_rubric(skill_db))["extra_keys"] == ["unexpected"]


def test_archived_rubric_is_not_reactivated(skill_db) -> None:
    rubric = ResearchSkillRubric(name=RUBRIC["name"], version=RUBRIC["version"], status="archived")
    skill_db.add(rubric)
    skill_db.commit()
    before = counts(skill_db)

    with pytest.raises(RuntimeError, match="Archived iCO rubric exists"):
        seed_ico_cataract_skill_rubric(skill_db, creator_username="reader", apply=True, activate=True)

    assert counts(skill_db) == before


def test_seed_never_creates_assessment_score_or_evidence(skill_db) -> None:
    before = counts(skill_db)

    seed_ico_cataract_skill_rubric(skill_db, creator_username="reader", apply=True, activate=True)
    after = counts(skill_db)

    assert after["assessments"] == before["assessments"]
    assert after["scores"] == before["scores"]
    assert after["evidence"] == before["evidence"]
