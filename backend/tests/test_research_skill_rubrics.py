from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.db.base import Base
from app.models import ResearchSkillAssessment, ResearchSkillCriterion, ResearchSkillRubric
from app.schemas.research_skill import (
    CloneResearchSkillRubricRequest,
    CreateResearchSkillCriterionRequest,
    CreateResearchSkillRubricRequest,
    UpdateResearchSkillCriterionRequest,
    UpdateResearchSkillRubricRequest,
)
from app.services.research_skill_service import (
    activate_skill_rubric,
    archive_skill_rubric,
    clone_skill_rubric,
    create_skill_criterion,
    create_skill_rubric,
    get_skill_rubric,
    list_skill_rubrics,
    update_skill_criterion,
    update_skill_rubric,
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


def test_create_and_update_draft_rubric(skill_db) -> None:
    db, seeded = skill_db

    rubric = create_skill_rubric(
        db,
        CreateResearchSkillRubricRequest(
            name=" New Skill ",
            version=1,
            description=" Draft ",
            phase_protocol_id=seeded.protocol_id,
            username="reader",
        ),
    )
    updated = update_skill_rubric(
        db,
        rubric.id,
        UpdateResearchSkillRubricRequest(name="Updated Skill", description="Updated", phase_protocol_id=seeded.other_protocol_id),
    )

    assert rubric.status == "draft"
    assert updated.name == "Updated Skill"
    assert updated.phase_protocol_id == seeded.other_protocol_id
    assert updated.created_by_id == seeded.reader_user_id


def test_active_rubric_cannot_be_modified_and_must_be_cloned(skill_db) -> None:
    db, seeded = skill_db

    with pytest.raises(HTTPException) as exc_info:
        update_skill_rubric(db, seeded.active_rubric_id, UpdateResearchSkillRubricRequest(name="Illegal"))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Active skill rubrics must be cloned before editing."

    clone = clone_skill_rubric(db, seeded.active_rubric_id, CloneResearchSkillRubricRequest())
    assert clone.status == "draft"
    assert clone.name == "Core Cataract Skill"
    assert clone.version == 2
    assert [criterion.key for criterion in clone.criteria] == [
        "global_rating",
        "phase_safety",
        "tissue_handling",
        "complication",
        "free_text",
    ]
    phase_clone = next(criterion for criterion in clone.criteria if criterion.key == "phase_safety")
    assert set(phase_clone.phase_label_ids) == {seeded.label_ids["incision"], seeded.label_ids["phaco"]}
    assert db.query(ResearchSkillAssessment).filter(ResearchSkillAssessment.rubric_id == clone.id).count() == 0


def test_activate_archive_and_list_rubrics(skill_db) -> None:
    db, seeded = skill_db
    rubric = create_skill_rubric(db, CreateResearchSkillRubricRequest(name="Activation Target"))
    criterion = create_skill_criterion(
        db,
        rubric.id,
        CreateResearchSkillCriterionRequest(
            key="text",
            name="Text",
            scope="overall",
            score_type="text",
            display_order=0,
            required=True,
        ),
    )

    activated = activate_skill_rubric(db, rubric.id)
    archived = archive_skill_rubric(db, activated.rubric.id)
    default_list = list_skill_rubrics(db)
    archived_list = list_skill_rubrics(db, status_filter="archived")

    assert criterion.key == "text"
    assert activated.rubric.status == "active"
    assert archived.rubric.status == "archived"
    assert archived.rubric.id not in {item.id for item in default_list}
    assert archived.rubric.id in {item.id for item in archived_list}
    assert [item.name for item in default_list] == sorted([item.name for item in default_list])


def test_empty_or_invalid_rubric_cannot_activate(skill_db) -> None:
    db, _seeded = skill_db
    empty = create_skill_rubric(db, CreateResearchSkillRubricRequest(name="Empty"))
    invalid = create_skill_rubric(db, CreateResearchSkillRubricRequest(name="Invalid"))
    db.add(
        ResearchSkillCriterion(
            rubric_id=invalid.id,
            key="bad_choice",
            name="Bad Choice",
            scope="overall",
            score_type="single_choice",
            options_json=[{"value": "only", "label": "Only"}],
            display_order=0,
            is_active=True,
        )
    )
    db.commit()

    for rubric_id in (empty.id, invalid.id):
        with pytest.raises(HTTPException) as exc_info:
            activate_skill_rubric(db, rubric_id)
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == "Invalid rubric configuration."


@pytest.mark.parametrize(
    "payload",
    [
        CreateResearchSkillCriterionRequest(key="int", name="Integer", scope="overall", score_type="integer_scale", min_value=1, max_value=5, step=1, display_order=0),
        CreateResearchSkillCriterionRequest(key="num", name="Number", scope="overall", score_type="number", min_value=0, max_value=10, step=0.5, display_order=0),
        CreateResearchSkillCriterionRequest(key="choice", name="Choice", scope="overall", score_type="single_choice", options_json=[{"value": "a", "label": "A"}, {"value": "b", "label": "B"}], display_order=0),
        CreateResearchSkillCriterionRequest(key="bool", name="Boolean", scope="overall", score_type="boolean", display_order=0),
        CreateResearchSkillCriterionRequest(key="text", name="Text", scope="overall", score_type="text", display_order=0),
    ],
)
def test_valid_criterion_types(skill_db, payload) -> None:
    db, _seeded = skill_db
    rubric = create_skill_rubric(db, CreateResearchSkillRubricRequest(name=f"Rubric {payload.key}"))

    criterion = create_skill_criterion(db, rubric.id, payload)

    assert criterion.key == payload.key
    assert criterion.score_type == payload.score_type


def test_phase_criterion_label_rules(skill_db) -> None:
    db, seeded = skill_db
    no_protocol = create_skill_rubric(db, CreateResearchSkillRubricRequest(name="No Protocol"))
    with_protocol = create_skill_rubric(db, CreateResearchSkillRubricRequest(name="With Protocol", phase_protocol_id=seeded.protocol_id))

    with pytest.raises(HTTPException) as no_protocol_error:
        create_skill_criterion(
            db,
            no_protocol.id,
            CreateResearchSkillCriterionRequest(key="phase", name="Phase", scope="phase", score_type="text", display_order=0),
        )
    with pytest.raises(HTTPException) as overall_label_error:
        create_skill_criterion(
            db,
            with_protocol.id,
            CreateResearchSkillCriterionRequest(key="overall", name="Overall", scope="overall", score_type="text", display_order=0, phase_label_ids=[seeded.label_ids["idle"]]),
        )
    with pytest.raises(HTTPException) as wrong_label_error:
        create_skill_criterion(
            db,
            with_protocol.id,
            CreateResearchSkillCriterionRequest(key="wrong", name="Wrong", scope="phase", score_type="text", display_order=0, phase_label_ids=[seeded.other_label_id]),
        )

    assert no_protocol_error.value.status_code == 422
    assert overall_label_error.value.status_code == 422
    assert wrong_label_error.value.status_code == 422


def test_draft_criterion_update_supports_inactive(skill_db) -> None:
    db, _seeded = skill_db
    rubric = create_skill_rubric(db, CreateResearchSkillRubricRequest(name="Criterion Update"))
    criterion = create_skill_criterion(
        db,
        rubric.id,
        CreateResearchSkillCriterionRequest(key="text", name="Text", scope="overall", score_type="text", display_order=0),
    )

    updated = update_skill_criterion(db, criterion.id, UpdateResearchSkillCriterionRequest(is_active=False, name="Inactive Text"))

    assert updated.name == "Inactive Text"
    assert updated.is_active is False


def test_archived_rubric_cannot_be_activated(skill_db) -> None:
    db, seeded = skill_db

    with pytest.raises(HTTPException) as exc_info:
        activate_skill_rubric(db, seeded.archived_rubric_id)

    assert exc_info.value.status_code == 409
