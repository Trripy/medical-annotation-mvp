from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Label, Project, User


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)

    settings.local_storage_root = str(tmp_path)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestingSessionLocal() as db:
        owner = User(email="owner@example.com")
        project = Project(name="Upload Project", owner=owner)
        project.labels = [
            Label(name="Nodule", color="#22c55e"),
            Label(name="Organ", color="#0ea5e9"),
        ]
        db.add(project)
        db.commit()

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def make_png(size: tuple[int, int] = (32, 24)) -> BytesIO:
    buffer = BytesIO()
    PILImage.new("RGB", size, color=(12, 82, 91)).save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def test_create_task(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tasks",
        json={"project_id": 1, "name": "Upload CT", "description": "Initial upload"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 1
    assert body["project_id"] == 1
    assert body["name"] == "Upload CT"


def test_upload_images_creates_images_thumbnails_and_job(client: TestClient, tmp_path: Path) -> None:
    task_response = client.post("/api/v1/tasks", json={"project_id": 1, "name": "Upload CT"})
    task_id = task_response.json()["id"]

    response = client.post(
        f"/api/v1/tasks/{task_id}/data",
        files=[
            ("files", ("slice-1.png", make_png((64, 48)), "image/png")),
            ("files", ("slice-2.png", make_png((40, 30)), "image/png")),
        ],
    )

    assert response.status_code == 201
    body = response.json()
    assert body["task_id"] == task_id
    assert body["job_id"] == 1
    assert len(body["images"]) == 2

    first_image = body["images"][0]
    assert first_image["filename"] == "slice-1.png"
    assert first_image["width"] == 64
    assert first_image["height"] == 48
    assert Path(first_image["file_path"]).is_file()
    assert Path(first_image["thumbnail_path"]).is_file()
    assert Path(first_image["file_path"]).parent == tmp_path / "data" / "images"
    assert Path(first_image["thumbnail_path"]).parent == tmp_path / "data" / "thumbnails"

    jobs_response = client.get("/api/jobs")

    assert jobs_response.status_code == 200
    jobs = jobs_response.json()
    assert jobs == [
        {
            "id": 1,
            "project_id": 1,
            "project_name": "Upload Project",
            "name": "Upload CT",
            "status": "pending",
            "task_id": task_id,
            "frames": 2,
            "thumbnail_url": jobs[0]["thumbnail_url"],
        }
    ]
    assert jobs[0]["thumbnail_url"].startswith("/api/images/")


def test_get_job_detail_and_save_annotations(client: TestClient) -> None:
    task_response = client.post("/api/tasks", json={"project_id": 1, "name": "Annotate CT"})
    task_id = task_response.json()["id"]
    upload_response = client.post(
        f"/api/tasks/{task_id}/data",
        files=[("files", ("slice.png", make_png((100, 80)), "image/png"))],
    )
    image_id = upload_response.json()["images"][0]["id"]
    job_id = upload_response.json()["job_id"]

    detail_response = client.get(f"/api/jobs/{job_id}")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["images"][0]["id"] == image_id
    assert detail["images"][0]["image_url"] == f"/api/images/{image_id}/file"
    assert detail["labels"][0]["name"] == "Nodule"

    save_response = client.put(
        f"/api/jobs/{job_id}/images/{image_id}/annotations",
        json={
            "annotations": [
                {
                    "label_id": detail["labels"][0]["id"],
                    "shape_type": "rectangle",
                    "points": [[10, 12], [50, 44]],
                },
                {
                    "label_id": detail["labels"][1]["id"],
                    "shape_type": "polygon",
                    "points": [[20, 20], [40, 22], [35, 50]],
                },
            ]
        },
    )

    assert save_response.status_code == 200
    annotations = save_response.json()
    assert len(annotations) == 2
    assert annotations[0]["points"] == [[10.0, 12.0], [50.0, 44.0]]


def test_export_task_as_labelme_zip(client: TestClient) -> None:
    task_response = client.post("/api/tasks", json={"project_id": 1, "name": "Export CT"})
    task_id = task_response.json()["id"]
    upload_response = client.post(
        f"/api/tasks/{task_id}/data",
        files=[("files", ("slice.png", make_png((100, 80)), "image/png"))],
    )
    image_id = upload_response.json()["images"][0]["id"]
    job_id = upload_response.json()["job_id"]
    detail = client.get(f"/api/jobs/{job_id}").json()

    save_response = client.put(
        f"/api/jobs/{job_id}/images/{image_id}/annotations",
        json={
            "annotations": [
                {
                    "label_id": detail["labels"][0]["id"],
                    "shape_type": "rectangle",
                    "points": [[10, 12], [50, 44]],
                },
                {
                    "label_id": detail["labels"][1]["id"],
                    "shape_type": "polygon",
                    "points": [[20, 20], [40, 22], [35, 50]],
                },
                {
                    "label_id": detail["labels"][0]["id"],
                    "shape_type": "point",
                    "points": [[70, 30]],
                },
            ]
        },
    )
    assert save_response.status_code == 200

    export_response = client.post(f"/api/tasks/{task_id}/export?format=labelme")

    assert export_response.status_code == 200
    assert export_response.headers["content-type"] == "application/zip"

    with ZipFile(BytesIO(export_response.content)) as archive:
        assert archive.namelist() == ["slice.json"]
        labelme = json.loads(archive.read("slice.json"))

    assert labelme["imagePath"] == "slice.png"
    assert labelme["imageHeight"] == 80
    assert labelme["imageWidth"] == 100
    assert [shape["shape_type"] for shape in labelme["shapes"]] == ["polygon", "polygon", "point"]
    assert labelme["shapes"][0]["label"] == "Nodule"
    assert labelme["shapes"][0]["points"] == [[10, 12], [50, 12], [50, 44], [10, 44]]


def test_image_file_and_thumbnail_are_inline_images(client: TestClient) -> None:
    task_response = client.post("/api/tasks", json={"project_id": 1, "name": "Image headers"})
    task_id = task_response.json()["id"]
    upload_response = client.post(
        f"/api/tasks/{task_id}/data",
        files=[("files", ("slice.png", make_png((16, 12)), "image/png"))],
    )
    image_id = upload_response.json()["images"][0]["id"]

    file_response = client.get(f"/api/images/{image_id}/file")
    thumbnail_response = client.get(f"/api/images/{image_id}/thumbnail")
    file_head_response = client.head(f"/api/images/{image_id}/file")
    thumbnail_head_response = client.head(f"/api/images/{image_id}/thumbnail")

    assert file_response.status_code == 200
    assert file_response.headers["content-type"] == "image/png"
    assert file_response.headers["content-disposition"] == "inline"
    assert thumbnail_response.status_code == 200
    assert thumbnail_response.headers["content-type"] == "image/png"
    assert thumbnail_response.headers["content-disposition"] == "inline"
    assert file_head_response.status_code == 200
    assert file_head_response.headers["content-type"] == "image/png"
    assert file_head_response.headers["content-disposition"] == "inline"
    assert thumbnail_head_response.status_code == 200
    assert thumbnail_head_response.headers["content-type"] == "image/png"
    assert thumbnail_head_response.headers["content-disposition"] == "inline"


def test_dataset_upload_creates_project_task_images_labels_and_job(client: TestClient) -> None:
    response = client.post(
        "/api/datasets",
        data={
            "project_name": "Dataset Upload",
            "task_name": "First Batch",
            "labels": "tumor, vessel, tumor",
        },
        files=[
            ("files", ("a.png", make_png((20, 10)), "image/png")),
            ("files", ("b.png", make_png((30, 15)), "image/png")),
        ],
    )

    assert response.status_code == 201
    body = response.json()
    assert body["project_id"] == 2
    assert body["task_id"] == 1
    assert body["job_id"] == 1
    assert body["labels"] == ["tumor", "vessel"]
    assert len(body["images"]) == 2

    jobs_response = client.get("/api/jobs")
    assert jobs_response.status_code == 200
    assert jobs_response.json()[0]["frames"] == 2


def test_project_and_job_creation_flow(client: TestClient) -> None:
    project_response = client.post("/api/projects", json={"name": "Pig Eye OCT"})
    assert project_response.status_code == 201
    project = project_response.json()
    assert project["name"] == "Pig Eye OCT"

    projects_response = client.get("/api/projects")
    assert projects_response.status_code == 200
    assert any(item["name"] == "Pig Eye OCT" for item in projects_response.json())

    response = client.post(
        "/api/jobs",
        data={
            "project_id": str(project["id"]),
            "job_name": "case001",
            "labels_json": json.dumps(
                [
                    {"name": "layer_down", "shape_type": "polygon", "color": "#f97316"},
                    {"name": "layer_up", "shape_type": "polygon", "color": "#0ea5e9"},
                    {"name": "needle", "shape_type": "polygon", "color": "#22c55e"},
                ]
            ),
        },
        files=[
            ("files", ("1.png", make_png((20, 10)), "image/png")),
            ("files", ("2.png", make_png((30, 15)), "image/png")),
        ],
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "case001"
    assert body["project_id"] == project["id"]
    assert [label["name"] for label in body["labels"]] == ["layer_down", "layer_up", "needle"]
    assert body["labels"][0]["shape_type"] == "polygon"
    assert len(body["images"]) == 2

    jobs_response = client.get("/api/jobs")
    assert jobs_response.status_code == 200
    created_job = next(job for job in jobs_response.json() if job["id"] == body["id"])
    assert created_job["name"] == "case001"
    assert created_job["project_name"] == "Pig Eye OCT"
    assert created_job["frames"] == 2
