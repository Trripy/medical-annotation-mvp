from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import ResearchPhaseAnnotationSet, ResearchPhaseSegment, User
from app.schemas.research_phase import FillResearchPhaseGapsRequest
from app.services.research_phase_service import (
    calculate_phase_annotation_gaps,
    fill_phase_gaps,
    preview_phase_gap_fill,
)
from tests._research_phase_test_utils import create_phase_session_factory, seed_phase_data


@pytest.fixture()
def phase_gap_fill_context(tmp_path):
    engine, session_factory = create_phase_session_factory(tmp_path)
    seeded = seed_phase_data(session_factory)
    try:
        yield session_factory, seeded
    finally:
        engine.dispose()


def create_annotation_set(session_factory, seeded, *, username: str, status: str = "draft", revision: int = 1) -> int:
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
) -> int:
    with session_factory() as db:
        segment = ResearchPhaseSegment(
            annotation_set_id=annotation_set_id,
            phase_label_id=phase_label_id,
            start_frame=start_frame,
            end_frame_exclusive=end_frame_exclusive,
            source="manual",
        )
        db.add(segment)
        db.commit()
        db.refresh(segment)
        return segment.id


def read_state(session_factory, annotation_set_id: int) -> tuple[int, list[tuple[int, int | None, int, str, str | None]]]:
    with session_factory() as db:
        annotation_set = db.get(ResearchPhaseAnnotationSet, annotation_set_id)
        assert annotation_set is not None
        segments = db.scalars(
            select(ResearchPhaseSegment)
            .where(ResearchPhaseSegment.annotation_set_id == annotation_set_id)
            .order_by(ResearchPhaseSegment.start_frame, ResearchPhaseSegment.id)
        ).all()
        return annotation_set.revision, [
            (segment.start_frame, segment.end_frame_exclusive, segment.phase_label_id, segment.source, segment.notes)
            for segment in segments
        ]


def test_calculate_phase_annotation_gaps_includes_leading_internal_trailing_and_one_frame(phase_gap_fill_context) -> None:
    session_factory, seeded = phase_gap_fill_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="gap_calc")
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=100,
        end_frame_exclusive=200,
    )
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["viscoelastic"],
        start_frame=201,
        end_frame_exclusive=300,
    )
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=350,
        end_frame_exclusive=400,
    )

    with session_factory() as db:
        annotation_set = db.get(ResearchPhaseAnnotationSet, annotation_set_id)
        assert annotation_set is not None
        gaps = calculate_phase_annotation_gaps(400, annotation_set.segments)

    assert [(gap.start_frame, gap.end_frame_exclusive, gap.frame_count, gap.gap_type) for gap in gaps] == [
        (0, 100, 100, "leading"),
        (200, 201, 1, "internal"),
        (300, 350, 50, "internal"),
    ]


def test_preview_is_read_only_and_fill_creates_idle_segments_once(phase_gap_fill_context) -> None:
    session_factory, seeded = phase_gap_fill_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="gap_fill")
    incision_id = seeded.active_default_label_ids["incision"]
    idle_id = seeded.active_default_label_ids["idle"]
    add_segment(session_factory, annotation_set_id=annotation_set_id, phase_label_id=incision_id, start_frame=100, end_frame_exclusive=200)
    add_segment(session_factory, annotation_set_id=annotation_set_id, phase_label_id=incision_id, start_frame=300, end_frame_exclusive=350)

    with session_factory() as db:
        preview = preview_phase_gap_fill(db, annotation_set_id, FillResearchPhaseGapsRequest(phase_label_id=idle_id, expected_revision=1))

    assert preview.current_revision == 1
    assert preview.gap_count == 3
    assert preview.total_gap_frames == 250
    assert preview.leading_gap_count == 1
    assert preview.internal_gap_count == 1
    assert preview.trailing_gap_count == 1
    assert read_state(session_factory, annotation_set_id)[0] == 1

    with session_factory() as db:
        response = fill_phase_gaps(db, annotation_set_id, FillResearchPhaseGapsRequest(phase_label_id=idle_id, expected_revision=1))

    revision, segments = read_state(session_factory, annotation_set_id)
    assert response.action == "filled_gaps"
    assert response.annotation_set.revision == 2
    assert revision == 2
    assert response.created_segment_ids
    assert [(start, end, label_id) for start, end, label_id, _source, _notes in segments] == [
        (0, 100, idle_id),
        (100, 200, incision_id),
        (200, 300, idle_id),
        (300, 350, incision_id),
        (350, 400, idle_id),
    ]
    assert all(source == "manual" for _start, _end, label_id, source, _notes in segments if label_id == idle_id)
    assert all(notes is None for _start, _end, label_id, _source, notes in segments if label_id == idle_id)


def test_gap_fill_rejects_open_overlap_wrong_label_submitted_and_revision_conflict(phase_gap_fill_context) -> None:
    session_factory, seeded = phase_gap_fill_context
    idle_id = seeded.active_default_label_ids["idle"]
    incision_id = seeded.active_default_label_ids["incision"]

    open_set_id = create_annotation_set(session_factory, seeded, username="gap_open")
    add_segment(session_factory, annotation_set_id=open_set_id, phase_label_id=incision_id, start_frame=20, end_frame_exclusive=None)
    with session_factory() as db, pytest.raises(HTTPException) as open_error:
        preview_phase_gap_fill(db, open_set_id, FillResearchPhaseGapsRequest(phase_label_id=idle_id, expected_revision=1))
    assert open_error.value.status_code == 409
    assert open_error.value.detail["error_code"] == "open_phase_segment_exists"

    overlap_set_id = create_annotation_set(session_factory, seeded, username="gap_overlap")
    add_segment(session_factory, annotation_set_id=overlap_set_id, phase_label_id=incision_id, start_frame=20, end_frame_exclusive=80)
    add_segment(session_factory, annotation_set_id=overlap_set_id, phase_label_id=incision_id, start_frame=70, end_frame_exclusive=100)
    with session_factory() as db, pytest.raises(HTTPException) as overlap_error:
        preview_phase_gap_fill(db, overlap_set_id, FillResearchPhaseGapsRequest(phase_label_id=idle_id, expected_revision=1))
    assert overlap_error.value.status_code == 409
    assert overlap_error.value.detail["error_code"] == "phase_segment_overlap"

    with session_factory() as db, pytest.raises(HTTPException) as label_error:
        fill_phase_gaps(db, overlap_set_id, FillResearchPhaseGapsRequest(phase_label_id=999999, expected_revision=1))
    assert label_error.value.status_code == 404

    submitted_set_id = create_annotation_set(session_factory, seeded, username="gap_submitted", status="submitted")
    with session_factory() as db, pytest.raises(HTTPException) as submitted_error:
        fill_phase_gaps(db, submitted_set_id, FillResearchPhaseGapsRequest(phase_label_id=idle_id, expected_revision=1))
    assert submitted_error.value.status_code == 409

    conflict_set_id = create_annotation_set(session_factory, seeded, username="gap_conflict")
    with session_factory() as db, pytest.raises(HTTPException) as conflict_error:
        fill_phase_gaps(db, conflict_set_id, FillResearchPhaseGapsRequest(phase_label_id=idle_id, expected_revision=99))
    assert conflict_error.value.status_code == 409
    assert conflict_error.value.detail["message"] == "Phase annotation set revision conflict."


def test_gap_fill_noop_when_fully_covered_without_revision_increment(phase_gap_fill_context) -> None:
    session_factory, seeded = phase_gap_fill_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="gap_full")
    idle_id = seeded.active_default_label_ids["idle"]
    incision_id = seeded.active_default_label_ids["incision"]
    add_segment(session_factory, annotation_set_id=annotation_set_id, phase_label_id=incision_id, start_frame=0, end_frame_exclusive=200)
    add_segment(session_factory, annotation_set_id=annotation_set_id, phase_label_id=incision_id, start_frame=200, end_frame_exclusive=400)

    with session_factory() as db:
        preview = preview_phase_gap_fill(db, annotation_set_id, FillResearchPhaseGapsRequest(phase_label_id=idle_id, expected_revision=1))
        response = fill_phase_gaps(db, annotation_set_id, FillResearchPhaseGapsRequest(phase_label_id=idle_id, expected_revision=1))

    assert preview.gap_count == 0
    assert response.action == "unchanged"
    assert response.annotation_set.revision == 1
    assert read_state(session_factory, annotation_set_id)[0] == 1
