from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import ResearchPhaseAnnotationSet, ResearchPhaseLabel, ResearchPhaseSegment, User
from app.schemas.research_phase import (
    MergeResearchPhaseSegmentsRequest,
    SplitResearchPhaseSegmentRequest,
)
from app.services.research_phase_service import (
    _merge_segment_notes,
    delete_phase_segment,
    merge_phase_segments,
    split_phase_segment,
)
from tests._research_phase_test_utils import create_phase_session_factory, seed_phase_data


@pytest.fixture()
def phase_segment_ops_context(tmp_path):
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
    protocol_id: int | None = None,
    status: str = "draft",
    revision: int = 1,
) -> int:
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


def get_segment_state(session_factory, annotation_set_id: int) -> tuple[int, list[tuple[int, int | None, int, str | None, float | None, str | None]]]:
    with session_factory() as db:
        annotation_set = db.get(ResearchPhaseAnnotationSet, annotation_set_id)
        assert annotation_set is not None
        segments = db.scalars(
            select(ResearchPhaseSegment)
            .where(ResearchPhaseSegment.annotation_set_id == annotation_set_id)
            .order_by(ResearchPhaseSegment.start_frame, ResearchPhaseSegment.id)
        ).all()
        return annotation_set.revision, [
            (
                segment.id,
                segment.start_frame,
                segment.end_frame_exclusive,
                segment.source,
                segment.confidence,
                segment.notes,
            )
            for segment in segments
        ]


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


def segment_exists(session_factory, segment_id: int) -> bool:
    with session_factory() as db:
        return db.get(ResearchPhaseSegment, segment_id) is not None


def test_delete_closed_segment_removes_only_target_and_increments_revision(phase_segment_ops_context) -> None:
    session_factory, seeded = phase_segment_ops_context
    deleted_segment_id = get_segment_id_by_start(session_factory, seeded.set_reader_id, 10)

    with session_factory() as db:
        response = delete_phase_segment(db, deleted_segment_id, 1)

    assert response.action == "deleted"
    assert response.annotation_set.revision == 2
    assert response.deleted_segment_ids == [deleted_segment_id]
    assert response.changed_segment_ids == []
    assert response.created_segment_ids == []
    assert [(segment.start_frame, segment.end_frame_exclusive) for segment in response.annotation_set.segments] == [
        (120, None)
    ]
    assert not segment_exists(session_factory, deleted_segment_id)


def test_delete_open_segment_allows_gap(phase_segment_ops_context) -> None:
    session_factory, seeded = phase_segment_ops_context
    deleted_segment_id = get_segment_id_by_start(session_factory, seeded.set_reader_id, 120)

    with session_factory() as db:
        response = delete_phase_segment(db, deleted_segment_id, 1)

    assert response.annotation_set.revision == 2
    assert response.annotation_set.has_open_segment is False
    assert [(segment.start_frame, segment.end_frame_exclusive) for segment in response.annotation_set.segments] == [
        (10, 60)
    ]
    assert not segment_exists(session_factory, deleted_segment_id)


def test_delete_segment_returns_404_for_missing_segment(phase_segment_ops_context) -> None:
    session_factory, _seeded = phase_segment_ops_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            delete_phase_segment(db, 999999, 1)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Phase segment not found."


def test_delete_segment_rejects_non_draft_annotation_set(phase_segment_ops_context) -> None:
    session_factory, seeded = phase_segment_ops_context
    segment_id = get_segment_id_by_start(session_factory, seeded.set_reviewer_id, 200)

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            delete_phase_segment(db, segment_id, 2)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Only draft phase annotation sets can be modified."


def test_delete_segment_rejects_revision_conflict(phase_segment_ops_context) -> None:
    session_factory, seeded = phase_segment_ops_context
    segment_id = get_segment_id_by_start(session_factory, seeded.set_reader_id, 10)

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            delete_phase_segment(db, segment_id, 999)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "message": "Phase annotation set revision conflict.",
        "current_revision": 1,
    }


def test_delete_segment_rolls_back_when_flush_fails(phase_segment_ops_context, monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory, seeded = phase_segment_ops_context
    segment_id = get_segment_id_by_start(session_factory, seeded.set_reader_id, 10)

    with session_factory() as db:
        def fail_flush() -> None:
            raise RuntimeError("simulated delete flush failure")

        monkeypatch.setattr(db, "flush", fail_flush)
        with pytest.raises(RuntimeError, match="simulated delete flush failure"):
            delete_phase_segment(db, segment_id, 1)

    revision, segments = get_segment_state(session_factory, seeded.set_reader_id)
    assert revision == 1
    assert [segment[1:3] for segment in segments] == [(10, 60), (120, None)]


def test_split_closed_segment_preserves_original_id_and_creates_new_segment(phase_segment_ops_context) -> None:
    session_factory, seeded = phase_segment_ops_context
    original_segment_id = get_segment_id_by_start(session_factory, seeded.set_reader_id, 10)

    with session_factory() as db:
        response = split_phase_segment(
            db,
            original_segment_id,
            SplitResearchPhaseSegmentRequest(split_frame=30, expected_revision=1),
        )

    assert response.action == "split"
    assert response.annotation_set.revision == 2
    assert response.changed_segment_ids == [original_segment_id]
    assert len(response.created_segment_ids) == 1
    created_segment_id = response.created_segment_ids[0]
    assert created_segment_id != original_segment_id
    assert [
        (segment.id, segment.start_frame, segment.end_frame_exclusive, segment.phase_label.key)
        for segment in response.annotation_set.segments
    ] == [
        (original_segment_id, 10, 30, "idle"),
        (created_segment_id, 30, 60, "idle"),
        (get_segment_id_by_start(session_factory, seeded.set_reader_id, 120), 120, None, "viscoelastic"),
    ]


def test_split_open_segment_copies_metadata_and_keeps_new_segment_open(phase_segment_ops_context) -> None:
    session_factory, seeded = phase_segment_ops_context
    open_segment_id = get_segment_id_by_start(session_factory, seeded.set_reader_id, 120)

    with session_factory() as db:
        response = split_phase_segment(
            db,
            open_segment_id,
            SplitResearchPhaseSegmentRequest(split_frame=150, expected_revision=1),
        )

    created_segment_id = response.created_segment_ids[0]
    assert response.annotation_set.revision == 2
    assert [
        (segment.id, segment.start_frame, segment.end_frame_exclusive, segment.source, segment.confidence, segment.notes)
        for segment in response.annotation_set.segments
    ] == [
        (get_segment_id_by_start(session_factory, seeded.set_reader_id, 10), 10, 60, "manual", 0.95, None),
        (open_segment_id, 120, 150, "manual", 0.9, None),
        (created_segment_id, 150, None, "manual", 0.9, None),
    ]


@pytest.mark.parametrize(
    ("segment_start", "split_frame", "detail"),
    [
        (10, 10, "Split frame must be after the segment start frame."),
        (10, 60, "Split frame must be before the segment end frame."),
    ],
)
def test_split_closed_segment_rejects_invalid_boundaries(
    phase_segment_ops_context,
    segment_start: int,
    split_frame: int,
    detail: str,
) -> None:
    session_factory, seeded = phase_segment_ops_context
    segment_id = get_segment_id_by_start(session_factory, seeded.set_reader_id, segment_start)

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            split_phase_segment(
                db,
                segment_id,
                SplitResearchPhaseSegmentRequest(split_frame=split_frame, expected_revision=1),
            )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == detail


def test_split_open_segment_rejects_video_end_frame(phase_segment_ops_context) -> None:
    session_factory, seeded = phase_segment_ops_context
    segment_id = get_segment_id_by_start(session_factory, seeded.set_reader_id, 120)

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            split_phase_segment(
                db,
                segment_id,
                SplitResearchPhaseSegmentRequest(split_frame=400, expected_revision=1),
            )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Split frame must be before the video end frame."


def test_split_segment_rejects_out_of_range_frame(phase_segment_ops_context) -> None:
    session_factory, seeded = phase_segment_ops_context
    segment_id = get_segment_id_by_start(session_factory, seeded.set_reader_id, 120)

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            split_phase_segment(
                db,
                segment_id,
                SplitResearchPhaseSegmentRequest(split_frame=401, expected_revision=1),
            )

    assert exc_info.value.status_code == 422


def test_split_segment_rejects_non_draft_annotation_set(phase_segment_ops_context) -> None:
    session_factory, seeded = phase_segment_ops_context
    segment_id = get_segment_id_by_start(session_factory, seeded.set_reviewer_id, 200)

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            split_phase_segment(
                db,
                segment_id,
                SplitResearchPhaseSegmentRequest(split_frame=220, expected_revision=2),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Only draft phase annotation sets can be modified."


def test_split_segment_rejects_revision_conflict(phase_segment_ops_context) -> None:
    session_factory, seeded = phase_segment_ops_context
    segment_id = get_segment_id_by_start(session_factory, seeded.set_reader_id, 10)

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            split_phase_segment(
                db,
                segment_id,
                SplitResearchPhaseSegmentRequest(split_frame=30, expected_revision=999),
            )

    assert exc_info.value.status_code == 409


def test_split_segment_rolls_back_when_flush_fails(phase_segment_ops_context, monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory, seeded = phase_segment_ops_context
    segment_id = get_segment_id_by_start(session_factory, seeded.set_reader_id, 10)

    with session_factory() as db:
        def fail_flush() -> None:
            raise RuntimeError("simulated split flush failure")

        monkeypatch.setattr(db, "flush", fail_flush)
        with pytest.raises(RuntimeError, match="simulated split flush failure"):
            split_phase_segment(
                db,
                segment_id,
                SplitResearchPhaseSegmentRequest(split_frame=30, expected_revision=1),
            )

    revision, segments = get_segment_state(session_factory, seeded.set_reader_id)
    assert revision == 1
    assert [segment[1:3] for segment in segments] == [(10, 60), (120, None)]


def test_merge_adjacent_closed_segments_keeps_left_id_and_deletes_right(phase_segment_ops_context) -> None:
    session_factory, seeded = phase_segment_ops_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="merge_closed")
    left_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=20,
        notes="left",
    )
    right_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=20,
        end_frame_exclusive=40,
        notes="right",
    )

    with session_factory() as db:
        response = merge_phase_segments(
            db,
            annotation_set_id,
            MergeResearchPhaseSegmentsRequest(
                left_segment_id=left_id,
                right_segment_id=right_id,
                expected_revision=1,
            ),
        )

    assert response.action == "merged"
    assert response.annotation_set.revision == 2
    assert response.changed_segment_ids == [left_id]
    assert response.deleted_segment_ids == [right_id]
    assert [(segment.id, segment.start_frame, segment.end_frame_exclusive, segment.notes) for segment in response.annotation_set.segments] == [
        (left_id, 10, 40, "left\nright")
    ]
    assert not segment_exists(session_factory, right_id)


def test_merge_closed_and_open_segment_produces_open_segment(phase_segment_ops_context) -> None:
    session_factory, seeded = phase_segment_ops_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="merge_open")
    left_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=20,
        source="manual",
        confidence=0.8,
        notes="keep left",
    )
    right_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=20,
        end_frame_exclusive=None,
        source="imported",
        confidence=0.3,
        notes=None,
    )

    with session_factory() as db:
        response = merge_phase_segments(
            db,
            annotation_set_id,
            MergeResearchPhaseSegmentsRequest(
                left_segment_id=left_id,
                right_segment_id=right_id,
                expected_revision=1,
            ),
        )

    assert [(segment.id, segment.start_frame, segment.end_frame_exclusive, segment.source, segment.confidence, segment.notes) for segment in response.annotation_set.segments] == [
        (left_id, 10, None, "manual", 0.8, "keep left")
    ]


def test_merge_rejects_non_adjacent_segments(phase_segment_ops_context) -> None:
    session_factory, seeded = phase_segment_ops_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="merge_gap")
    left_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=20,
    )
    right_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=30,
        end_frame_exclusive=40,
    )

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            merge_phase_segments(
                db,
                annotation_set_id,
                MergeResearchPhaseSegmentsRequest(
                    left_segment_id=left_id,
                    right_segment_id=right_id,
                    expected_revision=1,
                ),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Phase segments must be strictly adjacent to merge."


def test_merge_rejects_segments_with_different_labels(phase_segment_ops_context) -> None:
    session_factory, seeded = phase_segment_ops_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="merge_label")
    left_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=20,
    )
    right_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=20,
        end_frame_exclusive=40,
    )

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            merge_phase_segments(
                db,
                annotation_set_id,
                MergeResearchPhaseSegmentsRequest(
                    left_segment_id=left_id,
                    right_segment_id=right_id,
                    expected_revision=1,
                ),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Only adjacent segments with the same phase label can be merged."


def test_merge_rejects_segments_from_different_annotation_sets(phase_segment_ops_context) -> None:
    session_factory, seeded = phase_segment_ops_context
    left_set_id = create_annotation_set(session_factory, seeded, username="merge_set_left")
    right_set_id = create_annotation_set(session_factory, seeded, username="merge_set_right")
    left_id = add_segment(
        session_factory,
        annotation_set_id=left_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=20,
    )
    right_id = add_segment(
        session_factory,
        annotation_set_id=right_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=20,
        end_frame_exclusive=40,
    )

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            merge_phase_segments(
                db,
                left_set_id,
                MergeResearchPhaseSegmentsRequest(
                    left_segment_id=left_id,
                    right_segment_id=right_id,
                    expected_revision=1,
                ),
            )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Both segments must belong to the requested annotation set."


def test_merge_rejects_open_left_segment(phase_segment_ops_context) -> None:
    session_factory, seeded = phase_segment_ops_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="merge_open_left")
    left_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=None,
    )
    right_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=20,
        end_frame_exclusive=40,
    )

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            merge_phase_segments(
                db,
                annotation_set_id,
                MergeResearchPhaseSegmentsRequest(
                    left_segment_id=left_id,
                    right_segment_id=right_id,
                    expected_revision=1,
                ),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Left segment must be closed before merging."


def test_merge_rejects_same_segment_ids(phase_segment_ops_context) -> None:
    session_factory, seeded = phase_segment_ops_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="merge_same")
    left_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=20,
    )

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            merge_phase_segments(
                db,
                annotation_set_id,
                MergeResearchPhaseSegmentsRequest(
                    left_segment_id=left_id,
                    right_segment_id=left_id,
                    expected_revision=1,
                ),
            )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Left and right segments must be different."


@pytest.mark.parametrize(
    ("left_notes", "right_notes", "expected_notes"),
    [
        (None, "right only", "right only"),
        ("same", "same", "same"),
        ("left", "right", "left\nright"),
    ],
)
def test_merge_segment_notes_pure_function(
    left_notes: str | None,
    right_notes: str | None,
    expected_notes: str | None,
) -> None:
    assert _merge_segment_notes(left_notes, right_notes) == expected_notes


def test_merge_segment_rejects_non_draft_annotation_set(phase_segment_ops_context) -> None:
    session_factory, seeded = phase_segment_ops_context
    left_id = add_segment(
        session_factory,
        annotation_set_id=seeded.set_reviewer_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=260,
        end_frame_exclusive=300,
    )

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            merge_phase_segments(
                db,
                seeded.set_reviewer_id,
                MergeResearchPhaseSegmentsRequest(
                    left_segment_id=get_segment_id_by_start(session_factory, seeded.set_reviewer_id, 200),
                    right_segment_id=left_id,
                    expected_revision=2,
                ),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Only draft phase annotation sets can be modified."


def test_merge_segment_rejects_revision_conflict(phase_segment_ops_context) -> None:
    session_factory, seeded = phase_segment_ops_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="merge_conflict")
    left_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=20,
    )
    right_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=20,
        end_frame_exclusive=40,
    )

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            merge_phase_segments(
                db,
                annotation_set_id,
                MergeResearchPhaseSegmentsRequest(
                    left_segment_id=left_id,
                    right_segment_id=right_id,
                    expected_revision=999,
                ),
            )

    assert exc_info.value.status_code == 409


def test_merge_segment_rolls_back_when_flush_fails(phase_segment_ops_context, monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory, seeded = phase_segment_ops_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="merge_rollback")
    left_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=20,
        notes="left",
    )
    right_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=20,
        end_frame_exclusive=40,
        notes="right",
    )

    with session_factory() as db:
        def fail_flush() -> None:
            raise RuntimeError("simulated merge flush failure")

        monkeypatch.setattr(db, "flush", fail_flush)
        with pytest.raises(RuntimeError, match="simulated merge flush failure"):
            merge_phase_segments(
                db,
                annotation_set_id,
                MergeResearchPhaseSegmentsRequest(
                    left_segment_id=left_id,
                    right_segment_id=right_id,
                    expected_revision=1,
                ),
            )

    revision, segments = get_segment_state(session_factory, annotation_set_id)
    assert revision == 1
    assert [(segment[1], segment[2], segment[5]) for segment in segments] == [
        (10, 20, "left"),
        (20, 40, "right"),
    ]
