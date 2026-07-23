import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import (
    Annotation,
    Image,
    Job,
    Label,
    Project,
    ResearchVideo,
    ResearchVideoAnnotation,
    ResearchVideoFrame,
    ResearchVideoLabel,
    Task,
    User,
)


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session


def test_metadata_contains_core_tables() -> None:
    assert {
        "users",
        "projects",
        "labels",
        "tasks",
        "jobs",
        "images",
        "annotations",
        "research_phase_protocols",
        "research_phase_labels",
        "research_phase_annotation_sets",
        "research_phase_segments",
        "research_videos",
        "research_video_frames",
        "research_video_labels",
        "research_video_annotations",
    }.issubset(Base.metadata.tables.keys())


def test_can_create_project_task_image_and_polygon_annotation(session: Session) -> None:
    user = User(username="reader", email="reader@example.com", full_name="Reader")
    project = Project(name="Chest CT", owner=user)
    label = Label(project=project, name="Nodule", color="#22c55e")
    task = Task(project=project, name="Round 1")
    job = Job(task=task, assignee=user)
    image = Image(
        project=project,
        task=task,
        filename="series-001.png",
        file_path="data/images/series-001.png",
        thumbnail_path="data/thumbnails/series-001.png",
        width=512,
        height=512,
        modality="CT",
    )
    annotation = Annotation(
        image=image,
        label=label,
        job=job,
        created_by=user,
        shape_type="polygon",
        points=[[100.0, 120.0], [140.0, 125.0], [130.0, 160.0]],
    )

    session.add(annotation)
    session.commit()

    assert annotation.id is not None
    assert annotation.points[0] == [100.0, 120.0]
    assert image.annotations == [annotation]
    assert project.labels == [label]


def test_annotation_shape_type_is_limited(session: Session) -> None:
    user = User(username="owner", email="owner@example.com")
    project = Project(name="MR Brain", owner=user)
    label = Label(project=project, name="Lesion")
    image = Image(
        project=project,
        filename="slice.png",
        file_path="data/images/slice.png",
        thumbnail_path="data/thumbnails/slice.png",
    )
    annotation = Annotation(
        image=image,
        label=label,
        shape_type="mask",
        points=[[1.0, 2.0]],
    )

    session.add(annotation)

    with pytest.raises(IntegrityError):
        session.commit()


def test_can_create_research_video_frame_label_and_annotation(session: Session) -> None:
    user = User(username="researcher", email="researcher@example.com")
    video = ResearchVideo(
        name="case001",
        original_filename="case001.mp4",
        file_path="/tmp/case001.mp4",
        thumbnail_path="/tmp/case001.jpg",
        width=320,
        height=240,
        fps=30.0,
        frame_count=2,
        duration_ms=67,
        status="ready",
        created_by=user,
    )
    frame = ResearchVideoFrame(
        video=video,
        frame_index=0,
        timestamp_ms=0,
        filename="000000.jpg",
        file_path="/tmp/frames/000000.jpg",
        width=320,
        height=240,
    )
    label = ResearchVideoLabel(
        video=video,
        name="layer_up",
        color="#22c55e",
        shape_type="polygon",
        sort_order=0,
    )
    annotation = ResearchVideoAnnotation(
        video=video,
        frame=frame,
        frame_index=0,
        label=label,
        shape_type="polygon",
        points=[[10.0, 12.0], [18.0, 12.0], [18.0, 20.0]],
        visible=True,
    )

    session.add(annotation)
    session.commit()

    assert annotation.id is not None
    assert video.frames == [frame]
    assert video.labels == [label]
    assert frame.annotations == [annotation]
