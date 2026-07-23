from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.api.v1 import research
from app.db.base import Base
from app.db.session import get_db
from app.main import app as main_app
from app.models import ResearchPhaseAnnotationSet, ResearchPhaseLabel, ResearchPhaseSegment, ResearchVideo, User
from app.services.download_filenames import build_attachment_content_disposition, sanitize_filename
from tests._asgi_test_utils import asgi_request
from tests._research_phase_test_utils import create_phase_session_factory, seed_phase_data


@pytest.fixture()
def phase_api_context(tmp_path):
    engine, session_factory = create_phase_session_factory(tmp_path)
    seeded = seed_phase_data(session_factory)

    test_app = FastAPI()
    test_app.include_router(research.router, prefix="/api/research")
    test_app.state.phase_session_factory = session_factory

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


def create_api_annotation_set(
    app: FastAPI,
    seeded,
    *,
    username: str,
    protocol_id: int | None = None,
    status: str = "draft",
    revision: int = 1,
    submitted_at: datetime | None = None,
) -> int:
    session_factory = app.state.phase_session_factory
    with session_factory() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            user = User(username=username, email=f"{username}@example.com", full_name=username.title())
            db.add(user)
            db.flush()

        annotation_set = ResearchPhaseAnnotationSet(
            video_id=seeded.video_id,
            protocol_id=protocol_id or seeded.active_default_protocol_id,
            annotator_id=user.id,
            status=status,
            revision=revision,
            submitted_at=submitted_at if submitted_at is not None else (datetime.now(timezone.utc) if status != "draft" else None),
        )
        db.add(annotation_set)
        db.commit()
        db.refresh(annotation_set)
        return annotation_set.id


def create_api_label(
    app: FastAPI,
    *,
    protocol_id: int,
    key: str,
    name: str,
    display_order: int,
    color: str,
    is_active: bool,
) -> int:
    session_factory = app.state.phase_session_factory
    with session_factory() as db:
        label = ResearchPhaseLabel(
            protocol_id=protocol_id,
            key=key,
            name=name,
            color=color,
            display_order=display_order,
            is_active=is_active,
        )
        db.add(label)
        db.commit()
        db.refresh(label)
        return label.id


def create_api_segment(
    app: FastAPI,
    *,
    annotation_set_id: int,
    phase_label_id: int,
    start_frame: int,
    end_frame_exclusive: int | None,
    source: str = "manual",
    confidence: float | None = None,
    notes: str | None = None,
) -> int:
    session_factory = app.state.phase_session_factory
    with session_factory() as db:
        segment = ResearchPhaseSegment(
            annotation_set_id=annotation_set_id,
            phase_label_id=phase_label_id,
            start_frame=start_frame,
            end_frame_exclusive=end_frame_exclusive,
            source=source,
            confidence=confidence,
            notes=notes,
        )
        db.add(segment)
        db.commit()
        db.refresh(segment)
        return segment.id


def get_api_segment_id_by_start(app: FastAPI, annotation_set_id: int, start_frame: int) -> int:
    session_factory = app.state.phase_session_factory
    with session_factory() as db:
        segment = db.scalar(
            select(ResearchPhaseSegment).where(
                ResearchPhaseSegment.annotation_set_id == annotation_set_id,
                ResearchPhaseSegment.start_frame == start_frame,
            )
        )
        assert segment is not None
        return segment.id


def update_api_video(app: FastAPI, video_id: int, **changes) -> None:
    session_factory = app.state.phase_session_factory
    with session_factory() as db:
        video = db.get(ResearchVideo, video_id)
        assert video is not None
        for key, value in changes.items():
            setattr(video, key, value)
        db.commit()


def parse_csv_rows(csv_bytes: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(csv_bytes.decode("utf-8-sig"))))


def test_list_phase_protocols_endpoint_returns_200_and_excludes_archived_by_default(phase_api_context) -> None:
    app, seeded = phase_api_context

    response = asgi_request(app, "GET", "/api/research/phase-protocols")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == [
        seeded.active_default_protocol_id,
        seeded.active_alpha_v2_protocol_id,
        seeded.active_alpha_v1_protocol_id,
        seeded.draft_protocol_id,
    ]
    assert all(item["id"] != seeded.archived_protocol_id for item in payload)
    assert "file_path" not in response.text


def test_list_phase_protocols_endpoint_supports_include_archived_and_status_filters(phase_api_context) -> None:
    app, seeded = phase_api_context

    include_archived_response = asgi_request(
        app,
        "GET",
        "/api/research/phase-protocols",
        params={"include_archived": "true"},
    )
    archived_only_response = asgi_request(
        app,
        "GET",
        "/api/research/phase-protocols",
        params={"status": "archived"},
    )

    assert include_archived_response.status_code == 200
    include_archived_payload = include_archived_response.json()
    assert [item["id"] for item in include_archived_payload] == [
        seeded.active_default_protocol_id,
        seeded.active_alpha_v2_protocol_id,
        seeded.active_alpha_v1_protocol_id,
        seeded.draft_protocol_id,
        seeded.archived_protocol_id,
    ]

    assert archived_only_response.status_code == 200
    assert [item["id"] for item in archived_only_response.json()] == [seeded.archived_protocol_id]


def test_list_phase_protocols_endpoint_rejects_invalid_status_filter(phase_api_context) -> None:
    app, _seeded = phase_api_context

    response = asgi_request(
        app,
        "GET",
        "/api/research/phase-protocols",
        params={"status": "invalid"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid protocol status filter."}


def test_get_phase_protocol_detail_endpoint_returns_sorted_labels(phase_api_context) -> None:
    app, seeded = phase_api_context

    response = asgi_request(
        app,
        "GET",
        f"/api/research/phase-protocols/{seeded.active_default_protocol_id}",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == seeded.active_default_protocol_id
    assert payload["label_count"] == 3
    assert [label["key"] for label in payload["labels"]] == ["idle", "viscoelastic", "incision"]
    assert [label["display_order"] for label in payload["labels"]] == [0, 1, 1]
    assert "file_path" not in response.text


def test_get_phase_protocol_detail_endpoint_returns_404_for_missing_protocol(phase_api_context) -> None:
    app, _seeded = phase_api_context

    response = asgi_request(app, "GET", "/api/research/phase-protocols/999999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Phase protocol not found."}


def test_list_video_phase_annotation_sets_endpoint_returns_all_sets(phase_api_context) -> None:
    app, seeded = phase_api_context

    response = asgi_request(
        app,
        "GET",
        f"/api/research/videos/{seeded.video_id}/phase-annotation-sets",
    )

    assert response.status_code == 200
    payload = response.json()
    assert {item["id"] for item in payload} == {seeded.set_reader_id, seeded.set_reviewer_id}
    assert {item["annotator_username"] for item in payload} == {"reader", "reviewer"}
    by_id = {item["id"]: item for item in payload}
    assert by_id[seeded.set_reader_id]["segment_count"] == 2
    assert by_id[seeded.set_reader_id]["has_open_segment"] is True
    assert by_id[seeded.set_reviewer_id]["segment_count"] == 1
    assert by_id[seeded.set_reviewer_id]["has_open_segment"] is False
    assert "file_path" not in response.text


def test_list_video_phase_annotation_sets_endpoint_returns_404_for_missing_video(phase_api_context) -> None:
    app, _seeded = phase_api_context

    response = asgi_request(app, "GET", "/api/research/videos/999999/phase-annotation-sets")

    assert response.status_code == 404
    assert response.json() == {"detail": "Research video not found."}


def test_create_or_get_phase_annotation_set_endpoint_is_idempotent(phase_api_context) -> None:
    app, seeded = phase_api_context

    first_response = asgi_request(
        app,
        "POST",
        f"/api/research/videos/{seeded.video_id}/phase-annotation-sets",
        json_body={"protocol_id": seeded.active_alpha_v2_protocol_id, "username": "reader"},
    )
    second_response = asgi_request(
        app,
        "POST",
        f"/api/research/videos/{seeded.video_id}/phase-annotation-sets",
        json_body={"protocol_id": seeded.active_alpha_v2_protocol_id, "username": "reader"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    first_payload = first_response.json()
    second_payload = second_response.json()
    assert first_payload["created"] is True
    assert second_payload["created"] is False
    assert second_payload["annotation_set"]["id"] == first_payload["annotation_set"]["id"]
    assert second_payload["annotation_set"]["segment_count"] == 0
    assert second_payload["annotation_set"]["segments"] == []


@pytest.mark.parametrize("protocol_attribute", ["draft_protocol_id", "archived_protocol_id"])
def test_create_or_get_phase_annotation_set_endpoint_rejects_non_active_protocols(
    phase_api_context,
    protocol_attribute: str,
) -> None:
    app, seeded = phase_api_context

    response = asgi_request(
        app,
        "POST",
        f"/api/research/videos/{seeded.video_id}/phase-annotation-sets",
        json_body={"protocol_id": getattr(seeded, protocol_attribute), "username": "reader"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "New annotation sets can only use an active phase protocol."}


def test_create_or_get_phase_annotation_set_endpoint_rejects_missing_user(phase_api_context) -> None:
    app, seeded = phase_api_context

    response = asgi_request(
        app,
        "POST",
        f"/api/research/videos/{seeded.video_id}/phase-annotation-sets",
        json_body={"protocol_id": seeded.active_alpha_v2_protocol_id, "username": "ghost"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found."}


def test_create_or_get_phase_annotation_set_endpoint_rejects_blank_username(phase_api_context) -> None:
    app, seeded = phase_api_context

    response = asgi_request(
        app,
        "POST",
        f"/api/research/videos/{seeded.video_id}/phase-annotation-sets",
        json_body={"protocol_id": seeded.active_alpha_v2_protocol_id, "username": "   "},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Username cannot be empty."}


def test_create_or_get_phase_annotation_set_endpoint_returns_404_for_missing_video(phase_api_context) -> None:
    app, seeded = phase_api_context

    response = asgi_request(
        app,
        "POST",
        "/api/research/videos/999999/phase-annotation-sets",
        json_body={"protocol_id": seeded.active_alpha_v2_protocol_id, "username": "reader"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Research video not found."}


def test_get_phase_annotation_set_endpoint_returns_segments_without_paths(phase_api_context) -> None:
    app, seeded = phase_api_context

    response = asgi_request(
        app,
        "GET",
        f"/api/research/phase-annotation-sets/{seeded.set_reader_id}",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == seeded.set_reader_id
    assert [segment["start_frame"] for segment in payload["segments"]] == [10, 120]
    assert payload["segments"][0]["phase_label"]["key"] == "idle"
    assert payload["segments"][1]["phase_label"]["key"] == "viscoelastic"
    assert "file_path" not in response.text
    assert "/tmp/phase-test" not in response.text


def test_validate_phase_annotation_set_endpoint_returns_issue_counts_and_coverage(phase_api_context) -> None:
    app, seeded = phase_api_context

    response = asgi_request(
        app,
        "GET",
        f"/api/research/phase-annotation-sets/{seeded.set_reader_id}/validate",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["annotation_set_id"] == seeded.set_reader_id
    assert payload["revision"] == 1
    assert payload["status"] == "draft"
    assert payload["closed_covered_frame_count"] == 50
    assert payload["closed_coverage_percent"] == 12.5
    assert payload["issue_counts"]["error"] >= 1
    assert any(issue["issue_type"] == "open_segment" for issue in payload["issues"])
    assert "file_path" not in response.text
    assert "/tmp/phase-test" not in response.text


def test_validate_phase_annotation_set_endpoint_returns_no_segments_for_empty_set(phase_api_context) -> None:
    app, seeded = phase_api_context
    annotation_set_id = create_api_annotation_set(app, seeded, username="api_validate_empty")

    response = asgi_request(
        app,
        "GET",
        f"/api/research/phase-annotation-sets/{annotation_set_id}/validate",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["annotation_set_id"] == annotation_set_id
    assert payload["segment_count"] == 0
    assert payload["issues"][0]["issue_type"] == "no_segments"
    assert payload["closed_coverage_percent"] == 0.0


def test_validate_phase_annotation_set_endpoint_does_not_change_revision_or_status(phase_api_context) -> None:
    app, seeded = phase_api_context
    session_factory = app.state.phase_session_factory

    with session_factory() as db:
        annotation_set = db.get(ResearchPhaseAnnotationSet, seeded.set_reader_id)
        assert annotation_set is not None
        before_revision = annotation_set.revision
        before_status = annotation_set.status

    response = asgi_request(
        app,
        "GET",
        f"/api/research/phase-annotation-sets/{seeded.set_reader_id}/validate",
    )

    with session_factory() as db:
        annotation_set = db.get(ResearchPhaseAnnotationSet, seeded.set_reader_id)
        assert annotation_set is not None
        after_revision = annotation_set.revision
        after_status = annotation_set.status

    assert response.status_code == 200
    assert before_revision == after_revision == 1
    assert before_status == after_status == "draft"


def test_validate_phase_annotation_set_endpoint_returns_404_for_missing_set(phase_api_context) -> None:
    app, _seeded = phase_api_context

    response = asgi_request(
        app,
        "GET",
        "/api/research/phase-annotation-sets/999999/validate",
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Phase annotation set not found."}


def test_submit_phase_annotation_set_endpoint_returns_200(phase_api_context) -> None:
    app, seeded = phase_api_context
    annotation_set_id = create_api_annotation_set(app, seeded, username="api_submit_ok")
    create_api_segment(
        app,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=0,
        end_frame_exclusive=150,
    )
    create_api_segment(
        app,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["viscoelastic"],
        start_frame=150,
        end_frame_exclusive=400,
    )

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-annotation-sets/{annotation_set_id}/submit",
        json_body={"expected_revision": 1, "confirm_warnings": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "submitted"
    assert payload["annotation_set"]["status"] == "submitted"
    assert payload["annotation_set"]["revision"] == 2
    assert payload["annotation_set"]["submitted_at"] is not None
    assert payload["validation"]["status"] == "submitted"
    assert payload["validation"]["revision"] == 2


def test_submit_phase_annotation_set_endpoint_requires_warning_confirmation(phase_api_context) -> None:
    app, seeded = phase_api_context
    annotation_set_id = create_api_annotation_set(app, seeded, username="api_submit_warning")
    create_api_segment(
        app,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=400,
    )

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-annotation-sets/{annotation_set_id}/submit",
        json_body={"expected_revision": 1, "confirm_warnings": False},
    )

    assert response.status_code == 409
    payload = response.json()
    assert payload["detail"]["message"] == "Phase annotation set has warnings that require confirmation."
    assert payload["detail"]["validation"]["revision"] == 1


def test_submit_phase_annotation_set_endpoint_accepts_confirmed_warnings(phase_api_context) -> None:
    app, seeded = phase_api_context
    annotation_set_id = create_api_annotation_set(app, seeded, username="api_submit_confirmed_warning")
    create_api_segment(
        app,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=400,
    )

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-annotation-sets/{annotation_set_id}/submit",
        json_body={"expected_revision": 1, "confirm_warnings": True},
    )

    assert response.status_code == 200
    assert response.json()["annotation_set"]["status"] == "submitted"


def test_submit_phase_annotation_set_endpoint_rejects_validation_errors(phase_api_context) -> None:
    app, seeded = phase_api_context
    annotation_set_id = create_api_annotation_set(app, seeded, username="api_submit_error")

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-annotation-sets/{annotation_set_id}/submit",
        json_body={"expected_revision": 1, "confirm_warnings": True},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["message"] == "Phase annotation set has validation errors."


def test_submit_phase_annotation_set_endpoint_returns_revision_conflict(phase_api_context) -> None:
    app, seeded = phase_api_context
    annotation_set_id = create_api_annotation_set(app, seeded, username="api_submit_conflict")
    create_api_segment(
        app,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=0,
        end_frame_exclusive=400,
    )

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-annotation-sets/{annotation_set_id}/submit",
        json_body={"expected_revision": 999, "confirm_warnings": False},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "message": "Phase annotation set revision conflict.",
            "current_revision": 1,
        }
    }


def test_reopen_phase_annotation_set_endpoint_returns_200_and_clears_submitted_at(phase_api_context) -> None:
    app, seeded = phase_api_context
    annotation_set_id = create_api_annotation_set(
        app,
        seeded,
        username="api_reopen_ok",
        status="submitted",
        revision=4,
    )

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-annotation-sets/{annotation_set_id}/reopen",
        json_body={"expected_revision": 4},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "reopened"
    assert payload["annotation_set"]["status"] == "draft"
    assert payload["annotation_set"]["revision"] == 5
    assert payload["annotation_set"]["submitted_at"] is None
    assert payload["validation"] is None


def test_export_phase_annotation_set_json_endpoint_returns_utf8_json(phase_api_context) -> None:
    app, seeded = phase_api_context
    update_api_video(app, seeded.video_id, name="张玉柱 手术")

    response = asgi_request(
        app,
        "GET",
        f"/api/research/phase-annotation-sets/{seeded.set_reader_id}/export/json",
    )

    expected_filename = f"{sanitize_filename('张玉柱 手术', fallback=f'video_{seeded.video_id}')}_phases.json"
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["content-disposition"] == build_attachment_content_disposition(
        expected_filename,
        f"video_{seeded.video_id}_phases.json",
    )
    assert "file_path" not in response.text
    assert "thumbnail_path" not in response.text
    assert "张玉柱 手术" in response.text


def test_export_phase_annotation_set_segments_csv_endpoint_returns_bom(phase_api_context) -> None:
    app, seeded = phase_api_context

    response = asgi_request(
        app,
        "GET",
        f"/api/research/phase-annotation-sets/{seeded.set_reader_id}/export/segments",
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv; charset=utf-8")
    assert response.body.startswith(b"\xef\xbb\xbf")
    rows = parse_csv_rows(response.body)
    assert rows[0][0] == "video_id"
    assert rows[1][13] == "idle"


def test_export_phase_annotation_set_framewise_csv_endpoint_returns_streaming_body_and_validation_headers(
    phase_api_context,
) -> None:
    app, seeded = phase_api_context
    update_api_video(app, seeded.video_id, frame_count=6, fps=2.0)
    annotation_set_id = create_api_annotation_set(app, seeded, username="api_framewise")
    create_api_segment(
        app,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=1,
        end_frame_exclusive=3,
    )
    create_api_segment(
        app,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["viscoelastic"],
        start_frame=4,
        end_frame_exclusive=None,
    )

    response = asgi_request(
        app,
        "GET",
        f"/api/research/phase-annotation-sets/{annotation_set_id}/export/framewise",
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv; charset=utf-8")
    assert response.headers["x-phase-validation-errors"] == "1"
    assert response.headers["x-phase-validation-warnings"] == "3"
    rows = parse_csv_rows(response.body)
    assert len(rows) == 7
    assert rows[1] == ["0", "0", "unlabeled", "Unlabeled", "", "", "draft"]
    assert rows[6][2] == "viscoelastic"


def test_export_phase_annotation_set_endpoint_returns_404_for_missing_set(phase_api_context) -> None:
    app, _seeded = phase_api_context

    response = asgi_request(
        app,
        "GET",
        "/api/research/phase-annotation-sets/999999/export/json",
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Phase annotation set not found."}


def test_create_phase_segment_endpoint_returns_200_with_latest_detail(phase_api_context) -> None:
    app, seeded = phase_api_context

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-annotation-sets/{seeded.set_reader_id}/segments",
        json_body={
            "phase_label_id": seeded.active_default_label_ids["incision"],
            "start_frame": 60,
            "end_frame_exclusive": 80,
            "expected_revision": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "created"
    assert payload["annotation_set"]["revision"] == 2
    assert (60, 80) in [
        (segment["start_frame"], segment["end_frame_exclusive"])
        for segment in payload["annotation_set"]["segments"]
    ]
    assert "file_path" not in response.text


def test_transition_phase_endpoint_returns_latest_detail(phase_api_context) -> None:
    app, seeded = phase_api_context

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-annotation-sets/{seeded.set_reader_id}/transition",
        json_body={
            "phase_label_id": seeded.active_default_label_ids["incision"],
            "current_frame": 150,
            "expected_revision": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "transitioned"
    assert payload["annotation_set"]["revision"] == 2
    assert [
        (segment["start_frame"], segment["end_frame_exclusive"], segment["phase_label"]["key"])
        for segment in payload["annotation_set"]["segments"]
    ] == [
        (10, 60, "idle"),
        (120, 150, "viscoelastic"),
        (150, None, "incision"),
    ]


def test_transition_phase_endpoint_returns_unchanged_for_same_label(phase_api_context) -> None:
    app, seeded = phase_api_context

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-annotation-sets/{seeded.set_reader_id}/transition",
        json_body={
            "phase_label_id": seeded.active_default_label_ids["viscoelastic"],
            "current_frame": 150,
            "expected_revision": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "unchanged"
    assert payload["annotation_set"]["revision"] == 1
    assert payload["changed_segment_ids"] == []
    assert payload["created_segment_ids"] == []


def test_close_active_phase_segment_endpoint_returns_closed_state(phase_api_context) -> None:
    app, seeded = phase_api_context

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-annotation-sets/{seeded.set_reader_id}/close-active",
        json_body={
            "end_frame_exclusive": 180,
            "expected_revision": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "closed"
    assert payload["annotation_set"]["revision"] == 2
    assert payload["annotation_set"]["has_open_segment"] is False
    assert [
        (segment["start_frame"], segment["end_frame_exclusive"])
        for segment in payload["annotation_set"]["segments"]
    ] == [(10, 60), (120, 180)]


def test_update_phase_segment_endpoint_returns_updated_detail(phase_api_context) -> None:
    app, seeded = phase_api_context
    segment_id = get_api_segment_id_by_start(app, seeded.set_reader_id, 10)

    response = asgi_request(
        app,
        "PATCH",
        f"/api/research/phase-segments/{segment_id}",
        json_body={
            "start_frame": 15,
            "end_frame_exclusive": 70,
            "expected_revision": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "updated"
    assert payload["annotation_set"]["revision"] == 2
    assert [
        (segment["start_frame"], segment["end_frame_exclusive"])
        for segment in payload["annotation_set"]["segments"]
    ] == [(15, 70), (120, None)]


def test_phase_mutation_endpoint_returns_revision_conflict(phase_api_context) -> None:
    app, seeded = phase_api_context
    annotation_set_id = create_api_annotation_set(app, seeded, username="api_conflict")

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-annotation-sets/{annotation_set_id}/segments",
        json_body={
            "phase_label_id": seeded.active_default_label_ids["idle"],
            "start_frame": 20,
            "end_frame_exclusive": 40,
            "expected_revision": 999,
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "message": "Phase annotation set revision conflict.",
            "current_revision": 1,
        }
    }


def test_phase_mutation_endpoint_rejects_invalid_frame(phase_api_context) -> None:
    app, seeded = phase_api_context

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-annotation-sets/{seeded.set_reader_id}/segments",
        json_body={
            "phase_label_id": seeded.active_default_label_ids["idle"],
            "start_frame": -1,
            "end_frame_exclusive": 40,
            "expected_revision": 1,
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Start frame is out of bounds."}


def test_phase_mutation_endpoint_rejects_inactive_label(phase_api_context) -> None:
    app, seeded = phase_api_context
    inactive_label_id = create_api_label(
        app,
        protocol_id=seeded.active_default_protocol_id,
        key="inactive_api_label",
        name="Inactive API Label",
        display_order=10,
        color="#6b7280",
        is_active=False,
    )

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-annotation-sets/{seeded.set_reader_id}/segments",
        json_body={
            "phase_label_id": inactive_label_id,
            "start_frame": 70,
            "end_frame_exclusive": 90,
            "expected_revision": 1,
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Inactive phase labels cannot be used."}


def test_delete_phase_segment_endpoint_uses_query_expected_revision_and_returns_deleted_ids(
    phase_api_context,
) -> None:
    app, seeded = phase_api_context
    segment_id = get_api_segment_id_by_start(app, seeded.set_reader_id, 10)

    response = asgi_request(
        app,
        "DELETE",
        f"/api/research/phase-segments/{segment_id}",
        params={"expected_revision": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "deleted"
    assert payload["deleted_segment_ids"] == [segment_id]
    assert payload["annotation_set"]["revision"] == 2
    assert "file_path" not in response.text


def test_split_phase_segment_endpoint_returns_original_and_new_segment(phase_api_context) -> None:
    app, seeded = phase_api_context
    segment_id = get_api_segment_id_by_start(app, seeded.set_reader_id, 10)

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-segments/{segment_id}/split",
        json_body={"split_frame": 30, "expected_revision": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "split"
    assert payload["changed_segment_ids"] == [segment_id]
    assert len(payload["created_segment_ids"]) == 1
    created_segment_id = payload["created_segment_ids"][0]
    assert created_segment_id != segment_id
    assert [
        (segment["id"], segment["start_frame"], segment["end_frame_exclusive"])
        for segment in payload["annotation_set"]["segments"]
    ] == [
        (segment_id, 10, 30),
        (created_segment_id, 30, 60),
        (get_api_segment_id_by_start(app, seeded.set_reader_id, 120), 120, None),
    ]


def test_split_open_phase_segment_endpoint_returns_new_open_segment(phase_api_context) -> None:
    app, seeded = phase_api_context
    segment_id = get_api_segment_id_by_start(app, seeded.set_reader_id, 120)

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-segments/{segment_id}/split",
        json_body={"split_frame": 150, "expected_revision": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "split"
    assert [
        (segment["start_frame"], segment["end_frame_exclusive"])
        for segment in payload["annotation_set"]["segments"]
    ] == [(10, 60), (120, 150), (150, None)]


def test_merge_phase_segments_endpoint_returns_left_segment_and_deletes_right(phase_api_context) -> None:
    app, seeded = phase_api_context
    annotation_set_id = create_api_annotation_set(app, seeded, username="api_merge_closed")
    left_id = create_api_segment(
        app,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=20,
        notes="left",
    )
    right_id = create_api_segment(
        app,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=20,
        end_frame_exclusive=40,
        notes="right",
    )

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-annotation-sets/{annotation_set_id}/merge",
        json_body={
            "left_segment_id": left_id,
            "right_segment_id": right_id,
            "expected_revision": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "merged"
    assert payload["changed_segment_ids"] == [left_id]
    assert payload["deleted_segment_ids"] == [right_id]
    assert [
        (segment["id"], segment["start_frame"], segment["end_frame_exclusive"], segment["notes"])
        for segment in payload["annotation_set"]["segments"]
    ] == [(left_id, 10, 40, "left\nright")]


def test_merge_closed_and_open_segments_endpoint_returns_open_left_segment(phase_api_context) -> None:
    app, seeded = phase_api_context
    annotation_set_id = create_api_annotation_set(app, seeded, username="api_merge_open")
    left_id = create_api_segment(
        app,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=20,
    )
    right_id = create_api_segment(
        app,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=20,
        end_frame_exclusive=None,
    )

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-annotation-sets/{annotation_set_id}/merge",
        json_body={
            "left_segment_id": left_id,
            "right_segment_id": right_id,
            "expected_revision": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [
        (segment["id"], segment["start_frame"], segment["end_frame_exclusive"])
        for segment in payload["annotation_set"]["segments"]
    ] == [(left_id, 10, None)]


def test_merge_phase_segments_endpoint_rejects_non_adjacent_segments(phase_api_context) -> None:
    app, seeded = phase_api_context
    annotation_set_id = create_api_annotation_set(app, seeded, username="api_merge_gap")
    left_id = create_api_segment(
        app,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=20,
    )
    right_id = create_api_segment(
        app,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=30,
        end_frame_exclusive=40,
    )

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-annotation-sets/{annotation_set_id}/merge",
        json_body={
            "left_segment_id": left_id,
            "right_segment_id": right_id,
            "expected_revision": 1,
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Phase segments must be strictly adjacent to merge."}


def test_merge_phase_segments_endpoint_rejects_different_labels(phase_api_context) -> None:
    app, seeded = phase_api_context
    annotation_set_id = create_api_annotation_set(app, seeded, username="api_merge_labels")
    left_id = create_api_segment(
        app,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=20,
    )
    right_id = create_api_segment(
        app,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=20,
        end_frame_exclusive=40,
    )

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-annotation-sets/{annotation_set_id}/merge",
        json_body={
            "left_segment_id": left_id,
            "right_segment_id": right_id,
            "expected_revision": 1,
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Only adjacent segments with the same phase label can be merged."}


def test_segment_operations_endpoint_returns_revision_conflict(phase_api_context) -> None:
    app, seeded = phase_api_context
    segment_id = get_api_segment_id_by_start(app, seeded.set_reader_id, 10)

    response = asgi_request(
        app,
        "DELETE",
        f"/api/research/phase-segments/{segment_id}",
        params={"expected_revision": 999},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "message": "Phase annotation set revision conflict.",
            "current_revision": 1,
        }
    }


def test_split_phase_segment_endpoint_rejects_invalid_frame(phase_api_context) -> None:
    app, seeded = phase_api_context
    segment_id = get_api_segment_id_by_start(app, seeded.set_reader_id, 10)

    response = asgi_request(
        app,
        "POST",
        f"/api/research/phase-segments/{segment_id}/split",
        json_body={"split_frame": 60, "expected_revision": 1},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Split frame must be before the segment end frame."}


def test_phase_routes_are_registered_in_main_app_openapi() -> None:
    paths = main_app.openapi()["paths"]

    assert "/api/research/phase-protocols" in paths
    assert "/api/research/phase-protocols/{protocol_id}" in paths
    assert "/api/research/videos/{video_id}/phase-annotation-sets" in paths
    assert "/api/research/phase-annotation-sets/{annotation_set_id}" in paths
    assert "/api/research/phase-annotation-sets/{annotation_set_id}/validate" in paths
    assert "/api/research/phase-annotation-sets/{annotation_set_id}/submit" in paths
    assert "/api/research/phase-annotation-sets/{annotation_set_id}/reopen" in paths
    assert "/api/research/phase-annotation-sets/{annotation_set_id}/export/json" in paths
    assert "/api/research/phase-annotation-sets/{annotation_set_id}/export/segments" in paths
    assert "/api/research/phase-annotation-sets/{annotation_set_id}/export/framewise" in paths
    assert "/api/research/phase-annotation-sets/{annotation_set_id}/segments" in paths
    assert "/api/research/phase-annotation-sets/{annotation_set_id}/transition" in paths
    assert "/api/research/phase-annotation-sets/{annotation_set_id}/close-active" in paths
    assert "/api/research/phase-segments/{segment_id}" in paths
    assert "/api/research/phase-segments/{segment_id}/split" in paths
    assert "/api/research/phase-annotation-sets/{annotation_set_id}/merge" in paths
