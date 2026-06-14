import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.db.session import get_db
from app.models import Annotation, Image, Job, Label, Project, Task
from app.schemas.annotation import (
    AnnotationRead,
    AnnotationSaveRequest,
    JobDetailRead,
    JobImageRead,
    LabelRead,
)
from app.schemas.job import JobLabelCreate, JobRead
from app.services.image_storage import InvalidImageError, save_uploaded_image
from app.services.labelme_export import build_job_labelme_zip
from app.services.export_visual import (
    build_job_color_mask_zip,
    build_job_indexed_mask_zip,
    build_job_overlay_zip,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("", response_model=list[JobRead])
def list_jobs(db: Session = Depends(get_db)) -> list[JobRead]:
    jobs = db.scalars(
        select(Job)
        .options(
            selectinload(Job.project),
            selectinload(Job.task).selectinload(Task.images),
            selectinload(Job.images),
        )
        .order_by(Job.id.desc())
    ).all()

    result: list[JobRead] = []
    for job in jobs:
        images = _job_images(job)
        result.append(
            JobRead(
                id=job.id,
                project_id=job.project_id,
                project_name=job.project.name if job.project else None,
                name=job.name,
                status=job.status,
                task_id=job.task_id,
                frames=len(images),
                thumbnail_url=f"/api/images/{images[0].id}/thumbnail" if images else None,
            )
        )

    return result


@router.post("", response_model=JobDetailRead, status_code=status.HTTP_201_CREATED)
def create_job(
    project_id: int = Form(...),
    job_name: str = Form(...),
    labels_json: str = Form(...),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> JobDetailRead:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one image is required")

    labels = _parse_labels_json(labels_json)
    if not labels:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one label is required")

    normalized_job_name = job_name.strip()
    if not normalized_job_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Job name is required")

    task = Task(project=project, name=normalized_job_name, status="pending")
    job = Job(project=project, task=task, name=normalized_job_name, status="annotation")
    job.labels = [
        Label(
            job=job,
            name=label.name.strip(),
            color=label.color,
            shape_type=label.shape_type,
            sort_order=index,
        )
        for index, label in enumerate(labels)
    ]
    db.add(job)
    db.flush()

    data_root = Path(settings.local_storage_root) / "data"
    try:
        for frame_index, upload in enumerate(files):
            file_path, thumbnail_path, width, height = save_uploaded_image(upload, data_root=data_root)
            db.add(
                Image(
                    project=project,
                    task=task,
                    job=job,
                    filename=Path(upload.filename or Path(file_path).name).name,
                    file_path=file_path,
                    thumbnail_path=thumbnail_path,
                    width=width,
                    height=height,
                    frame_index=frame_index,
                )
            )
    except InvalidImageError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.commit()
    return get_job(job.id, db)


@router.get("/{job_id}", response_model=JobDetailRead)
def get_job(job_id: int, db: Session = Depends(get_db)) -> JobDetailRead:
    job = db.scalar(
        select(Job)
        .where(Job.id == job_id)
        .options(
            selectinload(Job.images),
            selectinload(Job.labels),
            selectinload(Job.task).selectinload(Task.images),
            selectinload(Job.task).selectinload(Task.project).selectinload(Project.labels),
            selectinload(Job.annotations),
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    images = _job_images(job)
    image_ids = [image.id for image in images]
    annotations = db.scalars(
        select(Annotation).where(Annotation.job_id == job.id, Annotation.image_id.in_(image_ids))
    ).all()
    labels = _job_labels(job)

    return JobDetailRead(
        id=job.id,
        project_id=job.project_id,
        name=job.name,
        status=job.status,
        task_id=job.task_id,
        images=[
            JobImageRead(
                id=image.id,
                filename=image.filename,
                width=image.width,
                height=image.height,
                frame_index=image.frame_index,
                image_url=f"/api/images/{image.id}/file",
                thumbnail_url=f"/api/images/{image.id}/thumbnail",
            )
            for image in images
        ],
        labels=[LabelRead.model_validate(label) for label in labels],
        annotations=[AnnotationRead.model_validate(annotation) for annotation in annotations],
    )


@router.put("/{job_id}/images/{image_id}/annotations", response_model=list[AnnotationRead])
def save_image_annotations(
    job_id: int,
    image_id: int,
    payload: AnnotationSaveRequest,
    db: Session = Depends(get_db),
) -> list[Annotation]:
    job = db.get(Job, job_id)
    image = db.get(Image, image_id)
    if job is None or image is None or not _image_belongs_to_job(image, job):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job image not found")

    label_ids = {label.id for label in db.scalars(select(Label).where(Label.job_id == job.id)).all()}
    if not label_ids:
        label_ids = {label.id for label in db.scalars(select(Label).where(Label.project_id == image.project_id)).all()}
    invalid_label_ids = {annotation.label_id for annotation in payload.annotations} - label_ids
    if invalid_label_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Label does not belong to job")

    db.execute(delete(Annotation).where(Annotation.job_id == job_id, Annotation.image_id == image_id))

    saved_annotations = [
        Annotation(
            image_id=image_id,
            job_id=job_id,
            label_id=annotation.label_id,
            shape_type=annotation.shape_type,
            points=annotation.points,
        )
        for annotation in payload.annotations
    ]
    db.add_all(saved_annotations)
    db.commit()

    for annotation in saved_annotations:
        db.refresh(annotation)

    return saved_annotations


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: int, db: Session = Depends(get_db)) -> None:
    job = db.scalar(
        select(Job)
        .where(Job.id == job_id)
        .options(
            selectinload(Job.images),
            selectinload(Job.task).selectinload(Task.images),
            selectinload(Job.labels),
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    images = _job_images(job)
    image_ids = [image.id for image in images]
    label_ids = [label.id for label in job.labels]
    file_paths = _image_file_paths(images)

    annotation_conditions = [Annotation.job_id == job.id]
    if image_ids:
        annotation_conditions.append(Annotation.image_id.in_(image_ids))
    if label_ids:
        annotation_conditions.append(Annotation.label_id.in_(label_ids))

    db.execute(delete(Annotation).where(or_(*annotation_conditions)))
    if image_ids:
        db.execute(delete(Image).where(Image.id.in_(image_ids)))
    db.execute(delete(Label).where(Label.job_id == job.id))
    db.execute(delete(Job).where(Job.id == job.id))
    db.commit()

    _delete_files(file_paths)


@router.get("/{job_id}/export/labelme")
def export_job_labelme(job_id: int, db: Session = Depends(get_db)) -> StreamingResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    archive = build_job_labelme_zip(job, db)
    filename = f"job_{job.id}_labelme.zip"
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{job_id}/export/overlay")
def export_job_overlay_images(job_id: int, db: Session = Depends(get_db)) -> StreamingResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    archive = build_job_overlay_zip(job, db)
    filename = f"job_{job.id}_overlay_images.zip"
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{job_id}/export/indexed-mask")
def export_job_indexed_masks(job_id: int, db: Session = Depends(get_db)) -> StreamingResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    try:
        archive = build_job_indexed_mask_zip(job, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    filename = f"job_{job.id}_indexed_masks.zip"
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{job_id}/export/color-mask")
def export_job_color_masks(job_id: int, db: Session = Depends(get_db)) -> StreamingResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    archive = build_job_color_mask_zip(job, db)
    filename = f"job_{job.id}_color_masks.zip"
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _thumbnail_url(thumbnail_path: str) -> str:
    return _storage_url(thumbnail_path)


def _storage_url(storage_path: str) -> str:
    storage_root = Path(settings.local_storage_root).resolve()
    path = Path(storage_path).resolve()

    try:
        relative_path = path.relative_to(storage_root)
    except ValueError:
        return ""

    return f"/storage/{relative_path.as_posix()}"


def _ordered_images(images: list[Image]) -> list[Image]:
    return sorted(
        images,
        key=lambda image: (
            image.frame_index is None,
            image.frame_index if image.frame_index is not None else 0,
            _natural_key(image.filename),
            image.id,
        ),
    )


def _natural_key(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def _job_images(job: Job) -> list[Image]:
    if job.images:
        return _ordered_images(job.images)
    if job.task is not None:
        return _ordered_images(job.task.images)
    return []


def _job_labels(job: Job) -> list[Label]:
    if job.labels:
        return sorted(job.labels, key=lambda label: (label.sort_order, label.id))
    if job.task is not None and job.task.project is not None:
        return sorted(job.task.project.labels, key=lambda label: (label.id,))
    return []


def _image_belongs_to_job(image: Image, job: Job) -> bool:
    if image.job_id is not None:
        return image.job_id == job.id
    return job.task_id is not None and image.task_id == job.task_id


def _image_file_paths(images: list[Image]) -> list[str]:
    paths: list[str] = []
    for image in images:
        paths.extend([image.file_path, image.thumbnail_path])
    return paths


def _delete_files(paths: list[str]) -> None:
    for path in paths:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to delete image file %s: %s", path, exc)


def _parse_labels_json(labels_json: str) -> list[JobLabelCreate]:
    try:
        raw_labels = json.loads(labels_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="labels_json is invalid") from exc

    if not isinstance(raw_labels, list):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="labels_json must be a list")

    labels: list[JobLabelCreate] = []
    seen: set[str] = set()
    for raw_label in raw_labels:
        label = JobLabelCreate.model_validate(raw_label)
        name = label.name.strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Label name is required")
        key = name.lower()
        if key in seen:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Duplicate label: {name}")
        seen.add(key)
        labels.append(JobLabelCreate(name=name, shape_type=label.shape_type, color=label.color))

    return labels
