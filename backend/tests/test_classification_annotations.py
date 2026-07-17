from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from PIL import Image as PILImage
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import jobs as jobs_api
from app.api.v1 import tasks as tasks_api
from app.core.config import settings
from app.db.base import Base
from app.models import Job
from app.models import Label, Project, User
from app.schemas.annotation import AnnotationSaveRequest
from app.schemas.job import JobLabelPayload
from app.schemas.task import TaskCreate
from app.services.export_visual import (
    build_job_color_mask_zip,
    build_job_indexed_mask_zip,
    build_job_overlay_zip,
)
from app.services.labelme_export import build_job_labelme_zip


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)

    original_local_storage_root = settings.local_storage_root
    settings.local_storage_root = str(tmp_path)

    with TestingSessionLocal() as db:
        owner = User(username="owner", email="owner@example.com")
        project = Project(name="Classification Project", owner=owner)
        project.labels = [
            Label(name="Nodule", color="#22c55e"),
            Label(name="Organ", color="#0ea5e9"),
        ]
        db.add(project)
        db.commit()

    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        settings.local_storage_root = original_local_storage_root
        Base.metadata.drop_all(engine)
        engine.dispose()


def make_png_bytes(size: tuple[int, int] = (32, 24)) -> BytesIO:
    buffer = BytesIO()
    PILImage.new("RGB", size, color=(12, 82, 91)).save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def make_upload_file(filename: str, size: tuple[int, int] = (32, 24)):
    from fastapi import UploadFile

    return UploadFile(file=make_png_bytes(size), filename=filename)


def test_save_classification_annotation_with_empty_points(db_session: Session) -> None:
    task = tasks_api.create_task(TaskCreate(project_id=1, name="Classification Save"), db_session)
    upload_response = tasks_api.upload_task_data(
        task.id,
        files=[make_upload_file("slice.png", (100, 80))],
        db=db_session,
    )
    detail = jobs_api.get_job(upload_response.job_id, db_session)

    classification_label = jobs_api.create_job_label(
        upload_response.job_id,
        payload=JobLabelPayload(name="valid", color="#f97316", shape_type="classification"),
        db=db_session,
    )

    saved_annotations = jobs_api.save_image_annotations(
        upload_response.job_id,
        upload_response.images[0].id,
        AnnotationSaveRequest.model_validate(
            {
                "annotations": [
                    {
                        "label_id": detail.labels[0].id,
                        "shape_type": "polygon",
                        "points": [[20, 20], [40, 20], [35, 50]],
                    },
                    {
                        "label_id": classification_label.id,
                        "shape_type": "classification",
                        "points": [],
                        "attributes": {
                            "annotation_kind": "image_classification",
                            "classification": True,
                        },
                    },
                ]
            }
        ),
        db_session,
    )

    assert len(saved_annotations) == 2
    assert saved_annotations[1].shape_type == "classification"
    assert saved_annotations[1].points == []
    assert saved_annotations[1].attributes == {
        "annotation_kind": "image_classification",
        "classification": True,
    }


def test_job_read_returns_classification_label_frame_count(db_session: Session) -> None:
    task = tasks_api.create_task(TaskCreate(project_id=1, name="Classification Read"), db_session)
    upload_response = tasks_api.upload_task_data(
        task.id,
        files=[
            make_upload_file("0.png", (100, 80)),
            make_upload_file("1.png", (100, 80)),
        ],
        db=db_session,
    )
    classification_label = jobs_api.create_job_label(
        upload_response.job_id,
        payload=JobLabelPayload(name="disturb", color="#ef4444", shape_type="classification"),
        db=db_session,
    )

    for image in upload_response.images:
        jobs_api.save_image_annotations(
            upload_response.job_id,
            image.id,
            AnnotationSaveRequest.model_validate(
                {
                    "annotations": [
                        {
                            "label_id": classification_label.id,
                            "shape_type": "classification",
                            "points": [],
                            "attributes": {
                                "annotation_kind": "image_classification",
                                "classification": True,
                            },
                        }
                    ]
                }
            ),
            db_session,
        )

    labels = jobs_api.list_job_labels(upload_response.job_id, db_session)
    loaded_classification = next(label for label in labels if label.id == classification_label.id)

    assert loaded_classification.annotation_count == 2
    assert loaded_classification.frame_count == 2


def test_labelme_export_skips_classification_annotations(db_session: Session) -> None:
    task = tasks_api.create_task(TaskCreate(project_id=1, name="Classification LabelMe"), db_session)
    upload_response = tasks_api.upload_task_data(
        task.id,
        files=[make_upload_file("slice.png", (100, 80))],
        db=db_session,
    )
    detail = jobs_api.get_job(upload_response.job_id, db_session)
    classification_label = jobs_api.create_job_label(
        upload_response.job_id,
        payload=JobLabelPayload(name="unclear", color="#eab308", shape_type="classification"),
        db=db_session,
    )

    jobs_api.save_image_annotations(
        upload_response.job_id,
        upload_response.images[0].id,
        AnnotationSaveRequest.model_validate(
            {
                "annotations": [
                    {
                        "label_id": detail.labels[0].id,
                        "shape_type": "rectangle",
                        "points": [[10, 12], [50, 44]],
                    },
                    {
                        "label_id": classification_label.id,
                        "shape_type": "classification",
                        "points": [],
                        "attributes": {
                            "annotation_kind": "image_classification",
                            "classification": True,
                        },
                    },
                ]
            }
        ),
        db_session,
    )

    job = db_session.get(Job, upload_response.job_id)
    assert job is not None

    with ZipFile(build_job_labelme_zip(job, db_session)) as archive:
        labelme = json.loads(archive.read("slice.json"))

    assert [shape["shape_type"] for shape in labelme["shapes"]] == ["polygon"]
    assert [shape["label"] for shape in labelme["shapes"]] == [detail.labels[0].name]


def test_visual_exports_skip_classification_annotations(db_session: Session) -> None:
    task = tasks_api.create_task(TaskCreate(project_id=1, name="Classification Visual Export"), db_session)
    upload_response = tasks_api.upload_task_data(
        task.id,
        files=[make_upload_file("slice.png", (64, 48))],
        db=db_session,
    )
    classification_label = jobs_api.create_job_label(
        upload_response.job_id,
        payload=JobLabelPayload(name="valid", color="#f97316", shape_type="classification"),
        db=db_session,
    )

    jobs_api.save_image_annotations(
        upload_response.job_id,
        upload_response.images[0].id,
        AnnotationSaveRequest.model_validate(
            {
                "annotations": [
                    {
                        "label_id": classification_label.id,
                        "shape_type": "classification",
                        "points": [],
                        "attributes": {
                            "annotation_kind": "image_classification",
                            "classification": True,
                        },
                    }
                ]
            }
        ),
        db_session,
    )

    job = db_session.get(Job, upload_response.job_id)
    assert job is not None
    original_image = PILImage.open(make_png_bytes((64, 48))).convert("RGB")

    with ZipFile(build_job_overlay_zip(job, db_session)) as archive:
        overlay = PILImage.open(BytesIO(archive.read("slice_overlay.png")))
        assert overlay.tobytes() == original_image.tobytes()

    with ZipFile(build_job_indexed_mask_zip(job, db_session)) as archive:
        indexed_mask = PILImage.open(BytesIO(archive.read("slice_mask.png")))
        assert indexed_mask.getbbox() is None

    with ZipFile(build_job_color_mask_zip(job, db_session)) as archive:
        color_mask = PILImage.open(BytesIO(archive.read("slice_color_mask.png")))
        assert color_mask.getbbox() is None


def test_non_classification_annotations_still_require_shape_points() -> None:
    with pytest.raises(ValueError, match="polygon annotations require at least 3 point"):
        AnnotationSaveRequest.model_validate(
            {
                "annotations": [
                    {
                        "label_id": 1,
                        "shape_type": "polygon",
                        "points": [[10, 10], [20, 20]],
                    }
                ]
            }
        )

    with pytest.raises(ValueError, match="rectangle annotations require at least 2 point"):
        AnnotationSaveRequest.model_validate(
            {
                "annotations": [
                    {
                        "label_id": 1,
                        "shape_type": "rectangle",
                        "points": [[10, 10]],
                    }
                ]
            }
        )

    with pytest.raises(ValueError, match="point annotations require at least 1 point"):
        AnnotationSaveRequest.model_validate(
            {
                "annotations": [
                    {
                        "label_id": 1,
                        "shape_type": "point",
                        "points": [],
                    }
                ]
            }
        )
