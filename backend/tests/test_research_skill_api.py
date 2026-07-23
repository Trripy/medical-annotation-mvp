from __future__ import annotations

import pytest
from fastapi import FastAPI

from app.api.v1 import research
from app.db.base import Base
from app.db.session import get_db
from app.schemas.research_skill import CreateResearchSkillEvidenceRequest, UpsertResearchSkillScoreRequest
from app.services.research_skill_service import create_skill_evidence, upsert_skill_score
from tests._asgi_test_utils import asgi_request
from tests._research_skill_test_utils import create_skill_session_factory, seed_skill_data


@pytest.fixture()
def skill_api_context(tmp_path):
    engine, session_factory = create_skill_session_factory(tmp_path)
    seeded = seed_skill_data(session_factory)
    test_app = FastAPI()
    test_app.include_router(research.router, prefix="/api/research")
    test_app.state.skill_session_factory = session_factory

    async def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    test_app.dependency_overrides[get_db] = override_get_db
    try:
        yield test_app, seeded
    finally:
        test_app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def create_complete_assessment_for_api(app: FastAPI, seeded) -> tuple[int, int]:
    with app.state.skill_session_factory() as db:
        response = upsert_skill_score(
            db,
            seeded.active_assessment_id,
            seeded.overall_required_criterion_id,
            UpsertResearchSkillScoreRequest(target_type="overall", value=4, expected_revision=1),
        )
        score_id = response.created_score_ids[0]
        response = upsert_skill_score(
            db,
            seeded.active_assessment_id,
            seeded.phase_required_criterion_id,
            UpsertResearchSkillScoreRequest(
                target_type="phase_segment",
                phase_segment_id=seeded.segment_ids["incision"],
                value=8,
                expected_revision=response.assessment.revision,
            ),
        )
        response = upsert_skill_score(
            db,
            seeded.active_assessment_id,
            seeded.phase_required_criterion_id,
            UpsertResearchSkillScoreRequest(
                target_type="phase_segment",
                phase_segment_id=seeded.segment_ids["phaco"],
                value=7,
                expected_revision=response.assessment.revision,
            ),
        )
        create_skill_evidence(
            db,
            score_id,
            CreateResearchSkillEvidenceRequest(start_frame=1, end_frame_exclusive=5, expected_revision=response.assessment.revision),
        )
        return score_id, response.assessment.revision + 1


def test_skill_api_rubric_routes_and_openapi(skill_api_context) -> None:
    app, seeded = skill_api_context

    create_response = asgi_request(
        app,
        "POST",
        "/api/research/skill-rubrics",
        json_body={"name": "API Rubric", "phase_protocol_id": seeded.protocol_id, "username": "reader"},
    )
    rubric_id = create_response.json()["id"]
    criterion_response = asgi_request(
        app,
        "POST",
        f"/api/research/skill-rubrics/{rubric_id}/criteria",
        json_body={"key": "api_text", "name": "API Text", "scope": "overall", "score_type": "text", "display_order": 0},
    )
    activate_response = asgi_request(app, "POST", f"/api/research/skill-rubrics/{rubric_id}/activate")
    clone_response = asgi_request(app, "POST", f"/api/research/skill-rubrics/{rubric_id}/clone", json_body={})
    archive_response = asgi_request(app, "POST", f"/api/research/skill-rubrics/{rubric_id}/archive")
    list_response = asgi_request(app, "GET", "/api/research/skill-rubrics", params={"include_archived": "true"})
    openapi_response = asgi_request(app, "GET", "/openapi.json")

    assert create_response.status_code == 201
    assert criterion_response.status_code == 201
    assert activate_response.status_code == 200
    assert activate_response.json()["rubric"]["status"] == "active"
    assert clone_response.status_code == 200
    assert clone_response.json()["status"] == "draft"
    assert archive_response.status_code == 200
    assert archive_response.json()["rubric"]["status"] == "archived"
    assert rubric_id in {item["id"] for item in list_response.json()}
    paths = openapi_response.json()["paths"]
    assert "/api/research/skill-rubrics" in paths
    assert "/api/research/skill-assessments/{assessment_id}/export/csv" in paths


def test_skill_api_assessment_score_evidence_and_status_routes(skill_api_context) -> None:
    app, seeded = skill_api_context

    create_response = asgi_request(
        app,
        "POST",
        f"/api/research/videos/{seeded.video_id}/skill-assessments",
        json_body={
            "rubric_id": seeded.active_rubric_id,
            "username": "reviewer",
            "phase_annotation_set_id": seeded.submitted_phase_set_id,
        },
    )
    assessment_id = create_response.json()["assessment"]["id"]
    score_response = asgi_request(
        app,
        "PUT",
        f"/api/research/skill-assessments/{assessment_id}/scores/{seeded.overall_required_criterion_id}",
        json_body={"target_type": "overall", "value": 5, "expected_revision": 1},
    )
    score_id = score_response.json()["created_score_ids"][0]
    evidence_response = asgi_request(
        app,
        "POST",
        f"/api/research/skill-scores/{score_id}/evidence",
        json_body={"start_frame": 2, "end_frame_exclusive": 4, "expected_revision": 2},
    )
    evidence_id = evidence_response.json()["created_evidence_ids"][0]
    update_response = asgi_request(
        app,
        "PATCH",
        f"/api/research/skill-evidence/{evidence_id}",
        json_body={"clear_end_frame": True, "expected_revision": 3},
    )
    delete_evidence_response = asgi_request(
        app,
        "DELETE",
        f"/api/research/skill-evidence/{evidence_id}",
        params={"expected_revision": 4},
    )
    delete_score_response = asgi_request(
        app,
        "DELETE",
        f"/api/research/skill-scores/{score_id}",
        params={"expected_revision": 5},
    )
    patch_response = asgi_request(
        app,
        "PATCH",
        f"/api/research/skill-assessments/{assessment_id}",
        json_body={"overall_comment": "Updated", "expected_revision": 6},
    )
    detail_response = asgi_request(app, "GET", f"/api/research/skill-assessments/{assessment_id}")
    list_response = asgi_request(app, "GET", f"/api/research/videos/{seeded.video_id}/skill-assessments")

    assert create_response.status_code == 200
    assert create_response.json()["created"] is True
    assert score_response.status_code == 200
    assert evidence_response.status_code == 201
    assert update_response.status_code == 200
    assert delete_evidence_response.status_code == 200
    assert delete_score_response.status_code == 200
    assert patch_response.status_code == 200
    assert patch_response.json()["assessment"]["revision"] == 7
    assert detail_response.status_code == 200
    assert list_response.status_code == 200
    assert assessment_id in {item["id"] for item in list_response.json()}


def test_skill_api_errors_revision_conflict_and_warning_confirmation(skill_api_context) -> None:
    app, seeded = skill_api_context

    missing = asgi_request(app, "GET", "/api/research/skill-assessments/999999")
    invalid_username = asgi_request(
        app,
        "POST",
        f"/api/research/videos/{seeded.video_id}/skill-assessments",
        json_body={"rubric_id": seeded.active_rubric_id, "username": " "},
    )
    conflict = asgi_request(
        app,
        "PUT",
        f"/api/research/skill-assessments/{seeded.active_assessment_id}/scores/{seeded.overall_required_criterion_id}",
        json_body={"target_type": "overall", "value": 4, "expected_revision": 999},
    )
    _score_id, revision = create_complete_assessment_for_api(app, seeded)
    warning = asgi_request(
        app,
        "POST",
        f"/api/research/skill-assessments/{seeded.active_assessment_id}/submit",
        json_body={"expected_revision": revision, "confirm_warnings": False},
    )
    submitted = asgi_request(
        app,
        "POST",
        f"/api/research/skill-assessments/{seeded.active_assessment_id}/submit",
        json_body={"expected_revision": revision, "confirm_warnings": True},
    )
    reopened = asgi_request(
        app,
        "POST",
        f"/api/research/skill-assessments/{seeded.active_assessment_id}/reopen",
        json_body={"expected_revision": submitted.json()["assessment"]["revision"]},
    )

    assert missing.status_code == 404
    assert invalid_username.status_code == 422
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["message"] == "Skill assessment revision conflict."
    assert warning.status_code == 409
    assert warning.json()["detail"]["message"] == "Skill assessment has warnings that require confirmation."
    assert warning.json()["detail"]["validation"]["requires_warning_confirmation"] is True
    assert submitted.status_code == 200
    assert submitted.json()["action"] == "submitted"
    assert reopened.status_code == 200
    assert reopened.json()["action"] == "reopened"


def test_skill_api_exports(skill_api_context) -> None:
    app, seeded = skill_api_context
    create_complete_assessment_for_api(app, seeded)

    json_response = asgi_request(app, "GET", f"/api/research/skill-assessments/{seeded.active_assessment_id}/export/json")
    csv_response = asgi_request(app, "GET", f"/api/research/skill-assessments/{seeded.active_assessment_id}/export/csv")

    assert json_response.status_code == 200
    assert json_response.headers["content-type"].startswith("application/json")
    assert "filename*=" in json_response.headers["content-disposition"]
    assert "file_path" not in json_response.text
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert "filename*=" in csv_response.headers["content-disposition"]
    assert csv_response.body.startswith(b"\xef\xbb\xbf")
    assert b"global_rating" in csv_response.body
