from contextlib import nullcontext
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image as PILImage
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import datasets as datasets_api
from app.api.v1 import images as images_api
from app.api.v1 import jobs as jobs_api
from app.api.v1 import projects as projects_api
from app.api.v1 import sam2 as sam2_api
from app.api.v1 import tasks as tasks_api
from app.core.config import settings
from app.db.base import Base
from app.models import Image, Job, Label, Project, User
from app.schemas.annotation import AnnotationSaveRequest
from app.schemas.job import JobRead
from app.schemas.project import ProjectCreate
from app.schemas.sam2 import Sam2RefinePolygonRequest, Sam2TrackVideoRequest
from app.schemas.task import TaskCreate
from app.services.download_filenames import (
    build_attachment_content_disposition,
    build_job_export_filename,
    sanitize_filename,
)
from app.services.export_visual import (
    build_job_color_mask_zip,
    build_job_indexed_mask_zip,
    build_job_overlay_zip,
)
from app.services.labelme_export import build_job_labelme_zip, build_labelme_zip
from app.services.sam2_service import Sam2PredictionError, Sam2PredictionResult, Sam2Service
from app.services.sam2_video_service import (
    Sam2TrackVideoFrameResult,
    Sam2TrackVideoResult,
    Sam2VideoFrame,
    Sam2VideoService,
)


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


def build_stubbed_sam2_service(masks, scores) -> tuple[Sam2Service, object]:
    class FakePredictor:
        def __init__(self) -> None:
            self.model = type(
                "FakeModel",
                (),
                {
                    "use_mask_input_as_output_without_sam": True,
                    "sam_prompt_encoder": type("FakePromptEncoder", (), {"mask_input_size": (16, 16)})(),
                },
            )()
            self.image_shape = None
            self.mask_input = None
            self.force_flag_inside_call = None

        def set_image(self, image_array) -> None:
            self.image_shape = image_array.shape

        def predict(
            self,
            *,
            point_coords=None,
            point_labels=None,
            box=None,
            mask_input=None,
            multimask_output=True,
            return_logits=True,
        ):
            self.mask_input = mask_input
            self.force_flag_inside_call = self.model.use_mask_input_as_output_without_sam
            return masks, scores, masks

    class FakeTorch:
        @staticmethod
        def inference_mode():
            return nullcontext()

    predictor = FakePredictor()
    service = Sam2Service()
    service._predictor = predictor
    service._torch = FakeTorch()
    service._device = "cpu"
    service._dtype = "float32"
    service._active_model_name = "sam2_hiera_large"
    service.load_error = None
    service.load = lambda model_name=None: None  # type: ignore[assignment]
    return service, predictor


def build_stubbed_sam2_video_service(frame_masks) -> tuple[Sam2VideoService, object]:
    normalized_runs = frame_masks
    if not frame_masks or not isinstance(frame_masks[0], list):
        normalized_runs = [frame_masks]

    class FakePredictor:
        def __init__(self) -> None:
            self.init_state_path = None
            self.offload_video_to_cpu = None
            self.added_mask = None
            self.frame_files = []
            self.propagate_calls = 0

        def init_state(self, video_path, offload_video_to_cpu=False):
            self.init_state_path = video_path
            self.offload_video_to_cpu = offload_video_to_cpu
            self.frame_files = sorted(Path(video_path).glob("*.jpg"))
            return {"video_path": video_path}

        def add_new_mask(self, *, inference_state, frame_idx, obj_id, mask):
            self.added_mask = mask.detach().cpu().numpy() if hasattr(mask, "detach") else mask
            return frame_idx, [obj_id], None

        def propagate_in_video(self, inference_state, start_frame_idx=None, max_frame_num_to_track=None, reverse=False):
            run_index = min(self.propagate_calls, len(normalized_runs) - 1)
            self.propagate_calls += 1
            for frame_idx, mask in normalized_runs[run_index]:
                yield frame_idx, [1], mask

    class FakeTorch:
        @staticmethod
        def inference_mode():
            return nullcontext()

    predictor = FakePredictor()
    service = Sam2VideoService()
    service._predictor = predictor
    service._torch = FakeTorch()
    service._device = "cpu"
    service._dtype = "float32"
    service._active_model_name = "sam2_hiera_large"
    service.load_error = None
    service.load = lambda model_name=None: None  # type: ignore[assignment]
    return service, predictor


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
            annotated_images_count=0,
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
                        "attributes": {
                            "raw_points": [[20, 20], [38, 21], [41, 24], [35, 50]],
                            "smooth_value": 28,
                        },
                    },
                ]
            }
        ),
        db_session,
    )

    assert len(annotations) == 2
    assert annotations[0].points == [[10.0, 12.0], [50.0, 44.0]]
    assert annotations[0].attributes is None
    assert annotations[1].attributes == {
        "raw_points": [[20.0, 20.0], [38.0, 21.0], [41.0, 24.0], [35.0, 50.0]],
        "smooth_value": 28,
    }
    assert annotations[1].points != annotations[1].attributes["raw_points"]

    refreshed_detail = jobs_api.get_job(job_id, db_session)
    assert refreshed_detail.annotations[1].attributes == {
        "raw_points": [[20.0, 20.0], [38.0, 21.0], [41.0, 24.0], [35.0, 50.0]],
        "smooth_value": 28,
    }


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


def test_sanitize_filename_rules() -> None:
    assert sanitize_filename("20260428_13_22_28q_test", fallback="job_1") == "20260428_13_22_28q_test"
    assert sanitize_filename("张玉柱 OCT job", fallback="job_1") == "张玉柱_OCT_job"
    assert sanitize_filename("case:001/test", fallback="job_1") == "case_001_test"
    assert sanitize_filename("   ", fallback="job_1") == "job_1"
    content_disposition = build_attachment_content_disposition("张玉柱_labelme.zip", "export_labelme.zip")
    assert content_disposition.startswith('attachment; filename="')
    assert "filename*=UTF-8''%E5%BC%A0%E7%8E%89%E6%9F%B1_labelme.zip" in content_disposition


def test_build_job_export_filename_uses_job_name_for_all_export_types(db_session: Session) -> None:
    task = tasks_api.create_task(TaskCreate(project_id=1, name="20260428_13_28_25q"), db_session)
    upload_response = tasks_api.upload_task_data(
        task.id,
        files=[make_upload("slice.png", (100, 80))],
        db=db_session,
    )
    job = db_session.get(Job, upload_response.job_id)
    assert job is not None

    assert build_job_export_filename(job, "labelme") == "20260428_13_28_25q_labelme.zip"
    assert build_job_export_filename(job, "overlay") == "20260428_13_28_25q_overlay.zip"
    assert build_job_export_filename(job, "mask_indexed") == "20260428_13_28_25q_mask_indexed.zip"
    assert build_job_export_filename(job, "mask_color") == "20260428_13_28_25q_mask_color.zip"
    assert build_job_export_filename(job, "labelme", export_scope="annotated_only") == (
        "20260428_13_28_25q_labelme_annotated_only.zip"
    )


def test_export_job_labelme_content_disposition_uses_job_name(db_session: Session) -> None:
    task = tasks_api.create_task(TaskCreate(project_id=1, name="张玉柱 OCT job"), db_session)
    upload_response = tasks_api.upload_task_data(
        task.id,
        files=[make_upload("slice.png", (100, 80))],
        db=db_session,
    )

    export_response = jobs_api.export_job_labelme(upload_response.job_id, db=db_session)
    content_disposition = export_response.headers["Content-Disposition"]
    expected_filename = "张玉柱_OCT_job_labelme.zip"

    assert content_disposition == build_attachment_content_disposition(expected_filename, "export_labelme.zip")
    assert 'filename="OCT_job_labelme.zip"' in content_disposition
    assert f"filename*=UTF-8''{quote(expected_filename, safe='')}" in content_disposition


def test_job_exports_support_annotated_only_scope(db_session: Session) -> None:
    task = tasks_api.create_task(TaskCreate(project_id=1, name="Scoped Export"), db_session)
    upload_response = tasks_api.upload_task_data(
        task.id,
        files=[
            make_upload("0.png", (100, 80)),
            make_upload("1.png", (100, 80)),
            make_upload("2.png", (100, 80)),
            make_upload("3.png", (100, 80)),
            make_upload("4.png", (100, 80)),
        ],
        db=db_session,
    )
    detail = jobs_api.get_job(upload_response.job_id, db_session)
    labels = detail.labels
    annotated_image_ids = {detail.images[0].id, detail.images[3].id}

    for image in detail.images:
        annotations_payload = []
        if image.id in annotated_image_ids:
            annotations_payload = [
                {
                    "label_id": labels[0].id,
                    "shape_type": "polygon",
                    "points": [[10, 10], [40, 12], [38, 50], [12, 45]],
                }
            ]
        jobs_api.save_image_annotations(
            upload_response.job_id,
            image.id,
            AnnotationSaveRequest.model_validate({"annotations": annotations_payload}),
            db_session,
        )

    job = db_session.get(Job, upload_response.job_id)
    assert job is not None

    with ZipFile(build_job_labelme_zip(job, db_session)) as archive:
        assert len([name for name in archive.namelist() if name.endswith(".json")]) == 5
    with ZipFile(build_job_labelme_zip(job, db_session, export_scope="annotated_only")) as archive:
        assert len([name for name in archive.namelist() if name.endswith(".json")]) == 2

    with ZipFile(build_job_overlay_zip(job, db_session)) as archive:
        assert len([name for name in archive.namelist() if name.endswith(".png")]) == 5
    with ZipFile(build_job_overlay_zip(job, db_session, export_scope="annotated_only")) as archive:
        assert len([name for name in archive.namelist() if name.endswith(".png")]) == 2

    with ZipFile(build_job_indexed_mask_zip(job, db_session)) as archive:
        assert len([name for name in archive.namelist() if name.endswith(".png")]) == 5
    with ZipFile(build_job_indexed_mask_zip(job, db_session, export_scope="annotated_only")) as archive:
        assert len([name for name in archive.namelist() if name.endswith(".png")]) == 2

    with ZipFile(build_job_color_mask_zip(job, db_session)) as archive:
        assert len([name for name in archive.namelist() if name.endswith(".png")]) == 5
    with ZipFile(build_job_color_mask_zip(job, db_session, export_scope="annotated_only")) as archive:
        assert len([name for name in archive.namelist() if name.endswith(".png")]) == 2

    export_response = jobs_api.export_job_labelme(upload_response.job_id, "annotated_only", db_session)
    assert export_response.headers["Content-Disposition"] == build_attachment_content_disposition(
        "Scoped_Export_labelme_annotated_only.zip",
        "export_labelme.zip",
    )


def test_annotated_only_export_without_annotations_returns_error(db_session: Session) -> None:
    task = tasks_api.create_task(TaskCreate(project_id=1, name="No Annotations"), db_session)
    upload_response = tasks_api.upload_task_data(
        task.id,
        files=[make_upload("slice.png", (100, 80))],
        db=db_session,
    )

    with pytest.raises(HTTPException) as exc_info:
        jobs_api.export_job_labelme(upload_response.job_id, "annotated_only", db_session)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "No annotated images found in this job."


def test_refine_polygon_endpoint_returns_polygon(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    task = tasks_api.create_task(TaskCreate(project_id=1, name="Refine Polygon"), db_session)
    upload_response = tasks_api.upload_task_data(
        task.id,
        files=[make_upload("slice.png", (64, 48))],
        db=db_session,
    )

    class FakeSam2Service:
        def refine_polygon(self, **kwargs):
            assert kwargs["polygon_points"] == [[5, 5], [30, 6], [28, 30], [6, 28]]
            return Sam2PredictionResult(
                points=[[6.0, 6.0], [31.0, 7.0], [29.0, 31.0], [7.0, 29.0]],
                score=0.95,
                model_name="sam2_hiera_large",
                candidate="best",
                polygon_epsilon=0.002,
                mask_threshold=0.0,
                max_hole_area=0.0,
                num_contours=1,
                mask_area=432.0,
            )

    monkeypatch.setattr(sam2_api, "get_sam2_service", lambda: FakeSam2Service())

    response = sam2_api.refine_sam2_polygon(
        Sam2RefinePolygonRequest(
            image_id=upload_response.images[0].id,
            annotation_id=456,
            points=[[5, 5], [30, 6], [28, 30], [6, 28]],
        ),
        db_session,
    )

    assert response.annotation_id == 456
    assert response.source == "refine_polygon"
    assert response.points == [[6.0, 6.0], [31.0, 7.0], [29.0, 31.0], [7.0, 29.0]]
    assert response.area == 432.0


def test_track_video_endpoint_orders_frames_and_returns_results(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = tasks_api.create_task(TaskCreate(project_id=1, name="Track Polygon"), db_session)
    upload_response = tasks_api.upload_task_data(
        task.id,
        files=[
            make_upload("2.png", (64, 48)),
            make_upload("0.png", (64, 48)),
            make_upload("1.png", (64, 48)),
        ],
        db=db_session,
    )
    images = db_session.query(Image).filter(Image.id.in_([image.id for image in upload_response.images])).all()
    image_by_filename = {image.filename: image for image in images}
    image_by_filename["2.png"].frame_index = 5
    image_by_filename["0.png"].frame_index = 1
    image_by_filename["1.png"].frame_index = 3
    db_session.commit()
    detail = jobs_api.get_job(upload_response.job_id, db_session)

    class FakeSam2VideoService:
        def track_video(self, **kwargs):
            frames = kwargs["frames"]
            assert [frame.filename for frame in frames] == ["0.png", "1.png", "2.png"]
            assert [frame.frame_index for frame in frames] == [1, 3, 5]
            return Sam2TrackVideoResult(
                start_frame_index=1,
                end_frame_index=5,
                backward_end_frame_index=None,
                forward_end_frame_index=5,
                direction="forward",
                model_name="sam2_hiera_large",
                results=[
                    Sam2TrackVideoFrameResult(
                        image_id=frames[0].image_id,
                        frame_index=1,
                        filename="0.png",
                        points=[[5.0, 5.0], [20.0, 5.0], [20.0, 20.0], [5.0, 20.0]],
                        score=None,
                        area=225.0,
                        status="source",
                        propagation_direction="source",
                    ),
                    Sam2TrackVideoFrameResult(
                        image_id=frames[1].image_id,
                        frame_index=3,
                        filename="1.png",
                        points=[[6.0, 6.0], [21.0, 6.0], [21.0, 21.0], [6.0, 21.0]],
                        score=None,
                        area=225.0,
                        status="tracked",
                        propagation_direction="forward",
                    ),
                ],
                review_frames=[3, 5],
                warnings=[],
            )

    monkeypatch.setattr(sam2_api, "get_sam2_video_service", lambda: FakeSam2VideoService())

    response = sam2_api.track_sam2_video(
        Sam2TrackVideoRequest(
            job_id=upload_response.job_id,
            start_image_id=image_by_filename["0.png"].id,
            start_frame_index=1,
            annotation_id=123,
            label_id=detail.labels[0].id,
            points=[[5, 5], [20, 5], [20, 20], [5, 20]],
            direction="forward",
            end_frame_index=21,
            review_interval=10,
        ),
        db_session,
    )

    assert response.job_id == upload_response.job_id
    assert response.source_annotation_id == 123
    assert response.start_frame_index == 1
    assert response.end_frame_index == 5
    assert response.direction == "forward"
    assert response.review_frames == [3, 5]
    assert response.results[1].status == "tracked"
    assert response.results[1].points == [[6.0, 6.0], [21.0, 6.0], [21.0, 21.0], [6.0, 21.0]]


@pytest.mark.parametrize(
    ("candidate", "expected_score"),
    [
        ("best", 0.9),
        ("0", 0.1),
        ("1", 0.9),
        ("2", 0.2),
    ],
)
def test_sam2_service_refine_polygon_selects_requested_candidate(
    tmp_path: Path,
    candidate: str,
    expected_score: float,
) -> None:
    import numpy as np

    image_path = tmp_path / "slice.png"
    PILImage.new("RGB", (32, 24), color=(0, 0, 0)).save(image_path)

    masks = np.zeros((3, 24, 32), dtype=np.float32)
    masks[0, 4:18, 5:20] = 3.0
    masks[1, 5:20, 7:24] = 5.0
    masks[2, 3:16, 10:28] = 4.0
    scores = np.array([0.1, 0.9, 0.2], dtype=np.float32)

    service, predictor = build_stubbed_sam2_service(masks, scores)
    result = service.refine_polygon(
        image_path=str(image_path),
        model_name="sam2_hiera_large",
        polygon_points=[[4, 4], [24, 5], [26, 20], [6, 21]],
        multimask_output=True,
        candidate=candidate,
        polygon_epsilon=0.002,
        min_mask_area=10,
        mask_threshold=0.0,
        max_hole_area=0.0,
    )

    assert predictor.image_shape == (24, 32, 3)
    assert predictor.mask_input.shape == (1, 16, 16)
    assert predictor.mask_input.dtype == np.float32
    assert predictor.force_flag_inside_call is False
    assert predictor.model.use_mask_input_as_output_without_sam is True
    assert result.score == pytest.approx(expected_score)
    assert len(result.points) >= 3


def test_sam2_video_service_tracks_forward_frames_and_builds_review_frames(tmp_path: Path) -> None:
    import numpy as np
    import torch

    frame0 = tmp_path / "frame0.png"
    frame1 = tmp_path / "frame1.jpg"
    frame2 = tmp_path / "frame2.png"
    PILImage.new("RGB", (32, 24), color=(0, 0, 0)).save(frame0)
    PILImage.new("RGB", (32, 24), color=(0, 0, 0)).save(frame1)
    PILImage.new("RGB", (32, 24), color=(0, 0, 0)).save(frame2)

    mask1 = torch.zeros((1, 1, 24, 32), dtype=torch.float32)
    mask1[0, 0, 5:18, 6:22] = 2.0
    mask2 = torch.zeros((1, 1, 24, 32), dtype=torch.float32)
    mask2[0, 0, 6:20, 7:24] = 3.0

    service, predictor = build_stubbed_sam2_video_service(
        [
            (0, torch.zeros((1, 1, 24, 32), dtype=torch.float32)),
            (1, mask1),
            (2, mask2),
        ]
    )
    result = service.track_video(
        frames=[
            Sam2VideoFrame(image_id=1, frame_index=0, filename="frame0.png", file_path=str(frame0), width=32, height=24),
            Sam2VideoFrame(image_id=2, frame_index=1, filename="frame1.jpg", file_path=str(frame1), width=32, height=24),
            Sam2VideoFrame(image_id=3, frame_index=2, filename="frame2.png", file_path=str(frame2), width=32, height=24),
        ],
        start_image_id=1,
        start_frame_index=0,
        polygon_points=[[4, 4], [20, 4], [20, 18], [4, 18]],
        direction="forward",
        end_frame_index=2,
        backward_end_frame_index=None,
        forward_end_frame_index=None,
        review_interval=1,
        model_name="sam2_hiera_large",
        polygon_epsilon=0.002,
        min_mask_area=10,
        mask_threshold=0.0,
        max_hole_area=0.0,
    )

    assert predictor.added_mask.shape == (24, 32)
    assert predictor.added_mask.dtype == np.bool_
    assert [path.name for path in predictor.frame_files] == ["000000.jpg", "000001.jpg", "000002.jpg"]
    assert result.start_frame_index == 0
    assert result.end_frame_index == 2
    assert result.review_frames == [1, 2]
    assert [frame.status for frame in result.results] == ["source", "tracked", "tracked"]
    assert result.results[0].points == [[4.0, 4.0], [20.0, 4.0], [20.0, 18.0], [4.0, 18.0]]
    assert len(result.results[1].points or []) >= 3
    assert result.warnings == []


def test_sam2_video_service_tracks_backward_frames_using_reversed_sequence(tmp_path: Path) -> None:
    import torch

    frame0 = tmp_path / "frame0.png"
    frame1 = tmp_path / "frame1.jpg"
    frame2 = tmp_path / "frame2.png"
    PILImage.new("RGB", (32, 24), color=(0, 0, 0)).save(frame0)
    PILImage.new("RGB", (32, 24), color=(0, 0, 0)).save(frame1)
    PILImage.new("RGB", (32, 24), color=(0, 0, 0)).save(frame2)

    source_mask = torch.zeros((1, 1, 24, 32), dtype=torch.float32)
    mask_for_frame1 = torch.zeros((1, 1, 24, 32), dtype=torch.float32)
    mask_for_frame1[0, 0, 4:12, 4:14] = 2.0
    mask_for_frame0 = torch.zeros((1, 1, 24, 32), dtype=torch.float32)
    mask_for_frame0[0, 0, 6:20, 10:26] = 3.0

    service, predictor = build_stubbed_sam2_video_service(
        [
            (0, source_mask),
            (1, mask_for_frame1),
            (2, mask_for_frame0),
        ]
    )
    result = service.track_video(
        frames=[
            Sam2VideoFrame(image_id=1, frame_index=0, filename="frame0.png", file_path=str(frame0), width=32, height=24),
            Sam2VideoFrame(image_id=2, frame_index=1, filename="frame1.jpg", file_path=str(frame1), width=32, height=24),
            Sam2VideoFrame(image_id=3, frame_index=2, filename="frame2.png", file_path=str(frame2), width=32, height=24),
        ],
        start_image_id=3,
        start_frame_index=2,
        polygon_points=[[4, 4], [20, 4], [20, 18], [4, 18]],
        direction="backward",
        end_frame_index=0,
        backward_end_frame_index=None,
        forward_end_frame_index=None,
        review_interval=1,
        model_name="sam2_hiera_large",
        polygon_epsilon=0.002,
        min_mask_area=10,
        mask_threshold=0.0,
        max_hole_area=0.0,
    )

    assert predictor.added_mask.shape == (24, 32)
    assert result.start_frame_index == 2
    assert result.end_frame_index == 0
    assert result.backward_end_frame_index == 0
    assert result.forward_end_frame_index is None
    assert result.review_frames == [0, 1]
    assert [frame.frame_index for frame in result.results] == [0, 1, 2]
    assert [frame.propagation_direction for frame in result.results] == ["backward", "backward", "source"]
    assert [frame.status for frame in result.results] == ["tracked", "tracked", "source"]
    assert result.results[0].area == pytest.approx(float((mask_for_frame0[0, 0] > 0).sum().item()))
    assert result.results[1].area == pytest.approx(float((mask_for_frame1[0, 0] > 0).sum().item()))


def test_sam2_video_service_tracks_both_directions_and_deduplicates_source(tmp_path: Path) -> None:
    import torch

    frame_paths = []
    for index in range(5):
        frame_path = tmp_path / f"frame{index}.png"
        PILImage.new("RGB", (32, 24), color=(0, 0, 0)).save(frame_path)
        frame_paths.append(frame_path)

    empty = torch.zeros((1, 1, 24, 32), dtype=torch.float32)
    backward_mask_1 = torch.zeros((1, 1, 24, 32), dtype=torch.float32)
    backward_mask_1[0, 0, 4:12, 4:14] = 2.0
    backward_mask_0 = torch.zeros((1, 1, 24, 32), dtype=torch.float32)
    backward_mask_0[0, 0, 6:18, 8:24] = 2.5
    forward_mask_3 = torch.zeros((1, 1, 24, 32), dtype=torch.float32)
    forward_mask_3[0, 0, 5:14, 5:18] = 2.0
    forward_mask_4 = torch.zeros((1, 1, 24, 32), dtype=torch.float32)
    forward_mask_4[0, 0, 7:21, 12:26] = 2.5

    service, predictor = build_stubbed_sam2_video_service(
        [
            [
                (0, empty),
                (1, backward_mask_1),
                (2, backward_mask_0),
            ],
            [
                (0, empty),
                (1, forward_mask_3),
                (2, forward_mask_4),
            ],
        ]
    )
    result = service.track_video(
        frames=[
            Sam2VideoFrame(image_id=index + 1, frame_index=index, filename=f"frame{index}.png", file_path=str(frame_paths[index]), width=32, height=24)
            for index in range(5)
        ],
        start_image_id=3,
        start_frame_index=2,
        polygon_points=[[4, 4], [20, 4], [20, 18], [4, 18]],
        direction="both",
        end_frame_index=None,
        backward_end_frame_index=0,
        forward_end_frame_index=4,
        review_interval=1,
        model_name="sam2_hiera_large",
        polygon_epsilon=0.002,
        min_mask_area=10,
        mask_threshold=0.0,
        max_hole_area=0.0,
    )

    assert predictor.propagate_calls == 2
    assert result.start_frame_index == 2
    assert result.end_frame_index == 4
    assert result.backward_end_frame_index == 0
    assert result.forward_end_frame_index == 4
    assert result.review_frames == [0, 1, 3, 4]
    assert [frame.frame_index for frame in result.results] == [0, 1, 2, 3, 4]
    assert [frame.propagation_direction for frame in result.results] == ["backward", "backward", "source", "forward", "forward"]
    assert sum(1 for frame in result.results if frame.status == "source") == 1
    assert result.warnings == []


def test_sam2_track_video_request_validates_directional_ranges() -> None:
    with pytest.raises(ValidationError, match="Forward tracking end_frame_index must be greater than or equal to start_frame_index"):
        Sam2TrackVideoRequest(
            job_id=1,
            start_image_id=1,
            start_frame_index=10,
            label_id=1,
            points=[[1, 1], [2, 1], [2, 2]],
            direction="forward",
            end_frame_index=9,
        )

    with pytest.raises(ValidationError, match="Backward tracking end_frame_index must be less than or equal to start_frame_index"):
        Sam2TrackVideoRequest(
            job_id=1,
            start_image_id=1,
            start_frame_index=10,
            label_id=1,
            points=[[1, 1], [2, 1], [2, 2]],
            direction="backward",
            end_frame_index=11,
        )

    with pytest.raises(ValidationError, match="Bidirectional backward_end_frame_index must be less than or equal to start_frame_index"):
        Sam2TrackVideoRequest(
            job_id=1,
            start_image_id=1,
            start_frame_index=10,
            label_id=1,
            points=[[1, 1], [2, 1], [2, 2]],
            direction="both",
            backward_end_frame_index=11,
            forward_end_frame_index=12,
        )


def test_sam2_video_service_rejects_inconsistent_frame_sizes(tmp_path: Path) -> None:
    import torch

    frame0 = tmp_path / "frame0.jpg"
    frame1 = tmp_path / "frame1.jpg"
    PILImage.new("RGB", (32, 24), color=(0, 0, 0)).save(frame0)
    PILImage.new("RGB", (64, 24), color=(0, 0, 0)).save(frame1)

    service, _predictor = build_stubbed_sam2_video_service(
        [(0, torch.zeros((1, 1, 24, 32), dtype=torch.float32))]
    )

    with pytest.raises(Sam2PredictionError, match="All frames in the tracking range must have the same image size."):
        service.track_video(
            frames=[
                Sam2VideoFrame(image_id=1, frame_index=0, filename="frame0.jpg", file_path=str(frame0), width=32, height=24),
                Sam2VideoFrame(image_id=2, frame_index=1, filename="frame1.jpg", file_path=str(frame1), width=64, height=24),
            ],
            start_image_id=1,
            start_frame_index=0,
            polygon_points=[[4, 4], [20, 4], [20, 18], [4, 18]],
            direction="forward",
            end_frame_index=1,
            backward_end_frame_index=None,
            forward_end_frame_index=None,
            review_interval=10,
            model_name="sam2_hiera_large",
            polygon_epsilon=0.002,
            min_mask_area=10,
            mask_threshold=0.0,
            max_hole_area=0.0,
        )


def test_sam2_service_refine_polygon_falls_back_to_best_candidate(tmp_path: Path) -> None:
    import numpy as np

    image_path = tmp_path / "slice.png"
    PILImage.new("RGB", (32, 24), color=(0, 0, 0)).save(image_path)

    masks = np.zeros((1, 24, 32), dtype=np.float32)
    masks[0, 5:18, 6:22] = 6.0
    scores = np.array([0.8], dtype=np.float32)

    service, _predictor = build_stubbed_sam2_service(masks, scores)
    result = service.refine_polygon(
        image_path=str(image_path),
        model_name="sam2_hiera_large",
        polygon_points=[[5, 5], [21, 5], [22, 18], [6, 18]],
        multimask_output=False,
        candidate="2",
        polygon_epsilon=0.002,
        min_mask_area=10,
        mask_threshold=0.0,
        max_hole_area=0.0,
    )

    assert result.score == pytest.approx(0.8)
    assert len(result.points) >= 3


def test_sam2_service_refine_polygon_rejects_empty_mask(tmp_path: Path) -> None:
    import numpy as np

    image_path = tmp_path / "slice.png"
    PILImage.new("RGB", (32, 24), color=(0, 0, 0)).save(image_path)

    masks = np.zeros((1, 24, 32), dtype=np.float32)
    scores = np.array([0.8], dtype=np.float32)

    service, _predictor = build_stubbed_sam2_service(masks, scores)

    with pytest.raises(Sam2PredictionError, match="SAM2 returned an empty mask"):
        service.refine_polygon(
            image_path=str(image_path),
            model_name="sam2_hiera_large",
            polygon_points=[[5, 5], [21, 5], [22, 18], [6, 18]],
            multimask_output=False,
            candidate="best",
            polygon_epsilon=0.002,
            min_mask_area=10,
            mask_threshold=0.0,
            max_hole_area=0.0,
        )


def test_sam2_service_refine_polygon_rejects_degenerate_polygon(tmp_path: Path) -> None:
    import numpy as np

    image_path = tmp_path / "slice.png"
    PILImage.new("RGB", (32, 24), color=(0, 0, 0)).save(image_path)

    masks = np.zeros((1, 24, 32), dtype=np.float32)
    scores = np.array([0.8], dtype=np.float32)

    service, _predictor = build_stubbed_sam2_service(masks, scores)

    with pytest.raises(Sam2PredictionError, match="Polygon must enclose a non-zero area."):
        service.refine_polygon(
            image_path=str(image_path),
            model_name="sam2_hiera_large",
            polygon_points=[[5, 5], [10, 10], [15, 15]],
            multimask_output=False,
            candidate="best",
            polygon_epsilon=0.002,
            min_mask_area=10,
            mask_threshold=0.0,
            max_hole_area=0.0,
        )


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
