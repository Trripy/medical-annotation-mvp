from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import ResearchPhaseAnnotationSet
from app.services.research_phase_service import (
    get_or_create_phase_annotation_set,
    get_phase_annotation_set,
    get_phase_protocol,
    list_phase_protocols,
    list_video_phase_annotation_sets,
)
from tests._research_phase_test_utils import create_phase_session_factory, seed_phase_data


@pytest.fixture()
def phase_service_context(tmp_path):
    engine, session_factory = create_phase_session_factory(tmp_path)
    seeded = seed_phase_data(session_factory)
    try:
        yield session_factory, seeded
    finally:
        engine.dispose()


def test_list_phase_protocols_excludes_archived_by_default_and_orders_results(phase_service_context) -> None:
    session_factory, seeded = phase_service_context

    with session_factory() as db:
        protocols = list_phase_protocols(db)

    assert [protocol.id for protocol in protocols] == [
        seeded.active_default_protocol_id,
        seeded.active_alpha_v2_protocol_id,
        seeded.active_alpha_v1_protocol_id,
        seeded.draft_protocol_id,
    ]
    assert [protocol.label_count for protocol in protocols] == [3, 1, 1, 1]
    assert all(protocol.id != seeded.archived_protocol_id for protocol in protocols)


def test_list_phase_protocols_includes_archived_when_requested(phase_service_context) -> None:
    session_factory, seeded = phase_service_context

    with session_factory() as db:
        protocols = list_phase_protocols(db, include_archived=True)

    assert [protocol.id for protocol in protocols] == [
        seeded.active_default_protocol_id,
        seeded.active_alpha_v2_protocol_id,
        seeded.active_alpha_v1_protocol_id,
        seeded.draft_protocol_id,
        seeded.archived_protocol_id,
    ]


@pytest.mark.parametrize(
    ("status_filter", "expected_ids"),
    [
        ("active", ["active_default_protocol_id", "active_alpha_v2_protocol_id", "active_alpha_v1_protocol_id"]),
        ("draft", ["draft_protocol_id"]),
        ("archived", ["archived_protocol_id"]),
    ],
)
def test_list_phase_protocols_supports_status_filters(
    phase_service_context,
    status_filter: str,
    expected_ids: list[str],
) -> None:
    session_factory, seeded = phase_service_context

    with session_factory() as db:
        protocols = list_phase_protocols(db, status_filter=status_filter)

    assert [protocol.id for protocol in protocols] == [getattr(seeded, attribute_name) for attribute_name in expected_ids]


def test_list_phase_protocols_rejects_invalid_status_filter(phase_service_context) -> None:
    session_factory, _seeded = phase_service_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            list_phase_protocols(db, status_filter="unknown")

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Invalid protocol status filter."


def test_get_phase_protocol_returns_sorted_labels(phase_service_context) -> None:
    session_factory, seeded = phase_service_context

    with session_factory() as db:
        protocol = get_phase_protocol(db, seeded.active_default_protocol_id)

    assert protocol.id == seeded.active_default_protocol_id
    assert protocol.label_count == 3
    assert [label.key for label in protocol.labels] == ["idle", "viscoelastic", "incision"]
    assert [label.display_order for label in protocol.labels] == [0, 1, 1]
    assert [label.id for label in protocol.labels[1:]] == sorted([label.id for label in protocol.labels[1:]])


def test_get_phase_protocol_returns_404_for_missing_protocol(phase_service_context) -> None:
    session_factory, _seeded = phase_service_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            get_phase_protocol(db, 999999)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Phase protocol not found."


def test_list_video_phase_annotation_sets_returns_all_users_with_counts_and_open_flags(phase_service_context) -> None:
    session_factory, seeded = phase_service_context

    with session_factory() as db:
        annotation_sets = list_video_phase_annotation_sets(db, seeded.video_id)

    assert {annotation_set.annotator_username for annotation_set in annotation_sets} == {"reader", "reviewer"}
    assert {annotation_set.id for annotation_set in annotation_sets} == {seeded.set_reader_id, seeded.set_reviewer_id}

    annotation_sets_by_id = {annotation_set.id: annotation_set for annotation_set in annotation_sets}
    reader_set = annotation_sets_by_id[seeded.set_reader_id]
    reviewer_set = annotation_sets_by_id[seeded.set_reviewer_id]

    assert reader_set.segment_count == 2
    assert reader_set.has_open_segment is True
    assert reader_set.protocol_name == "Default Cataract"
    assert reviewer_set.segment_count == 1
    assert reviewer_set.has_open_segment is False


def test_list_video_phase_annotation_sets_returns_404_for_missing_video(phase_service_context) -> None:
    session_factory, _seeded = phase_service_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            list_video_phase_annotation_sets(db, 999999)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Research video not found."


def test_get_phase_annotation_set_returns_sorted_segments_and_phase_labels(phase_service_context) -> None:
    session_factory, seeded = phase_service_context

    with session_factory() as db:
        annotation_set = get_phase_annotation_set(db, seeded.set_reader_id)

    assert annotation_set.id == seeded.set_reader_id
    assert annotation_set.protocol.id == seeded.active_default_protocol_id
    assert [label.key for label in annotation_set.protocol.labels] == ["idle", "viscoelastic", "incision"]
    assert [segment.start_frame for segment in annotation_set.segments] == [10, 120]
    assert annotation_set.segments[0].phase_label.key == "idle"
    assert annotation_set.segments[1].phase_label.key == "viscoelastic"
    assert annotation_set.segment_count == 2
    assert annotation_set.has_open_segment is True


def test_get_phase_annotation_set_returns_404_for_missing_set(phase_service_context) -> None:
    session_factory, _seeded = phase_service_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            get_phase_annotation_set(db, 999999)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Phase annotation set not found."


def test_get_or_create_phase_annotation_set_creates_and_reuses_same_record(phase_service_context) -> None:
    session_factory, seeded = phase_service_context

    with session_factory() as db:
        created_response = get_or_create_phase_annotation_set(
            db,
            video_id=seeded.video_id,
            protocol_id=seeded.active_alpha_v2_protocol_id,
            username="  reader  ",
        )

    assert created_response.created is True
    assert created_response.annotation_set.protocol_id == seeded.active_alpha_v2_protocol_id
    assert created_response.annotation_set.annotator_username == "reader"
    assert created_response.annotation_set.segment_count == 0
    assert created_response.annotation_set.segments == []

    with session_factory() as db:
        existing_response = get_or_create_phase_annotation_set(
            db,
            video_id=seeded.video_id,
            protocol_id=seeded.active_alpha_v2_protocol_id,
            username="reader",
        )

    assert existing_response.created is False
    assert existing_response.annotation_set.id == created_response.annotation_set.id


def test_get_or_create_phase_annotation_set_allows_different_users(phase_service_context) -> None:
    session_factory, seeded = phase_service_context

    with session_factory() as db:
        reader_response = get_or_create_phase_annotation_set(
            db,
            video_id=seeded.video_id,
            protocol_id=seeded.active_alpha_v1_protocol_id,
            username="reader",
        )

    with session_factory() as db:
        reviewer_response = get_or_create_phase_annotation_set(
            db,
            video_id=seeded.video_id,
            protocol_id=seeded.active_alpha_v1_protocol_id,
            username="reviewer",
        )

    assert reader_response.created is True
    assert reviewer_response.created is True
    assert reader_response.annotation_set.id != reviewer_response.annotation_set.id
    assert reader_response.annotation_set.annotator_id != reviewer_response.annotation_set.annotator_id


@pytest.mark.parametrize("protocol_attribute", ["draft_protocol_id", "archived_protocol_id"])
def test_get_or_create_phase_annotation_set_rejects_non_active_protocols(
    phase_service_context,
    protocol_attribute: str,
) -> None:
    session_factory, seeded = phase_service_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            get_or_create_phase_annotation_set(
                db,
                video_id=seeded.video_id,
                protocol_id=getattr(seeded, protocol_attribute),
                username="reader",
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "New annotation sets can only use an active phase protocol."


def test_get_or_create_phase_annotation_set_returns_404_for_missing_video(phase_service_context) -> None:
    session_factory, seeded = phase_service_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            get_or_create_phase_annotation_set(
                db,
                video_id=999999,
                protocol_id=seeded.active_alpha_v2_protocol_id,
                username="reader",
            )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Research video not found."


def test_get_or_create_phase_annotation_set_returns_404_for_missing_user(phase_service_context) -> None:
    session_factory, seeded = phase_service_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            get_or_create_phase_annotation_set(
                db,
                video_id=seeded.video_id,
                protocol_id=seeded.active_alpha_v2_protocol_id,
                username="missing-user",
            )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "User not found."


def test_get_or_create_phase_annotation_set_rejects_blank_username(phase_service_context) -> None:
    session_factory, seeded = phase_service_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            get_or_create_phase_annotation_set(
                db,
                video_id=seeded.video_id,
                protocol_id=seeded.active_alpha_v2_protocol_id,
                username="   ",
            )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Username cannot be empty."


def test_get_or_create_phase_annotation_set_recovers_from_integrity_error_race(
    phase_service_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, seeded = phase_service_context

    with session_factory() as db:
        target_protocol_id = seeded.active_alpha_v2_protocol_id
        target_video_id = seeded.video_id
        original_commit = db.commit
        commit_calls = 0

        def commit_with_race() -> None:
            nonlocal commit_calls
            commit_calls += 1
            if commit_calls > 1:
                original_commit()
                return

            with session_factory() as other_db:
                other_db.add(
                    ResearchPhaseAnnotationSet(
                        video_id=target_video_id,
                        protocol_id=target_protocol_id,
                        annotator_id=seeded.reviewer_user_id,
                        status="draft",
                        revision=1,
                    )
                )
                other_db.commit()
            raise IntegrityError("simulated unique conflict", params=None, orig=Exception("unique"))

        monkeypatch.setattr(db, "commit", commit_with_race)
        response = get_or_create_phase_annotation_set(
            db,
            video_id=target_video_id,
            protocol_id=target_protocol_id,
            username="reviewer",
        )

    assert response.created is False
    assert response.annotation_set.protocol_id == target_protocol_id
    assert response.annotation_set.annotator_username == "reviewer"

    with session_factory() as db:
        annotation_sets = db.scalars(
            select(ResearchPhaseAnnotationSet).where(
                ResearchPhaseAnnotationSet.video_id == seeded.video_id,
                ResearchPhaseAnnotationSet.protocol_id == seeded.active_alpha_v2_protocol_id,
                ResearchPhaseAnnotationSet.annotator_id == seeded.reviewer_user_id,
            )
        ).all()

    assert len(annotation_sets) == 1
