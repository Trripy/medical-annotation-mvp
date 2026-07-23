from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import ResearchPhaseAnnotationSet, ResearchPhaseLabel, ResearchPhaseSegment, ResearchVideo, User
from app.services.research_phase_service import (
    _calculate_closed_coverage,
    _sort_validation_issues,
    _validate_segment_bounds,
    validate_phase_annotation_set,
)
from tests._research_phase_test_utils import create_phase_session_factory, seed_phase_data


@pytest.fixture()
def phase_validation_context(tmp_path):
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


def update_video(
    session_factory,
    video_id: int,
    *,
    frame_count: int | None = None,
    fps: float | None = None,
) -> None:
    with session_factory() as db:
        video = db.get(ResearchVideo, video_id)
        assert video is not None
        if frame_count is not None:
            video.frame_count = frame_count
        if fps is not None:
            video.fps = fps
        db.commit()


def get_annotation_set_snapshot(session_factory, annotation_set_id: int) -> tuple[int, str, list[tuple[int, int | None, int]]]:
    with session_factory() as db:
        annotation_set = db.scalar(
            select(ResearchPhaseAnnotationSet).where(ResearchPhaseAnnotationSet.id == annotation_set_id)
        )
        assert annotation_set is not None
        segments = db.scalars(
            select(ResearchPhaseSegment)
            .where(ResearchPhaseSegment.annotation_set_id == annotation_set_id)
            .order_by(ResearchPhaseSegment.start_frame, ResearchPhaseSegment.id)
        ).all()
        return annotation_set.revision, annotation_set.status, [
            (segment.start_frame, segment.end_frame_exclusive, segment.phase_label_id)
            for segment in segments
        ]


def build_segment(
    *,
    segment_id: int,
    start_frame: int,
    end_frame_exclusive: int | None,
    label_key: str = "incision",
    display_order: int = 1,
    is_active: bool = True,
) -> ResearchPhaseSegment:
    label = ResearchPhaseLabel(
        id=1000 + segment_id,
        protocol_id=1,
        key=label_key,
        name=label_key.replace("_", " ").title(),
        color="#111827",
        display_order=display_order,
        is_active=is_active,
    )
    segment = ResearchPhaseSegment(
        id=segment_id,
        annotation_set_id=1,
        phase_label_id=label.id,
        start_frame=start_frame,
        end_frame_exclusive=end_frame_exclusive,
        source="manual",
    )
    segment.phase_label = label
    return segment


def issue_types(response) -> list[str]:
    return [issue.issue_type for issue in response.issues]


def test_validate_returns_404_for_missing_annotation_set(phase_validation_context) -> None:
    session_factory, _seeded = phase_validation_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            validate_phase_annotation_set(db, 999999)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Phase annotation set not found."


def test_validate_empty_set_returns_no_segments_without_video_end_issue(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="empty_validate")

    with session_factory() as db:
        response = validate_phase_annotation_set(db, annotation_set_id)

    assert response.segment_count == 0
    assert response.closed_covered_frame_count == 0
    assert response.closed_coverage_percent == 0.0
    assert response.issue_counts.error == 1
    assert issue_types(response) == ["no_segments"]
    assert response.is_valid is False
    assert response.can_submit is False
    assert response.requires_warning_confirmation is False


def test_validate_complete_sequence_has_no_errors_and_full_coverage(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="validate_complete")
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=0,
        end_frame_exclusive=150,
    )
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["viscoelastic"],
        start_frame=150,
        end_frame_exclusive=300,
    )
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=300,
        end_frame_exclusive=400,
    )

    with session_factory() as db:
        response = validate_phase_annotation_set(db, annotation_set_id)

    assert response.issue_counts.error == 0
    assert response.issue_counts.warning == 0
    assert response.closed_covered_frame_count == 400
    assert response.closed_coverage_percent == 100.0
    assert response.is_valid is True
    assert response.can_submit is True
    assert response.requires_warning_confirmation is False


def test_validate_open_segment_reports_error_without_trailing_video_end_issue(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context

    with session_factory() as db:
        response = validate_phase_annotation_set(db, seeded.set_reader_id)

    types = issue_types(response)
    assert "open_segment" in types
    assert "video_end_not_covered" not in types
    assert response.open_segment_count == 1
    assert response.closed_segment_count == 1
    assert response.closed_covered_frame_count == 50
    assert response.closed_coverage_percent == 12.5


def test_validate_segment_bounds_detects_zero_length_pure_function() -> None:
    issues = _validate_segment_bounds(
        [build_segment(segment_id=1, start_frame=10, end_frame_exclusive=10)],
        400,
    )

    assert [issue.issue_type for issue in issues] == ["zero_length"]
    assert issues[0].message == "Phase segment must have a positive duration."


def test_validate_segment_bounds_detects_out_of_bounds_start_and_end_pure_function() -> None:
    issues = _validate_segment_bounds(
        [
            build_segment(segment_id=1, start_frame=-1, end_frame_exclusive=10),
            build_segment(segment_id=2, start_frame=10, end_frame_exclusive=401),
        ],
        400,
    )

    assert [(issue.segment_id, issue.message) for issue in issues] == [
        (1, "Phase segment starts outside the video frame range."),
        (2, "Phase segment ends outside the video frame range."),
    ]


def test_validate_invalid_video_frame_count_returns_error_and_zero_coverage(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="validate_bad_video")
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=0,
        end_frame_exclusive=10,
    )
    update_video(session_factory, seeded.video_id, frame_count=0)

    with session_factory() as db:
        response = validate_phase_annotation_set(db, annotation_set_id)

    assert response.closed_covered_frame_count == 0
    assert response.closed_coverage_percent == 0.0
    assert any(
        issue.issue_type == "out_of_bounds" and issue.message == "The research video has an invalid frame count."
        for issue in response.issues
    )


def test_validate_duplicate_start_groups_segments_stably(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="validate_duplicate_start")
    first_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=20,
    )
    second_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["viscoelastic"],
        start_frame=10,
        end_frame_exclusive=30,
    )
    third_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=10,
        end_frame_exclusive=40,
    )

    with session_factory() as db:
        response = validate_phase_annotation_set(db, annotation_set_id)

    duplicate_issues = [issue for issue in response.issues if issue.issue_type == "duplicate_start"]
    assert len(duplicate_issues) == 1
    assert duplicate_issues[0].details["segment_ids"] == [first_id, second_id, third_id]


def test_validate_reports_closed_segment_overlap(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="validate_overlap_closed")
    left_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=60,
    )
    right_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=50,
        end_frame_exclusive=90,
    )

    with session_factory() as db:
        response = validate_phase_annotation_set(db, annotation_set_id)

    overlap_issues = [issue for issue in response.issues if issue.issue_type == "overlap"]
    assert len(overlap_issues) == 1
    assert overlap_issues[0].segment_id == left_id
    assert overlap_issues[0].related_segment_id == right_id
    assert overlap_issues[0].frame_start == 50
    assert overlap_issues[0].frame_end_exclusive == 60


def test_validate_reports_open_segment_overlap(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="validate_overlap_open")
    open_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=50,
        end_frame_exclusive=None,
    )
    closed_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=60,
        end_frame_exclusive=90,
    )

    with session_factory() as db:
        response = validate_phase_annotation_set(db, annotation_set_id)

    overlap_issues = [issue for issue in response.issues if issue.issue_type == "overlap"]
    assert len(overlap_issues) == 1
    assert overlap_issues[0].segment_id == open_id
    assert overlap_issues[0].related_segment_id == closed_id
    assert overlap_issues[0].frame_start == 60
    assert overlap_issues[0].frame_end_exclusive == 90


def test_validate_strictly_adjacent_segments_do_not_report_overlap(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="validate_adjacent_no_overlap")
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=20,
    )
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=20,
        end_frame_exclusive=40,
    )

    with session_factory() as db:
        response = validate_phase_annotation_set(db, annotation_set_id)

    assert "overlap" not in issue_types(response)


def test_validate_reports_gap_at_video_start(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="validate_gap_start")
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=400,
    )

    with session_factory() as db:
        response = validate_phase_annotation_set(db, annotation_set_id)

    gap_issues = [issue for issue in response.issues if issue.issue_type == "gap"]
    assert len(gap_issues) == 1
    assert gap_issues[0].message == "There is an unlabeled gap at the beginning of the video."
    assert gap_issues[0].frame_start == 0
    assert gap_issues[0].frame_end_exclusive == 10


def test_validate_reports_gap_between_segments(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="validate_gap_middle")
    first_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=0,
        end_frame_exclusive=50,
    )
    second_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=100,
        end_frame_exclusive=400,
    )

    with session_factory() as db:
        response = validate_phase_annotation_set(db, annotation_set_id)

    gap_issues = [issue for issue in response.issues if issue.issue_type == "gap"]
    assert len(gap_issues) == 1
    assert gap_issues[0].segment_id == first_id
    assert gap_issues[0].related_segment_id == second_id
    assert gap_issues[0].frame_start == 50
    assert gap_issues[0].frame_end_exclusive == 100


def test_validate_reports_video_end_not_covered(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="validate_gap_end")
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=0,
        end_frame_exclusive=100,
    )

    with session_factory() as db:
        response = validate_phase_annotation_set(db, annotation_set_id)

    end_issues = [issue for issue in response.issues if issue.issue_type == "video_end_not_covered"]
    assert len(end_issues) == 1
    assert end_issues[0].frame_start == 100
    assert end_issues[0].frame_end_exclusive == 400
    assert "gap" not in [issue.issue_type for issue in end_issues]


def test_validate_reports_inactive_label_warning(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="validate_inactive")
    inactive_label_id = add_label(
        session_factory,
        protocol_id=seeded.active_default_protocol_id,
        key="inactive_phase",
        name="Inactive Phase",
        display_order=9,
        color="#6b7280",
        is_active=False,
    )
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=inactive_label_id,
        start_frame=0,
        end_frame_exclusive=400,
    )

    with session_factory() as db:
        response = validate_phase_annotation_set(db, annotation_set_id)

    inactive_issues = [issue for issue in response.issues if issue.issue_type == "inactive_label"]
    assert len(inactive_issues) == 1
    assert inactive_issues[0].details["phase_label_id"] == inactive_label_id


def test_validate_reports_adjacent_same_label_warning(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="validate_adjacent_same")
    left_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=0,
        end_frame_exclusive=100,
    )
    right_id = add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=100,
        end_frame_exclusive=400,
    )

    with session_factory() as db:
        response = validate_phase_annotation_set(db, annotation_set_id)

    adjacent_issues = [issue for issue in response.issues if issue.issue_type == "adjacent_same_label"]
    assert len(adjacent_issues) == 1
    assert adjacent_issues[0].segment_id == left_id
    assert adjacent_issues[0].related_segment_id == right_id


def test_validate_reports_unusual_order_warning(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="validate_order_backwards")
    later_label_id = add_label(
        session_factory,
        protocol_id=seeded.active_default_protocol_id,
        key="later_phase",
        name="Later Phase",
        display_order=5,
        color="#22c55e",
    )
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=later_label_id,
        start_frame=0,
        end_frame_exclusive=200,
    )
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=200,
        end_frame_exclusive=400,
    )

    with session_factory() as db:
        response = validate_phase_annotation_set(db, annotation_set_id)

    unusual_issues = [issue for issue in response.issues if issue.issue_type == "unusual_order"]
    assert len(unusual_issues) == 1
    assert unusual_issues[0].details["previous_display_order"] == 5
    assert unusual_issues[0].details["current_display_order"] == 1


def test_validate_ignores_idle_for_unusual_order(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="validate_idle_ignored")
    later_label_id = add_label(
        session_factory,
        protocol_id=seeded.active_default_protocol_id,
        key="late_phase",
        name="Late Phase",
        display_order=5,
        color="#10b981",
    )
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=0,
        end_frame_exclusive=100,
    )
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=100,
        end_frame_exclusive=200,
    )
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=later_label_id,
        start_frame=200,
        end_frame_exclusive=400,
    )

    with session_factory() as db:
        response = validate_phase_annotation_set(db, annotation_set_id)

    assert "unusual_order" not in issue_types(response)


def test_validate_repeated_same_phase_does_not_report_unusual_order(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="validate_repeat_phase")
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=0,
        end_frame_exclusive=100,
    )
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=100,
        end_frame_exclusive=400,
    )

    with session_factory() as db:
        response = validate_phase_annotation_set(db, annotation_set_id)

    assert "unusual_order" not in issue_types(response)


def test_validate_reports_very_short_non_idle_segment(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="validate_short_non_idle")
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=0,
        end_frame_exclusive=2,
    )
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["viscoelastic"],
        start_frame=2,
        end_frame_exclusive=400,
    )

    with session_factory() as db:
        response = validate_phase_annotation_set(db, annotation_set_id)

    short_issues = [issue for issue in response.issues if issue.issue_type == "very_short_segment"]
    assert len(short_issues) == 1
    assert short_issues[0].details["duration_frames"] == 2
    assert short_issues[0].details["threshold_frames"] == 3


def test_validate_ignores_very_short_idle_segment(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="validate_short_idle")
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=0,
        end_frame_exclusive=2,
    )
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=2,
        end_frame_exclusive=400,
    )

    with session_factory() as db:
        response = validate_phase_annotation_set(db, annotation_set_id)

    assert "very_short_segment" not in issue_types(response)


def test_validate_duration_equal_to_threshold_does_not_warn(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="validate_threshold_equal")
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=0,
        end_frame_exclusive=3,
    )
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["viscoelastic"],
        start_frame=3,
        end_frame_exclusive=400,
    )

    with session_factory() as db:
        response = validate_phase_annotation_set(db, annotation_set_id)

    assert "very_short_segment" not in issue_types(response)


def test_calculate_closed_coverage_merges_overlap_and_clamps() -> None:
    covered = _calculate_closed_coverage(
        [
            build_segment(segment_id=1, start_frame=-10, end_frame_exclusive=20),
            build_segment(segment_id=2, start_frame=10, end_frame_exclusive=30),
            build_segment(segment_id=3, start_frame=30, end_frame_exclusive=120),
            build_segment(segment_id=4, start_frame=90, end_frame_exclusive=None),
        ],
        100,
    )

    assert covered == 100


def test_sort_validation_issues_is_stable() -> None:
    issues = [
        _validate_segment_bounds([build_segment(segment_id=3, start_frame=500, end_frame_exclusive=520)], 400)[0],
        _validate_segment_bounds([build_segment(segment_id=2, start_frame=10, end_frame_exclusive=10)], 400)[0],
        _validate_segment_bounds([build_segment(segment_id=1, start_frame=-1, end_frame_exclusive=5)], 400)[0],
    ]

    first_sorted = _sort_validation_issues(issues)
    second_sorted = _sort_validation_issues(list(reversed(issues)))

    assert [(issue.issue_type, issue.segment_id) for issue in first_sorted] == [
        ("out_of_bounds", 1),
        ("zero_length", 2),
        ("out_of_bounds", 3),
    ]
    assert [(issue.issue_type, issue.segment_id) for issue in second_sorted] == [
        ("out_of_bounds", 1),
        ("zero_length", 2),
        ("out_of_bounds", 3),
    ]


def test_validate_warning_only_remains_valid_and_requires_confirmation(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="validate_warning_only")
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=10,
        end_frame_exclusive=400,
    )

    with session_factory() as db:
        response = validate_phase_annotation_set(db, annotation_set_id)

    assert response.issue_counts.error == 0
    assert response.issue_counts.warning >= 1
    assert response.is_valid is True
    assert response.can_submit is True
    assert response.requires_warning_confirmation is True


def test_validate_error_sets_invalid_and_cannot_submit(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context

    with session_factory() as db:
        response = validate_phase_annotation_set(db, seeded.set_reader_id)

    assert response.issue_counts.error >= 1
    assert response.is_valid is False
    assert response.can_submit is False
    assert response.requires_warning_confirmation is False


def test_validate_does_not_change_revision_status_or_segments(phase_validation_context) -> None:
    session_factory, seeded = phase_validation_context
    before_snapshot = get_annotation_set_snapshot(session_factory, seeded.set_reader_id)

    with session_factory() as db:
        response = validate_phase_annotation_set(db, seeded.set_reader_id)

    after_snapshot = get_annotation_set_snapshot(session_factory, seeded.set_reader_id)
    assert response.revision == before_snapshot[0]
    assert response.status == before_snapshot[1]
    assert before_snapshot == after_snapshot


def test_validate_does_not_call_commit_or_flush(phase_validation_context, monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory, seeded = phase_validation_context

    with session_factory() as db:
        def fail_commit() -> None:
            raise AssertionError("validate should not call commit")

        def fail_flush() -> None:
            raise AssertionError("validate should not call flush")

        monkeypatch.setattr(db, "commit", fail_commit)
        monkeypatch.setattr(db, "flush", fail_flush)

        response = validate_phase_annotation_set(db, seeded.set_reader_id)

    assert response.annotation_set_id == seeded.set_reader_id
