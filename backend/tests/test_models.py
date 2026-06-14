import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import Annotation, Image, Job, Label, Project, Task, User


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
    }.issubset(Base.metadata.tables.keys())


def test_can_create_project_task_image_and_polygon_annotation(session: Session) -> None:
    user = User(email="reader@example.com", full_name="Reader")
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
    user = User(email="owner@example.com")
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
