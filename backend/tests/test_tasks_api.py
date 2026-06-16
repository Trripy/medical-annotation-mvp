from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi import UploadFile
from PIL import Image as PILImage
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import datasets as datasets_api
from app.api.v1 import images as images_api
from app.api.v1 import jobs as jobs_api
from app.api.v1 import projects as projects_api
from app.api.v1 import tasks as tasks_api
from app.core.config import settings
from app.db.base import Base
from app.models import Label, Project, User
from app.schemas.annotation import AnnotationSaveRequest
from app.schemas.job import JobRead
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate
from app.services.labelme_export import build_labelme_zip


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
        project = Project(name="Upload Project", owner=owner)
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


def make_png(size: tuple[int, int] = (32, 24)) -> BytesIO:
    buffer = BytesIO()
    PILImage.new("RGB", size, color=(12, 82, 91)).save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def make_upload(filename: str, size: tuple[int, int] = (32, 24)) -> UploadFile:
    return UploadFile(file=make_png(size), filename=filename)


def test_create_task(db_session: Session) -> None:
    task = tasks_api.create_task(
        TaskCreate(project_id=1, name="Upload CT", description="Initial upload"),
        db_session,
    )

    assert task.id == 1
    assert task.project_id == 1
    assert task.name == "Upload CT"


def test_upload_images_creates_images_thumbnails_and_job(db_session: Session, tmp_path: Path) -> None:
    task = tasks_api.create_task(TaskCreate(project_id=1, name="Upload CT"), db_session)

    body = tasks_api.upload_task_data(
        task.id,
        files=[
            make_upload("slice-1.png", (64, 48)),
            make_upload("slice-2.png", (40, 30)),
        ],
        db=db_session,
    )

    assert body.task_id == task.id
    assert body.job_id == 1
    assert len(body.images) == 2

    first_image = body.images[0]
    assert first_image.filename == "slice-1.png"
    assert first_image.width == 64
    assert first_image.height == 48
    assert Path(first_image.file_path).is_file()
    assert Path(first_image.thumbnail_path).is_file()
    assert Path(first_image.file_path).parent == tmp_path / "data" / "images"
    assert Path(first_image.thumbnail_path).parent == tmp_path / "data" / "thumbnails"

    jobs = jobs_api.list_jobs(db_session)

    assert jobs == [
        JobRead(
            id=1,
            project_id=1,
            project_name="Upload Project",
            name="Upload CT",
            status="pending",
            task_id=task.id,
            frames=2,
            thumbnail_url=jobs[0].thumbnail_url,
        )
    ]
    assert jobs[0].thumbnail_url is not None
    assert jobs[0].thumbnail_url.startswith("/api/images/")


def test_get_job_detail_and_save_annotations(db_session: Session) -> None:
    task = tasks_api.create_task(TaskCreate(project_id=1, name="Annotate CT"), db_session)
    upload_response = tasks_api.upload_task_data(
        task.id,
        files=[make_upload("slice.png", (100, 80))],
        db=db_session,
    )
    image_id = upload_response.images[0].id
    job_id = upload_response.job_id

    detail = jobs_api.get_job(job_id, db_session)

    assert detail.images[0].id == image_id
    assert detail.images[0].image_url == f"/api/images/{image_id}/file"
    assert detail.labels[0].name == "Nodule"

    annotations = jobs_api.save_image_annotations(
        job_id,
        image_id,
        AnnotationSaveRequest.model_validate(
            {
                "annotations": [
                    {
                        "label_id": detail.labels[0].id,
                        "shape_type": "rectangle",
                        "points": [[10, 12], [50, 44]],
                    },
                    {
                        "label_id": detail.labels[1].id,
                        "shape_type": "polygon",
                        "points": [[20, 20], [40, 22], [35, 50]],
                    },
                ]
            }
        ),
        db_session,
    )

    assert len(annotations) == 2
    assert annotations[0].points == [[10.0, 12.0], [50.0, 44.0]]


def test_export_task_as_labelme_zip(db_session: Session) -> None:
    task = tasks_api.create_task(TaskCreate(project_id=1, name="Export CT"), db_session)
    upload_response = tasks_api.upload_task_data(
        task.id,
        files=[make_upload("slice.png", (100, 80))],
        db=db_session,
    )
    image_id = upload_response.images[0].id
    job_id = upload_response.job_id
    detail = jobs_api.get_job(job_id, db_session)

    annotations = jobs_api.save_image_annotations(
        job_id,
        image_id,
        AnnotationSaveRequest.model_validate(
            {
                "annotations": [
                    {
                        "label_id": detail.labels[0].id,
                        "shape_type": "rectangle",
                        "points": [[10, 12], [50, 44]],
                    },
                    {
                        "label_id": detail.labels[1].id,
                        "shape_type": "polygon",
                        "points": [[20, 20], [40, 22], [35, 50]],
                    },
                    {
                        "label_id": detail.labels[0].id,
                        "shape_type": "point",
                        "points": [[70, 30]],
                    },
                ]
            }
        ),
        db_session,
    )
    assert len(annotations) == 3

    export_response = tasks_api.export_task(task.id, export_format="labelme", db=db_session)

    assert export_response.media_type == "application/zip"

    export_content = build_labelme_zip(task, db_session).getvalue()
    with ZipFile(BytesIO(export_content)) as archive:
        assert archive.namelist() == ["slice.json"]
        labelme = json.loads(archive.read("slice.json"))

    assert labelme["imagePath"] == "slice.png"
    assert labelme["imageHeight"] == 80
    assert labelme["imageWidth"] == 100
    assert [shape["shape_type"] for shape in labelme["shapes"]] == ["polygon", "polygon", "point"]
    assert labelme["shapes"][0]["label"] == "Nodule"
    assert labelme["shapes"][0]["points"] == [[10, 12], [50, 12], [50, 44], [10, 44]]


def test_image_file_and_thumbnail_are_inline_images(db_session: Session) -> None:
    task = tasks_api.create_task(TaskCreate(project_id=1, name="Image headers"), db_session)
    upload_response = tasks_api.upload_task_data(
        task.id,
        files=[make_upload("slice.png", (16, 12))],
        db=db_session,
    )
    image_id = upload_response.images[0].id

    file_response = images_api.get_image_file(image_id, db_session)
    thumbnail_response = images_api.get_image_thumbnail(image_id, db_session)
    file_head_response = images_api.head_image_file(image_id, db_session)
    thumbnail_head_response = images_api.head_image_thumbnail(image_id, db_session)

    assert file_response.headers["content-type"] == "image/png"
    assert file_response.headers["content-disposition"] == "inline"
    assert thumbnail_response.headers["content-type"] == "image/png"
    assert thumbnail_response.headers["content-disposition"] == "inline"
    assert file_head_response.headers["content-type"] == "image/png"
    assert file_head_response.headers["content-disposition"] == "inline"
    assert thumbnail_head_response.headers["content-type"] == "image/png"
    assert thumbnail_head_response.headers["content-disposition"] == "inline"


def test_dataset_upload_creates_project_task_images_labels_and_job(db_session: Session) -> None:
    body = datasets_api.create_dataset(
        project_name="Dataset Upload",
        task_name="First Batch",
        labels="tumor, vessel, tumor",
        files=[
            make_upload("a.png", (20, 10)),
            make_upload("b.png", (30, 15)),
        ],
        db=db_session,
    )

    assert body.project_id == 2
    assert body.task_id == 1
    assert body.job_id == 1
    assert body.labels == ["tumor", "vessel"]
    assert len(body.images) == 2

    jobs = jobs_api.list_jobs(db_session)
    assert jobs[0].frames == 2


def test_project_and_job_creation_flow(db_session: Session) -> None:
    project = projects_api.create_project(ProjectCreate(name="Pig Eye OCT"), db_session)
    assert project.name == "Pig Eye OCT"

    projects = projects_api.list_projects(db_session)
    assert any(item.name == "Pig Eye OCT" for item in projects)

    body = jobs_api.create_job(
        project_id=project.id,
        job_name="case001",
        labels_json=json.dumps(
            [
                {"name": "layer_down", "shape_type": "polygon", "color": "#f97316"},
                {"name": "layer_up", "shape_type": "polygon", "color": "#0ea5e9"},
                {"name": "needle", "shape_type": "polygon", "color": "#22c55e"},
            ]
        ),
        files=[
            make_upload("1.png", (20, 10)),
            make_upload("2.png", (30, 15)),
        ],
        db=db_session,
    )

    assert body.name == "case001"
    assert body.project_id == project.id
    assert [label.name for label in body.labels] == ["layer_down", "layer_up", "needle"]
    assert body.labels[0].shape_type == "polygon"
    assert len(body.images) == 2

    jobs = jobs_api.list_jobs(db_session)
    created_job = next(job for job in jobs if job.id == body.id)
    assert created_job.name == "case001"
    assert created_job.project_name == "Pig Eye OCT"
    assert created_job.frames == 2
