from io import BytesIO
import json
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from PIL import Image as PILImage
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from app.db.base import Base
from app.models import Annotation, Image, Job, Label, Project, Task, User
from app.services.importers import import_labels_for_job


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with SessionLocal() as db:
        yield db

    Base.metadata.drop_all(engine)


def create_job(session: Session) -> Job:
    user = User(username="owner", email="owner@example.com")
    project = Project(name="Import Project", owner=user)
    task = Task(project=project, name="Import Job")
    job = Job(project=project, task=task, name="Import Job", status="annotation")
    job.labels = [
        Label(job=job, name="layer_up", color="#22c55e", shape_type="polygon", sort_order=0),
        Label(job=job, name="layer_down", color="#0ea5e9", shape_type="polygon", sort_order=1),
    ]
    image = Image(
        project=project,
        task=task,
        job=job,
        filename="0.png",
        file_path="/tmp/0.png",
        thumbnail_path="/tmp/0_thumb.png",
        width=64,
        height=48,
        frame_index=0,
    )
    session.add(image)
    session.commit()
    session.refresh(job)
    return job


def labelme_payload(image_path: str, label: str = "layer_up") -> bytes:
    return json.dumps(
        {
            "version": "5.0.0",
            "imagePath": image_path,
            "imageHeight": 48,
            "imageWidth": 64,
            "shapes": [
                {
                    "label": label,
                    "shape_type": "polygon",
                    "points": [[10, 10], [30, 10], [30, 30], [10, 30]],
                }
            ],
        }
    ).encode("utf-8")


def make_mask_bmp() -> bytes:
    image = PILImage.new("L", (64, 48), 0)
    for x in range(4, 18):
        for y in range(5, 20):
            image.putpixel((x, y), 1)
    buffer = BytesIO()
    image.save(buffer, format="BMP")
    return buffer.getvalue()


def test_import_labelme_appends_annotations_and_preserves_existing_job_labels(session: Session) -> None:
    job = create_job(session)

    report = import_labels_for_job(
        job=job,
        db=session,
        uploads=[("0.json", labelme_payload("0.png", "new_layer"))],
        import_format="labelme",
        import_mode="append",
        missing_label_policy="auto_create",
    )
    session.commit()

    assert report["created_annotations"] == 1
    assert report["created_labels"] == ["new_layer"]
    label_names = [
        label.name
        for label in session.scalars(
            select(Label).where(Label.job_id == job.id).order_by(Label.sort_order, Label.id)
        ).all()
    ]
    assert label_names == ["layer_up", "layer_down", "new_layer"]
    annotations = session.scalars(select(Annotation).where(Annotation.job_id == job.id)).all()
    assert len(annotations) == 1
    assert annotations[0].shape_type == "polygon"


def test_import_skip_unknown_label_keeps_existing_labels_unchanged(session: Session) -> None:
    job = create_job(session)

    report = import_labels_for_job(
        job=job,
        db=session,
        uploads=[("0.json", labelme_payload("0.png", "unknown"))],
        import_format="labelme",
        import_mode="append",
        missing_label_policy="skip",
    )
    session.commit()

    assert report["created_annotations"] == 0
    assert report["created_labels"] == []
    assert report["skipped_items"][0]["reason"] == "unknown: unknown label"
    label_names = [
        label.name
        for label in session.scalars(
            select(Label).where(Label.job_id == job.id).order_by(Label.sort_order, Label.id)
        ).all()
    ]
    assert label_names == ["layer_up", "layer_down"]


def test_import_labelme_zip_reports_unmatched_items(session: Session) -> None:
    job = create_job(session)
    archive = BytesIO()
    with ZipFile(archive, mode="w", compression=ZIP_DEFLATED) as zip_file:
        zip_file.writestr("labels/0.json", labelme_payload("0.png"))
        zip_file.writestr("labels/missing.json", labelme_payload("missing.png"))

    report = import_labels_for_job(
        job=job,
        db=session,
        uploads=[("labels.zip", archive.getvalue())],
        import_format="auto",
        import_mode="append",
        missing_label_policy="auto_create",
    )
    session.commit()

    assert report["created_annotations"] == 1
    assert report["matched_images"] == 1
    assert report["unmatched_items"] == 1


def test_replace_all_job_removes_annotations_but_not_labels(session: Session) -> None:
    job = create_job(session)
    image = session.scalar(select(Image).where(Image.job_id == job.id))
    label = session.scalar(select(Label).where(Label.job_id == job.id, Label.name == "layer_up"))
    assert image is not None
    assert label is not None
    session.add(
        Annotation(
            image_id=image.id,
            job_id=job.id,
            label_id=label.id,
            shape_type="rectangle",
            points=[[1, 1], [8, 8]],
        )
    )
    session.commit()

    report = import_labels_for_job(
        job=job,
        db=session,
        uploads=[("0.json", labelme_payload("0.png", "new_layer"))],
        import_format="labelme",
        import_mode="replace_all_job",
        missing_label_policy="auto_create",
    )
    session.commit()

    assert report["created_annotations"] == 1
    annotations = session.scalars(select(Annotation).where(Annotation.job_id == job.id)).all()
    assert len(annotations) == 1
    assert {label.name for label in session.scalars(select(Label).where(Label.job_id == job.id)).all()} == {
        "layer_up",
        "layer_down",
        "new_layer",
    }


def test_import_indexed_mask_converts_to_polygon(session: Session) -> None:
    job = create_job(session)

    report = import_labels_for_job(
        job=job,
        db=session,
        uploads=[("0_mask.bmp", make_mask_bmp())],
        import_format="mask",
        import_mode="append",
        missing_label_policy="auto_create",
    )
    session.commit()

    assert report["created_annotations"] >= 1
    annotation = session.scalar(select(Annotation).where(Annotation.job_id == job.id))
    label = session.scalar(select(Label).where(Label.job_id == job.id, Label.name == "layer_up"))
    assert annotation is not None
    assert label is not None
    assert annotation.shape_type == "polygon"
    assert annotation.label_id == label.id


def test_import_yolo_zip_uses_classes_txt_names(session: Session) -> None:
    job = create_job(session)
    archive = BytesIO()
    with ZipFile(archive, mode="w", compression=ZIP_DEFLATED) as zip_file:
        zip_file.writestr("classes.txt", "lesion\norgan\n")
        zip_file.writestr("0.txt", "0 0.1 0.1 0.5 0.1 0.5 0.5 0.1 0.5\n")

    report = import_labels_for_job(
        job=job,
        db=session,
        uploads=[("yolo.zip", archive.getvalue())],
        import_format="auto",
        import_mode="append",
        missing_label_policy="auto_create",
    )
    session.commit()

    assert report["created_annotations"] == 1
    assert "lesion" in report["created_labels"]
    assert session.scalar(select(Label).where(Label.job_id == job.id, Label.name == "lesion")) is not None
