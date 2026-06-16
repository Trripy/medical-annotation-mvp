import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1 import jobs as jobs_api
from app.db.base import Base
from app.models import Annotation, Image, Job, Label, Project, Task, User
from app.schemas.job import JobLabelDeleteRequest, JobLabelPayload


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with SessionLocal() as db:
        yield db

    Base.metadata.drop_all(engine)
    engine.dispose()


def create_job(session: Session) -> Job:
    user = User(username="label_owner", email="label-owner@example.com")
    project = Project(name="Label Project", owner=user)
    task = Task(project=project, name="Label Job")
    job = Job(project=project, task=task, name="Label Job", status="annotation")
    job.labels = [
        Label(job=job, name="layer_up", color="#22c55e", shape_type="polygon", sort_order=0),
        Label(job=job, name="layer_down", color="#0ea5e9", shape_type="polygon", sort_order=1),
    ]
    images = [
        Image(
            project=project,
            task=task,
            job=job,
            filename="0.png",
            file_path="/tmp/0.png",
            thumbnail_path="/tmp/0_thumb.png",
            width=64,
            height=48,
            frame_index=0,
        ),
        Image(
            project=project,
            task=task,
            job=job,
            filename="1.png",
            file_path="/tmp/1.png",
            thumbnail_path="/tmp/1_thumb.png",
            width=64,
            height=48,
            frame_index=1,
        ),
    ]
    session.add_all(images)
    session.commit()
    session.refresh(job)
    return job


def add_annotation(session: Session, job: Job, label: Label, image: Image | None = None) -> Annotation:
    target_image = image or session.scalar(select(Image).where(Image.job_id == job.id).order_by(Image.id))
    assert target_image is not None
    annotation = Annotation(
        image_id=target_image.id,
        job_id=job.id,
        label_id=label.id,
        shape_type="polygon",
        points=[[1, 1], [8, 1], [8, 8]],
    )
    session.add(annotation)
    session.commit()
    return annotation


def labels_by_name(session: Session, job: Job) -> dict[str, Label]:
    return {
        label.name: label
        for label in session.scalars(
            select(Label).where(Label.job_id == job.id).order_by(Label.sort_order, Label.id)
        ).all()
    }


def test_create_and_update_job_label(session: Session) -> None:
    job = create_job(session)

    created = jobs_api.create_job_label(
        job.id,
        JobLabelPayload(name=" new layer ", color="#f97316", shape_type="rectangle"),
        session,
    )

    assert created.name == "new layer"
    assert created.color == "#f97316"
    assert created.shape_type == "rectangle"
    assert created.annotation_count == 0

    updated = jobs_api.update_job_label(
        job.id,
        created.id,
        JobLabelPayload(name="new_layer_renamed", color="#111827", shape_type="polygon"),
        session,
    )

    assert updated.name == "new_layer_renamed"
    assert updated.color == "#111827"
    assert updated.shape_type == "polygon"


def test_delete_unused_job_label(session: Session) -> None:
    job = create_job(session)
    label = jobs_api.create_job_label(
        job.id,
        JobLabelPayload(name="unused", color="#f97316", shape_type="polygon"),
        session,
    )

    response = jobs_api.delete_job_label(job.id, label.id, None, session)

    assert response.deleted_label_id == label.id
    assert response.affected_annotations == 0
    assert session.get(Label, label.id) is None


def test_delete_used_label_requires_strategy_and_can_reassign(session: Session) -> None:
    job = create_job(session)
    labels = labels_by_name(session, job)
    annotation = add_annotation(session, job, labels["layer_up"])

    usage = jobs_api.get_job_label_usage(job.id, labels["layer_up"].id, session)
    assert usage.annotation_count == 1
    assert usage.frame_count == 1

    with pytest.raises(HTTPException):
        jobs_api.delete_job_label(job.id, labels["layer_up"].id, None, session)

    response = jobs_api.delete_job_label(
        job.id,
        labels["layer_up"].id,
        JobLabelDeleteRequest(strategy="reassign", target_label_id=labels["layer_down"].id),
        session,
    )

    session.refresh(annotation)
    assert response.affected_annotations == 1
    assert response.target_label == "layer_down"
    assert annotation.label_id == labels["layer_down"].id
    assert session.get(Label, labels["layer_up"].id) is None


def test_delete_used_label_can_move_annotations_to_undefined(session: Session) -> None:
    job = create_job(session)
    labels = labels_by_name(session, job)
    annotation = add_annotation(session, job, labels["layer_up"])
    annotation_id = annotation.id

    response = jobs_api.delete_job_label(
        job.id,
        labels["layer_up"].id,
        JobLabelDeleteRequest(strategy="move_to_undefined"),
        session,
    )

    undefined_label = session.scalar(select(Label).where(Label.job_id == job.id, Label.name == "undefined"))
    assert undefined_label is not None
    session.refresh(annotation)
    assert response.affected_annotations == 1
    assert response.target_label == "undefined"
    assert annotation.label_id == undefined_label.id


def test_delete_used_label_can_delete_annotations(session: Session) -> None:
    job = create_job(session)
    labels = labels_by_name(session, job)
    annotation = add_annotation(session, job, labels["layer_up"])
    annotation_id = annotation.id

    response = jobs_api.delete_job_label(
        job.id,
        labels["layer_up"].id,
        JobLabelDeleteRequest(strategy="delete_annotations"),
        session,
    )

    assert response.affected_annotations == 1
    assert session.get(Annotation, annotation_id) is None
    assert session.get(Label, labels["layer_up"].id) is None


def test_delete_unused_undefined_label_is_allowed(session: Session) -> None:
    job = create_job(session)
    undefined = jobs_api.create_job_label(
        job.id,
        JobLabelPayload(name="undefined", color="#9CA3AF", shape_type="polygon"),
        session,
    )

    response = jobs_api.delete_job_label(job.id, undefined.id, None, session)

    assert response.deleted_label_id == undefined.id
    assert response.affected_annotations == 0
    assert session.get(Label, undefined.id) is None


def test_delete_used_undefined_label_can_reassign_or_delete_but_not_move_to_undefined(session: Session) -> None:
    job = create_job(session)
    undefined = jobs_api.create_job_label(
        job.id,
        JobLabelPayload(name="undefined", color="#9CA3AF", shape_type="polygon"),
        session,
    )
    labels = labels_by_name(session, job)
    annotation = add_annotation(session, job, undefined)

    with pytest.raises(HTTPException):
        jobs_api.delete_job_label(
            job.id,
            undefined.id,
            JobLabelDeleteRequest(strategy="move_to_undefined"),
            session,
        )

    response = jobs_api.delete_job_label(
        job.id,
        undefined.id,
        JobLabelDeleteRequest(strategy="reassign", target_label_id=labels["layer_up"].id),
        session,
    )

    session.refresh(annotation)
    assert response.affected_annotations == 1
    assert response.target_label == "layer_up"
    assert annotation.label_id == labels["layer_up"].id
    assert session.get(Label, undefined.id) is None

    undefined_again = jobs_api.create_job_label(
        job.id,
        JobLabelPayload(name="undefined", color="#9CA3AF", shape_type="polygon"),
        session,
    )
    annotation = add_annotation(session, job, undefined_again)
    annotation_id = annotation.id

    response = jobs_api.delete_job_label(
        job.id,
        undefined_again.id,
        JobLabelDeleteRequest(strategy="delete_annotations"),
        session,
    )

    assert response.affected_annotations == 1
    assert session.get(Annotation, annotation_id) is None
    assert session.get(Label, undefined_again.id) is None
