import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import (
    ResearchPhaseAnnotationSet,
    ResearchPhaseLabel,
    ResearchPhaseProtocol,
    ResearchPhaseSegment,
    ResearchVideo,
    User,
)


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session


def build_user(username: str = "annotator") -> User:
    return User(
        username=username,
        email=f"{username}@example.com",
        full_name=username.title(),
    )


def build_video(created_by: User, name: str = "case001") -> ResearchVideo:
    return ResearchVideo(
        name=name,
        original_filename=f"{name}.mp4",
        file_path=f"/tmp/{name}.mp4",
        thumbnail_path=f"/tmp/{name}.jpg",
        width=640,
        height=480,
        fps=25.0,
        frame_count=300,
        duration_ms=12_000,
        status="ready",
        created_by=created_by,
    )


def build_protocol(name: str = "Cataract Surgery Phases", version: int = 1) -> ResearchPhaseProtocol:
    return ResearchPhaseProtocol(
        name=name,
        version=version,
        description="Protocol used for testing.",
        status="active",
        is_default=False,
    )


def build_label(
    protocol: ResearchPhaseProtocol,
    *,
    key: str,
    name: str,
    display_order: int,
    color: str = "#64748B",
    shortcut: str | None = None,
) -> ResearchPhaseLabel:
    return ResearchPhaseLabel(
        protocol=protocol,
        key=key,
        name=name,
        color=color,
        display_order=display_order,
        shortcut=shortcut,
        is_active=True,
    )


def build_annotation_set(
    *,
    video: ResearchVideo,
    protocol: ResearchPhaseProtocol,
    annotator: User,
    status: str = "draft",
    revision: int | None = None,
) -> ResearchPhaseAnnotationSet:
    annotation_set = ResearchPhaseAnnotationSet(
        video=video,
        protocol=protocol,
        annotator=annotator,
        status=status,
    )
    if revision is not None:
        annotation_set.revision = revision
    return annotation_set


def prepare_annotation_target(session: Session) -> tuple[User, ResearchVideo, ResearchPhaseProtocol, ResearchPhaseLabel]:
    annotator = build_user()
    video = build_video(annotator)
    protocol = build_protocol()
    label = build_label(protocol, key="idle", name="Idle", display_order=0)
    session.add_all([annotator, video, protocol, label])
    session.commit()
    return annotator, video, protocol, label


def test_can_create_phase_protocol_annotation_set_and_segments(session: Session) -> None:
    annotator, video, protocol, label = prepare_annotation_target(session)
    phaco = build_label(
        protocol,
        key="phacoemulsification",
        name="Phacoemulsification",
        display_order=1,
        color="#EF4444",
    )
    annotation_set = build_annotation_set(video=video, protocol=protocol, annotator=annotator)
    first_segment = ResearchPhaseSegment(
        annotation_set=annotation_set,
        phase_label=label,
        start_frame=10,
        end_frame_exclusive=20,
        source="manual",
    )
    second_segment = ResearchPhaseSegment(
        annotation_set=annotation_set,
        phase_label=phaco,
        start_frame=30,
        end_frame_exclusive=40,
        source="manual",
    )
    third_segment = ResearchPhaseSegment(
        annotation_set=annotation_set,
        phase_label=label,
        start_frame=50,
        end_frame_exclusive=None,
        source="manual",
    )

    session.add_all([phaco, annotation_set, first_segment, second_segment, third_segment])
    session.commit()
    session.refresh(annotation_set)

    assert annotation_set.revision == 1
    assert [segment.start_frame for segment in annotation_set.segments] == [10, 30, 50]
    assert annotation_set.segments[0].end_frame_exclusive == 20
    assert annotation_set.segments[-1].end_frame_exclusive is None
    assert annotation_set.segments[0].phase_label.key == "idle"
    assert annotation_set.segments[-1].phase_label.key == "idle"


def test_protocol_constraints_reject_invalid_versions_and_duplicates(session: Session) -> None:
    invalid_protocol = build_protocol(name="Invalid Protocol", version=0)
    session.add(invalid_protocol)

    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()

    protocol = build_protocol(name="Versioned Protocol", version=1)
    session.add(protocol)
    session.commit()

    duplicate_protocol = build_protocol(name="Versioned Protocol", version=1)
    session.add(duplicate_protocol)

    with pytest.raises(IntegrityError):
        session.commit()


def test_label_constraints_reject_duplicates_and_negative_display_order(session: Session) -> None:
    protocol = build_protocol(name="Label Protocol", version=1)
    primary_label = build_label(protocol, key="idle", name="Idle", display_order=0)
    session.add_all([protocol, primary_label])
    session.commit()

    duplicate_key_label = build_label(protocol, key="idle", name="Duplicate Idle", display_order=1)
    session.add(duplicate_key_label)
    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()

    duplicate_name_label = build_label(protocol, key="incision", name="Idle", display_order=1)
    session.add(duplicate_name_label)
    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()

    negative_order_label = build_label(protocol, key="phaco", name="Phaco", display_order=-1)
    session.add(negative_order_label)
    with pytest.raises(IntegrityError):
        session.commit()


def test_annotation_set_constraints_reject_duplicates_invalid_revision_and_invalid_status(
    session: Session,
) -> None:
    annotator, video, protocol, _label = prepare_annotation_target(session)

    annotation_set = build_annotation_set(video=video, protocol=protocol, annotator=annotator)
    session.add(annotation_set)
    session.commit()
    assert annotation_set.revision == 1

    duplicate_annotation_set = build_annotation_set(video=video, protocol=protocol, annotator=annotator)
    session.add(duplicate_annotation_set)
    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()

    invalid_revision_set = build_annotation_set(
        video=video,
        protocol=protocol,
        annotator=annotator,
        revision=0,
    )
    session.add(invalid_revision_set)
    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()

    invalid_status_set = build_annotation_set(
        video=video,
        protocol=protocol,
        annotator=annotator,
        status="invalid",
    )
    session.add(invalid_status_set)
    with pytest.raises(IntegrityError):
        session.commit()


def test_segment_constraints_reject_invalid_ranges_and_confidence(session: Session) -> None:
    annotator, video, protocol, label = prepare_annotation_target(session)
    annotation_set = build_annotation_set(video=video, protocol=protocol, annotator=annotator)
    session.add(annotation_set)
    session.commit()

    invalid_start_segment = ResearchPhaseSegment(
        annotation_set=annotation_set,
        phase_label=label,
        start_frame=-1,
        end_frame_exclusive=10,
        source="manual",
    )
    session.add(invalid_start_segment)
    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()

    invalid_end_segment = ResearchPhaseSegment(
        annotation_set=annotation_set,
        phase_label=label,
        start_frame=10,
        end_frame_exclusive=10,
        source="manual",
    )
    session.add(invalid_end_segment)
    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()

    low_confidence_segment = ResearchPhaseSegment(
        annotation_set=annotation_set,
        phase_label=label,
        start_frame=10,
        end_frame_exclusive=20,
        source="manual",
        confidence=-0.1,
    )
    session.add(low_confidence_segment)
    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()

    high_confidence_segment = ResearchPhaseSegment(
        annotation_set=annotation_set,
        phase_label=label,
        start_frame=10,
        end_frame_exclusive=20,
        source="manual",
        confidence=1.1,
    )
    session.add(high_confidence_segment)
    with pytest.raises(IntegrityError):
        session.commit()
