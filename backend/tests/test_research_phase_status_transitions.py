from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import ResearchPhaseAnnotationSet, ResearchPhaseSegment, User
from app.schemas.research_phase import (
    CreateResearchPhaseSegmentRequest,
    ReopenResearchPhaseAnnotationSetRequest,
    SubmitResearchPhaseAnnotationSetRequest,
    UpdateResearchPhaseSegmentRequest,
)
from app.services.research_phase_service import (
    create_phase_segment,
    reopen_phase_annotation_set,
    submit_phase_annotation_set,
    update_phase_segment,
)
from tests._research_phase_test_utils import create_phase_session_factory, seed_phase_data


@pytest.fixture()
def phase_status_context(tmp_path):
    engine, session_factory = create_phase_session_factory(tmp_path)
    seeded = seed_phase_data(session_factory)
    try:
        yield session_factory, seeded
    finally:
        engine.dispose()


def create_annotation_set(
    session_factory,
    seeded,
    *,
    username: str,
    status: str = "draft",
    revision: int = 1,
    submitted_at: datetime | None = None,
) -> int:
    with session_factory() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            user = User(username=username, email=f"{username}@example.com", full_name=username.title())
            db.add(user)
            db.flush()

        annotation_set = ResearchPhaseAnnotationSet(
            video_id=seeded.video_id,
            protocol_id=seeded.active_default_protocol_id,
            annotator_id=user.id,
            status=status,
            revision=revision,
            submitted_at=submitted_at if submitted_at is not None else (datetime.now(timezone.utc) if status != "draft" else None),
        )
        db.add(annotation_set)
        db.commit()
        db.refresh(annotation_set)
        return annotation_set.id


def add_segment(
    session_factory,
    *,
    annotation_set_id: int,
    phase_label_id: int,
    start_frame: int,
    end_frame_exclusive: int | None,
    source: str = "manual",
    confidence: float | None = None,
    notes: str | None = None,
) -> int:
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


def seed_submittable_segments(session_factory, seeded, annotation_set_id: int) -> list[int]:
    return [
        add_segment(
            session_factory,
            annotation_set_id=annotation_set_id,
            phase_label_id=seeded.active_default_label_ids["idle"],
            start_frame=0,
            end_frame_exclusive=150,
        ),
        add_segment(
            session_factory,
            annotation_set_id=annotation_set_id,
            phase_label_id=seeded.active_default_label_ids["viscoelastic"],
            start_frame=150,
            end_frame_exclusive=400,
        ),
    ]


def get_annotation_set_snapshot(session_factory, annotation_set_id: int) -> tuple[str, int, datetime | None, list[tuple[int, int | None, int]]]:
    with session_factory() as db:
        annotation_set = db.get(ResearchPhaseAnnotationSet, annotation_set_id)
        assert annotation_set is not None
        segments = db.scalars(
            select(ResearchPhaseSegment)
            .where(ResearchPhaseSegment.annotation_set_id == annotation_set_id)
            .order_by(ResearchPhaseSegment.start_frame, ResearchPhaseSegment.id)
        ).all()
        return (
            annotation_set.status,
            annotation_set.revision,
            annotation_set.submitted_at,
            [(segment.start_frame, segment.end_frame_exclusive, segment.phase_label_id) for segment in segments],
        )


def get_segment_id_by_start(session_factory, annotation_set_id: int, start_frame: int) -> int:
    with session_factory() as db:
        segment = db.scalar(
            select(ResearchPhaseSegment).where(
                ResearchPhaseSegment.annotation_set_id == annotation_set_id,
                ResearchPhaseSegment.start_frame == start_frame,
            )
        )
        assert segment is not None
        return segment.id


def test_submit_phase_annotation_set_succeeds_without_warnings(phase_status_context) -> None:
    session_factory, seeded = phase_status_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="submit_clean")
    seed_submittable_segments(session_factory, seeded, annotation_set_id)

    with session_factory() as db:
        response = submit_phase_annotation_set(
            db,
            annotation_set_id,
            SubmitResearchPhaseAnnotationSetRequest(expected_revision=1, confirm_warnings=False),
        )

    assert response.action == "submitted"
    assert response.annotation_set.status == "submitted"
    assert response.annotation_set.revision == 2
    assert response.annotation_set.submitted_at is not None
    assert response.validation is not None
    assert response.validation.status == "submitted"
    assert response.validation.revision == 2
    assert response.validation.issue_counts.error == 0
    assert response.validation.issue_counts.warning == 0


def test_submit_phase_annotation_set_rejects_warnings_without_confirmation_and_keeps_revision(
    phase_status_context,
) -> None:
    session_factory, seeded = phase_status_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="submit_warning")
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=400,
    )
    before_snapshot = get_annotation_set_snapshot(session_factory, annotation_set_id)

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            submit_phase_annotation_set(
                db,
                annotation_set_id,
                SubmitResearchPhaseAnnotationSetRequest(expected_revision=1, confirm_warnings=False),
            )

    after_snapshot = get_annotation_set_snapshot(session_factory, annotation_set_id)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["message"] == "Phase annotation set has warnings that require confirmation."
    assert exc_info.value.detail["validation"]["revision"] == 1
    assert before_snapshot == after_snapshot


def test_submit_phase_annotation_set_allows_confirmed_warnings(phase_status_context) -> None:
    session_factory, seeded = phase_status_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="submit_confirm_warning")
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=400,
    )

    with session_factory() as db:
        response = submit_phase_annotation_set(
            db,
            annotation_set_id,
            SubmitResearchPhaseAnnotationSetRequest(expected_revision=1, confirm_warnings=True),
        )

    assert response.annotation_set.status == "submitted"
    assert response.annotation_set.revision == 2
    assert response.validation is not None
    assert response.validation.issue_counts.warning >= 1


def test_submit_phase_annotation_set_errors_cannot_be_bypassed(phase_status_context) -> None:
    session_factory, seeded = phase_status_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="submit_error")

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            submit_phase_annotation_set(
                db,
                annotation_set_id,
                SubmitResearchPhaseAnnotationSetRequest(expected_revision=1, confirm_warnings=True),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["message"] == "Phase annotation set has validation errors."


def test_empty_set_cannot_be_submitted(phase_status_context) -> None:
    session_factory, seeded = phase_status_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="submit_empty")

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            submit_phase_annotation_set(
                db,
                annotation_set_id,
                SubmitResearchPhaseAnnotationSetRequest(expected_revision=1),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["validation"]["issues"][0]["issue_type"] == "no_segments"


def test_open_segment_cannot_be_submitted(phase_status_context) -> None:
    session_factory, seeded = phase_status_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            submit_phase_annotation_set(
                db,
                seeded.set_reader_id,
                SubmitResearchPhaseAnnotationSetRequest(expected_revision=1, confirm_warnings=True),
            )

    assert exc_info.value.status_code == 409
    issue_types = {issue["issue_type"] for issue in exc_info.value.detail["validation"]["issues"]}
    assert "open_segment" in issue_types


def test_submit_phase_annotation_set_rejects_revision_conflict(phase_status_context) -> None:
    session_factory, seeded = phase_status_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="submit_conflict")
    seed_submittable_segments(session_factory, seeded, annotation_set_id)

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            submit_phase_annotation_set(
                db,
                annotation_set_id,
                SubmitResearchPhaseAnnotationSetRequest(expected_revision=999),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "message": "Phase annotation set revision conflict.",
        "current_revision": 1,
    }


@pytest.mark.parametrize("status_value", ["submitted", "reviewed", "locked"])
def test_non_draft_sets_cannot_be_submitted(phase_status_context, status_value: str) -> None:
    session_factory, seeded = phase_status_context
    annotation_set_id = create_annotation_set(
        session_factory,
        seeded,
        username=f"submit_{status_value}",
        status=status_value,
        revision=3,
    )
    seed_submittable_segments(session_factory, seeded, annotation_set_id)

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            submit_phase_annotation_set(
                db,
                annotation_set_id,
                SubmitResearchPhaseAnnotationSetRequest(expected_revision=3),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Only draft phase annotation sets can be submitted."


def test_reopen_phase_annotation_set_succeeds_and_clears_submitted_at(phase_status_context) -> None:
    session_factory, seeded = phase_status_context
    annotation_set_id = create_annotation_set(
        session_factory,
        seeded,
        username="reopen_submitted",
        status="submitted",
        revision=4,
    )
    seed_submittable_segments(session_factory, seeded, annotation_set_id)

    with session_factory() as db:
        response = reopen_phase_annotation_set(
            db,
            annotation_set_id,
            ReopenResearchPhaseAnnotationSetRequest(expected_revision=4),
        )

    assert response.action == "reopened"
    assert response.annotation_set.status == "draft"
    assert response.annotation_set.revision == 5
    assert response.annotation_set.submitted_at is None
    assert response.validation is None


@pytest.mark.parametrize(
    ("status_value", "detail"),
    [
        ("draft", "Only submitted phase annotation sets can be reopened."),
        ("reviewed", "Reviewed phase annotation sets cannot be reopened."),
        ("locked", "Locked phase annotation sets cannot be reopened."),
    ],
)
def test_non_submitted_sets_cannot_be_reopened(
    phase_status_context,
    status_value: str,
    detail: str,
) -> None:
    session_factory, seeded = phase_status_context
    annotation_set_id = create_annotation_set(
        session_factory,
        seeded,
        username=f"reopen_{status_value}",
        status=status_value,
        revision=2,
    )

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            reopen_phase_annotation_set(
                db,
                annotation_set_id,
                ReopenResearchPhaseAnnotationSetRequest(expected_revision=2),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == detail


def test_reopen_phase_annotation_set_rejects_revision_conflict(phase_status_context) -> None:
    session_factory, seeded = phase_status_context
    annotation_set_id = create_annotation_set(
        session_factory,
        seeded,
        username="reopen_conflict",
        status="submitted",
        revision=4,
    )

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            reopen_phase_annotation_set(
                db,
                annotation_set_id,
                ReopenResearchPhaseAnnotationSetRequest(expected_revision=3),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "message": "Phase annotation set revision conflict.",
        "current_revision": 4,
    }


def test_submit_and_reopen_failures_roll_back_state(phase_status_context, monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory, seeded = phase_status_context
    submit_set_id = create_annotation_set(session_factory, seeded, username="submit_rollback")
    seed_submittable_segments(session_factory, seeded, submit_set_id)
    reopen_set_id = create_annotation_set(
        session_factory,
        seeded,
        username="reopen_rollback",
        status="submitted",
        revision=4,
    )
    seed_submittable_segments(session_factory, seeded, reopen_set_id)

    with session_factory() as db:
        def fail_commit() -> None:
            raise RuntimeError("simulated commit failure")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="simulated commit failure"):
            submit_phase_annotation_set(
                db,
                submit_set_id,
                SubmitResearchPhaseAnnotationSetRequest(expected_revision=1),
            )

    with session_factory() as db:
        def fail_commit() -> None:
            raise RuntimeError("simulated commit failure")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="simulated commit failure"):
            reopen_phase_annotation_set(
                db,
                reopen_set_id,
                ReopenResearchPhaseAnnotationSetRequest(expected_revision=4),
            )

    assert get_annotation_set_snapshot(session_factory, submit_set_id)[0:3] == ("draft", 1, None)
    reopen_snapshot = get_annotation_set_snapshot(session_factory, reopen_set_id)
    assert reopen_snapshot[0] == "submitted"
    assert reopen_snapshot[1] == 4
    assert reopen_snapshot[2] is not None


def test_submit_and_reopen_do_not_modify_segments(phase_status_context) -> None:
    session_factory, seeded = phase_status_context
    submit_set_id = create_annotation_set(session_factory, seeded, username="submit_segments")
    expected_segments = seed_submittable_segments(session_factory, seeded, submit_set_id)
    reopen_set_id = create_annotation_set(
        session_factory,
        seeded,
        username="reopen_segments",
        status="submitted",
        revision=4,
    )
    seed_submittable_segments(session_factory, seeded, reopen_set_id)

    before_submit_segments = get_annotation_set_snapshot(session_factory, submit_set_id)[3]
    before_reopen_segments = get_annotation_set_snapshot(session_factory, reopen_set_id)[3]

    with session_factory() as db:
        submit_phase_annotation_set(
            db,
            submit_set_id,
            SubmitResearchPhaseAnnotationSetRequest(expected_revision=1),
        )

    with session_factory() as db:
        reopen_phase_annotation_set(
            db,
            reopen_set_id,
            ReopenResearchPhaseAnnotationSetRequest(expected_revision=4),
        )

    assert get_annotation_set_snapshot(session_factory, submit_set_id)[3] == before_submit_segments
    assert get_annotation_set_snapshot(session_factory, reopen_set_id)[3] == before_reopen_segments
    assert expected_segments


def test_submitted_sets_block_mutations_until_reopened(phase_status_context) -> None:
    session_factory, seeded = phase_status_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="submit_reopen_mutation")
    seed_submittable_segments(session_factory, seeded, annotation_set_id)

    with session_factory() as db:
        submit_response = submit_phase_annotation_set(
            db,
            annotation_set_id,
            SubmitResearchPhaseAnnotationSetRequest(expected_revision=1),
        )

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            create_phase_segment(
                db,
                annotation_set_id,
                CreateResearchPhaseSegmentRequest(
                    phase_label_id=seeded.active_default_label_ids["incision"],
                    start_frame=200,
                    end_frame_exclusive=250,
                    expected_revision=2,
                ),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Only draft phase annotation sets can be modified."

    with session_factory() as db:
        reopen_response = reopen_phase_annotation_set(
            db,
            annotation_set_id,
            ReopenResearchPhaseAnnotationSetRequest(expected_revision=2),
        )

    with session_factory() as db:
        mutation_response = update_phase_segment(
            db,
            get_segment_id_by_start(session_factory, annotation_set_id, 150),
            UpdateResearchPhaseSegmentRequest(
                notes="reopened edit",
                expected_revision=3,
            ),
        )

    assert submit_response.annotation_set.status == "submitted"
    assert reopen_response.annotation_set.status == "draft"
    assert mutation_response.action == "updated"
    assert mutation_response.annotation_set.revision == 4


def test_warning_confirmation_second_step_conflicts_after_intermediate_mutation(phase_status_context) -> None:
    session_factory, seeded = phase_status_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="warning_two_step")
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=400,
    )

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            submit_phase_annotation_set(
                db,
                annotation_set_id,
                SubmitResearchPhaseAnnotationSetRequest(expected_revision=1, confirm_warnings=False),
            )

    assert exc_info.value.status_code == 409
    assert get_annotation_set_snapshot(session_factory, annotation_set_id)[1] == 1

    with session_factory() as db:
        create_phase_segment(
            db,
            annotation_set_id,
            CreateResearchPhaseSegmentRequest(
                phase_label_id=seeded.active_default_label_ids["incision"],
                start_frame=0,
                end_frame_exclusive=5,
                expected_revision=1,
            ),
        )

    with session_factory() as db:
        with pytest.raises(HTTPException) as second_exc:
            submit_phase_annotation_set(
                db,
                annotation_set_id,
                SubmitResearchPhaseAnnotationSetRequest(expected_revision=1, confirm_warnings=True),
            )

    assert second_exc.value.status_code == 409
    assert second_exc.value.detail == {
        "message": "Phase annotation set revision conflict.",
        "current_revision": 2,
    }
