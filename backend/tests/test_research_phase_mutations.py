from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import ResearchPhaseAnnotationSet, ResearchPhaseLabel, ResearchPhaseSegment, User
from app.schemas.research_phase import (
    CloseActivePhaseSegmentRequest,
    CreateResearchPhaseSegmentRequest,
    TransitionResearchPhaseRequest,
    UpdateResearchPhaseSegmentRequest,
)
from app.services.research_phase_service import (
    close_active_phase_segment,
    create_phase_segment,
    transition_phase,
    update_phase_segment,
)
from tests._research_phase_test_utils import create_phase_session_factory, seed_phase_data


@pytest.fixture()
def phase_mutation_context(tmp_path):
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


def add_label(
    session_factory,
    *,
    protocol_id: int,
    key: str,
    name: str,
    display_order: int,
    color: str = "#111827",
    is_active: bool = True,
) -> int:
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


def add_segment(
    session_factory,
    *,
    annotation_set_id: int,
    phase_label_id: int,
    start_frame: int,
    end_frame_exclusive: int | None,
    source: str = "manual",
) -> int:
    with session_factory() as db:
        segment = ResearchPhaseSegment(
            annotation_set_id=annotation_set_id,
            phase_label_id=phase_label_id,
            start_frame=start_frame,
            end_frame_exclusive=end_frame_exclusive,
            source=source,
        )
        db.add(segment)
        db.commit()
        db.refresh(segment)
        return segment.id


def get_annotation_set_state(session_factory, annotation_set_id: int) -> tuple[int, list[tuple[int, int | None, int]]]:
    with session_factory() as db:
        annotation_set = db.scalar(
            select(ResearchPhaseAnnotationSet)
            .where(ResearchPhaseAnnotationSet.id == annotation_set_id)
            .order_by(ResearchPhaseAnnotationSet.id)
        )
        assert annotation_set is not None
        segments = db.scalars(
            select(ResearchPhaseSegment)
            .where(ResearchPhaseSegment.annotation_set_id == annotation_set_id)
            .order_by(ResearchPhaseSegment.start_frame, ResearchPhaseSegment.id)
        ).all()
        return annotation_set.revision, [
            (segment.start_frame, segment.end_frame_exclusive, segment.phase_label_id)
            for segment in segments
        ]


def get_segment_id_by_start(session_factory, annotation_set_id: int, start_frame: int) -> int:
    with session_factory() as db:
        segment = db.scalar(
            select(ResearchPhaseSegment)
            .where(
                ResearchPhaseSegment.annotation_set_id == annotation_set_id,
                ResearchPhaseSegment.start_frame == start_frame,
            )
        )
        assert segment is not None
        return segment.id


def get_alpha_v2_label_id(session_factory, seeded) -> int:
    with session_factory() as db:
        label = db.scalar(
            select(ResearchPhaseLabel).where(
                ResearchPhaseLabel.protocol_id == seeded.active_alpha_v2_protocol_id
            )
        )
        assert label is not None
        return label.id


def test_create_phase_segment_creates_closed_interval_and_increments_revision(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="creator_closed")

    with session_factory() as db:
        response = create_phase_segment(
            db,
            annotation_set_id,
            CreateResearchPhaseSegmentRequest(
                phase_label_id=seeded.active_default_label_ids["idle"],
                start_frame=20,
                end_frame_exclusive=40,
                expected_revision=1,
            ),
        )

    assert response.action == "created"
    assert response.annotation_set.revision == 2
    assert response.changed_segment_ids == response.created_segment_ids
    assert [(segment.start_frame, segment.end_frame_exclusive) for segment in response.annotation_set.segments] == [
        (20, 40)
    ]


def test_create_phase_segment_allows_open_segment(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="creator_open")

    with session_factory() as db:
        response = create_phase_segment(
            db,
            annotation_set_id,
            CreateResearchPhaseSegmentRequest(
                phase_label_id=seeded.active_default_label_ids["idle"],
                start_frame=20,
                end_frame_exclusive=None,
                expected_revision=1,
            ),
        )

    assert response.action == "created"
    assert response.annotation_set.has_open_segment is True
    assert response.annotation_set.revision == 2
    assert [(segment.start_frame, segment.end_frame_exclusive) for segment in response.annotation_set.segments] == [
        (20, None)
    ]


def test_create_phase_segment_rejects_second_open_segment(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            create_phase_segment(
                db,
                seeded.set_reader_id,
                CreateResearchPhaseSegmentRequest(
                    phase_label_id=seeded.active_default_label_ids["incision"],
                    start_frame=200,
                    end_frame_exclusive=None,
                    expected_revision=1,
                ),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Phase segment overlaps an existing segment."


def test_create_phase_segment_rejects_label_from_other_protocol(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context
    foreign_label_id = get_alpha_v2_label_id(session_factory, seeded)

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            create_phase_segment(
                db,
                seeded.set_reader_id,
                CreateResearchPhaseSegmentRequest(
                    phase_label_id=foreign_label_id,
                    start_frame=70,
                    end_frame_exclusive=90,
                    expected_revision=1,
                ),
            )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Phase label does not belong to the annotation set protocol."


def test_create_phase_segment_rejects_inactive_label(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context
    inactive_label_id = add_label(
        session_factory,
        protocol_id=seeded.active_default_protocol_id,
        key="inactive_label",
        name="Inactive Label",
        display_order=10,
        color="#6b7280",
        is_active=False,
    )

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            create_phase_segment(
                db,
                seeded.set_reader_id,
                CreateResearchPhaseSegmentRequest(
                    phase_label_id=inactive_label_id,
                    start_frame=70,
                    end_frame_exclusive=90,
                    expected_revision=1,
                ),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Inactive phase labels cannot be used."


@pytest.mark.parametrize("start_frame", [-1, 400])
def test_create_phase_segment_rejects_out_of_bounds_start(phase_mutation_context, start_frame: int) -> None:
    session_factory, seeded = phase_mutation_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            create_phase_segment(
                db,
                seeded.set_reader_id,
                CreateResearchPhaseSegmentRequest(
                    phase_label_id=seeded.active_default_label_ids["idle"],
                    start_frame=start_frame,
                    end_frame_exclusive=90,
                    expected_revision=1,
                ),
            )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Start frame is out of bounds."


def test_create_phase_segment_rejects_out_of_bounds_end(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            create_phase_segment(
                db,
                seeded.set_reader_id,
                CreateResearchPhaseSegmentRequest(
                    phase_label_id=seeded.active_default_label_ids["idle"],
                    start_frame=70,
                    end_frame_exclusive=401,
                    expected_revision=1,
                ),
            )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "End frame is out of bounds."


def test_create_phase_segment_rejects_end_not_after_start(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            create_phase_segment(
                db,
                seeded.set_reader_id,
                CreateResearchPhaseSegmentRequest(
                    phase_label_id=seeded.active_default_label_ids["idle"],
                    start_frame=70,
                    end_frame_exclusive=70,
                    expected_revision=1,
                ),
            )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "End frame must be greater than start frame."


def test_create_phase_segment_rejects_overlap_with_closed_segment(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            create_phase_segment(
                db,
                seeded.set_reader_id,
                CreateResearchPhaseSegmentRequest(
                    phase_label_id=seeded.active_default_label_ids["incision"],
                    start_frame=50,
                    end_frame_exclusive=80,
                    expected_revision=1,
                ),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Phase segment overlaps an existing segment."


def test_create_phase_segment_rejects_overlap_with_open_segment(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            create_phase_segment(
                db,
                seeded.set_reader_id,
                CreateResearchPhaseSegmentRequest(
                    phase_label_id=seeded.active_default_label_ids["incision"],
                    start_frame=200,
                    end_frame_exclusive=250,
                    expected_revision=1,
                ),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Phase segment overlaps an existing segment."


def test_create_phase_segment_allows_adjacent_interval(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context

    with session_factory() as db:
        response = create_phase_segment(
            db,
            seeded.set_reader_id,
            CreateResearchPhaseSegmentRequest(
                phase_label_id=seeded.active_default_label_ids["incision"],
                start_frame=60,
                end_frame_exclusive=80,
                expected_revision=1,
            ),
        )

    assert response.annotation_set.revision == 2
    assert (60, 80) in [(segment.start_frame, segment.end_frame_exclusive) for segment in response.annotation_set.segments]


def test_create_phase_segment_allows_gap_between_segments(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="creator_gap")

    with session_factory() as db:
        first_response = create_phase_segment(
            db,
            annotation_set_id,
            CreateResearchPhaseSegmentRequest(
                phase_label_id=seeded.active_default_label_ids["idle"],
                start_frame=10,
                end_frame_exclusive=20,
                expected_revision=1,
            ),
        )

    with session_factory() as db:
        second_response = create_phase_segment(
            db,
            annotation_set_id,
            CreateResearchPhaseSegmentRequest(
                phase_label_id=seeded.active_default_label_ids["incision"],
                start_frame=30,
                end_frame_exclusive=40,
                expected_revision=2,
            ),
        )

    assert first_response.annotation_set.revision == 2
    assert second_response.annotation_set.revision == 3
    assert [(segment.start_frame, segment.end_frame_exclusive) for segment in second_response.annotation_set.segments] == [
        (10, 20),
        (30, 40),
    ]


def test_transition_without_active_segment_creates_open_segment(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="transition_empty")

    with session_factory() as db:
        response = transition_phase(
            db,
            annotation_set_id,
            TransitionResearchPhaseRequest(
                phase_label_id=seeded.active_default_label_ids["idle"],
                current_frame=25,
                expected_revision=1,
            ),
        )

    assert response.action == "transitioned"
    assert response.annotation_set.revision == 2
    assert [(segment.start_frame, segment.end_frame_exclusive) for segment in response.annotation_set.segments] == [
        (25, None)
    ]


def test_transition_with_active_segment_closes_old_and_creates_new_segment(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context

    with session_factory() as db:
        response = transition_phase(
            db,
            seeded.set_reader_id,
            TransitionResearchPhaseRequest(
                phase_label_id=seeded.active_default_label_ids["incision"],
                current_frame=150,
                expected_revision=1,
            ),
        )

    assert response.action == "transitioned"
    assert response.annotation_set.revision == 2
    assert [(segment.start_frame, segment.end_frame_exclusive, segment.phase_label.key) for segment in response.annotation_set.segments] == [
        (10, 60, "idle"),
        (120, 150, "viscoelastic"),
        (150, None, "incision"),
    ]
    assert len(response.created_segment_ids) == 1
    assert len(response.changed_segment_ids) == 2


def test_transition_with_same_label_returns_unchanged_without_revision_increment(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context

    with session_factory() as db:
        response = transition_phase(
            db,
            seeded.set_reader_id,
            TransitionResearchPhaseRequest(
                phase_label_id=seeded.active_default_label_ids["viscoelastic"],
                current_frame=150,
                expected_revision=1,
            ),
        )

    assert response.action == "unchanged"
    assert response.annotation_set.revision == 1
    assert response.changed_segment_ids == []
    assert response.created_segment_ids == []


def test_transition_rejects_current_frame_at_active_start(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            transition_phase(
                db,
                seeded.set_reader_id,
                TransitionResearchPhaseRequest(
                    phase_label_id=seeded.active_default_label_ids["incision"],
                    current_frame=120,
                    expected_revision=1,
                ),
            )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Current frame must be after the active segment start frame."


def test_transition_rejects_video_end_frame_for_new_open_segment(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            transition_phase(
                db,
                seeded.set_reader_id,
                TransitionResearchPhaseRequest(
                    phase_label_id=seeded.active_default_label_ids["incision"],
                    current_frame=400,
                    expected_revision=1,
                ),
            )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Current frame must be before the video end frame."


def test_close_active_phase_segment_closes_open_segment(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context

    with session_factory() as db:
        response = close_active_phase_segment(
            db,
            seeded.set_reader_id,
            CloseActivePhaseSegmentRequest(
                end_frame_exclusive=180,
                expected_revision=1,
            ),
        )

    assert response.action == "closed"
    assert response.annotation_set.revision == 2
    assert response.annotation_set.has_open_segment is False
    assert [(segment.start_frame, segment.end_frame_exclusive) for segment in response.annotation_set.segments] == [
        (10, 60),
        (120, 180),
    ]


def test_close_active_phase_segment_allows_video_end_frame(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context

    with session_factory() as db:
        response = close_active_phase_segment(
            db,
            seeded.set_reader_id,
            CloseActivePhaseSegmentRequest(
                end_frame_exclusive=400,
                expected_revision=1,
            ),
        )

    assert response.annotation_set.revision == 2
    assert [(segment.start_frame, segment.end_frame_exclusive) for segment in response.annotation_set.segments] == [
        (10, 60),
        (120, 400),
    ]


def test_close_active_phase_segment_rejects_missing_active_segment(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="close_empty")

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            close_active_phase_segment(
                db,
                annotation_set_id,
                CloseActivePhaseSegmentRequest(
                    end_frame_exclusive=200,
                    expected_revision=1,
                ),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "No active phase segment exists."


def test_update_phase_segment_changes_label(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context
    segment_id = get_segment_id_by_start(session_factory, seeded.set_reader_id, 10)

    with session_factory() as db:
        response = update_phase_segment(
            db,
            segment_id,
            UpdateResearchPhaseSegmentRequest(
                phase_label_id=seeded.active_default_label_ids["incision"],
                expected_revision=1,
            ),
        )

    assert response.action == "updated"
    assert response.annotation_set.revision == 2
    assert response.annotation_set.segments[0].phase_label.key == "incision"


def test_update_phase_segment_changes_start_and_end(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context
    segment_id = get_segment_id_by_start(session_factory, seeded.set_reader_id, 10)

    with session_factory() as db:
        response = update_phase_segment(
            db,
            segment_id,
            UpdateResearchPhaseSegmentRequest(
                start_frame=15,
                end_frame_exclusive=70,
                expected_revision=1,
            ),
        )

    assert response.annotation_set.revision == 2
    assert [(segment.start_frame, segment.end_frame_exclusive) for segment in response.annotation_set.segments] == [
        (15, 70),
        (120, None),
    ]


def test_update_phase_segment_can_clear_end_frame_to_open(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="update_open")
    segment_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=20,
    )

    with session_factory() as db:
        response = update_phase_segment(
            db,
            segment_id,
            UpdateResearchPhaseSegmentRequest(
                clear_end_frame=True,
                expected_revision=1,
            ),
        )

    assert response.annotation_set.revision == 2
    assert [(segment.start_frame, segment.end_frame_exclusive) for segment in response.annotation_set.segments] == [
        (10, None)
    ]


def test_update_phase_segment_rejects_second_open_segment(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context
    segment_id = get_segment_id_by_start(session_factory, seeded.set_reader_id, 10)

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            update_phase_segment(
                db,
                segment_id,
                UpdateResearchPhaseSegmentRequest(
                    clear_end_frame=True,
                    expected_revision=1,
                ),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Phase segment overlaps an existing segment."


def test_update_phase_segment_rejects_overlap(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="update_overlap")
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=20,
    )
    second_segment_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=30,
        end_frame_exclusive=40,
    )

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            update_phase_segment(
                db,
                second_segment_id,
                UpdateResearchPhaseSegmentRequest(
                    start_frame=15,
                    end_frame_exclusive=35,
                    expected_revision=1,
                ),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Phase segment overlaps an existing segment."


def test_update_phase_segment_without_changes_returns_unchanged_without_revision_increment(
    phase_mutation_context,
) -> None:
    session_factory, seeded = phase_mutation_context
    segment_id = get_segment_id_by_start(session_factory, seeded.set_reader_id, 10)

    with session_factory() as db:
        response = update_phase_segment(
            db,
            segment_id,
            UpdateResearchPhaseSegmentRequest(expected_revision=1),
        )

    assert response.action == "unchanged"
    assert response.annotation_set.revision == 1


@pytest.mark.parametrize("operation", ["create", "transition", "close", "update"])
def test_non_draft_annotation_set_rejects_all_mutations(
    phase_mutation_context,
    operation: str,
) -> None:
    session_factory, seeded = phase_mutation_context
    reviewer_segment_id = get_segment_id_by_start(session_factory, seeded.set_reviewer_id, 200)

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            if operation == "create":
                create_phase_segment(
                    db,
                    seeded.set_reviewer_id,
                    CreateResearchPhaseSegmentRequest(
                        phase_label_id=seeded.active_default_label_ids["idle"],
                        start_frame=10,
                        end_frame_exclusive=20,
                        expected_revision=2,
                    ),
                )
            elif operation == "transition":
                transition_phase(
                    db,
                    seeded.set_reviewer_id,
                    TransitionResearchPhaseRequest(
                        phase_label_id=seeded.active_default_label_ids["idle"],
                        current_frame=260,
                        expected_revision=2,
                    ),
                )
            elif operation == "close":
                close_active_phase_segment(
                    db,
                    seeded.set_reviewer_id,
                    CloseActivePhaseSegmentRequest(
                        end_frame_exclusive=300,
                        expected_revision=2,
                    ),
                )
            else:
                update_phase_segment(
                    db,
                    reviewer_segment_id,
                    UpdateResearchPhaseSegmentRequest(
                        end_frame_exclusive=270,
                        expected_revision=2,
                    ),
                )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Only draft phase annotation sets can be modified."


def test_mutation_rejects_revision_conflict(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="revision_conflict")

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            create_phase_segment(
                db,
                annotation_set_id,
                CreateResearchPhaseSegmentRequest(
                    phase_label_id=seeded.active_default_label_ids["idle"],
                    start_frame=20,
                    end_frame_exclusive=40,
                    expected_revision=999,
                ),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "message": "Phase annotation set revision conflict.",
        "current_revision": 1,
    }


def test_successful_mutation_increments_revision_once(phase_mutation_context) -> None:
    session_factory, seeded = phase_mutation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="revision_once")

    with session_factory() as db:
        response = create_phase_segment(
            db,
            annotation_set_id,
            CreateResearchPhaseSegmentRequest(
                phase_label_id=seeded.active_default_label_ids["idle"],
                start_frame=20,
                end_frame_exclusive=40,
                expected_revision=1,
            ),
        )

    revision, segments = get_annotation_set_state(session_factory, annotation_set_id)
    assert response.annotation_set.revision == 2
    assert revision == 2
    assert segments == [(20, 40, seeded.active_default_label_ids["idle"])]


def test_transition_rolls_back_on_failure_without_changing_revision_or_segments(
    phase_mutation_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, seeded = phase_mutation_context

    with session_factory() as db:
        def fail_flush() -> None:
            raise RuntimeError("simulated flush failure")

        monkeypatch.setattr(db, "flush", fail_flush)
        with pytest.raises(RuntimeError, match="simulated flush failure"):
            transition_phase(
                db,
                seeded.set_reader_id,
                TransitionResearchPhaseRequest(
                    phase_label_id=seeded.active_default_label_ids["incision"],
                    current_frame=150,
                    expected_revision=1,
                ),
            )

    revision, segments = get_annotation_set_state(session_factory, seeded.set_reader_id)
    assert revision == 1
    assert segments == [
        (10, 60, seeded.active_default_label_ids["idle"]),
        (120, None, seeded.active_default_label_ids["viscoelastic"]),
    ]


def test_update_phase_segment_returns_404_for_missing_segment(phase_mutation_context) -> None:
    session_factory, _seeded = phase_mutation_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            update_phase_segment(
                db,
                999999,
                UpdateResearchPhaseSegmentRequest(expected_revision=1),
            )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Phase segment not found."
