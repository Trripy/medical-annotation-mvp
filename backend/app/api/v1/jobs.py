import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, or_, select, update
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
from app.schemas.job import (
    ExportScope,
    JobImportRequest,
    JobImportResponse,
    JobLabelCreate,
    JobLabelDeleteRequest,
    JobLabelDeleteResponse,
    JobLabelPayload,
    JobLabelRead,
    JobLabelUsageRead,
    JobRead,
)
from app.services.download_filenames import (
    build_attachment_content_disposition,
    build_job_export_filename,
)
from app.services.export_scope import get_annotated_image_counts
from app.services.image_storage import InvalidImageError, save_uploaded_image
from app.services.importers import import_labels_for_job
from app.services.label_colors import is_color_conflict, normalize_hex_color, pick_distinct_label_color
from app.services.labelme_export import build_job_labelme_zip
from app.services.export_visual import (
    build_job_color_mask_zip,
    build_job_indexed_mask_zip,
    build_job_overlay_zip,
)

router = APIRouter()
logger = logging.getLogger(__name__)
UNDEFINED_LABEL_NAME = "undefined"
UNDEFINED_LABEL_COLOR = "#9CA3AF"


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

    annotated_counts = get_annotated_image_counts(db, [job.id for job in jobs])
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
                annotated_images_count=annotated_counts.get(job.id, 0),
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
    used_colors: list[str] = []
    job.labels = []
    for index, label in enumerate(labels):
        color = pick_distinct_label_color(label.color, used_colors)
        used_colors.append(color)
        job.labels.append(
            Label(
                job=job,
                name=label.name.strip(),
                color=color,
                shape_type=label.shape_type,
                sort_order=index,
            )
        )
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


@router.get("/{job_id}/labels", response_model=list[JobLabelRead])
def list_job_labels(job_id: int, db: Session = Depends(get_db)) -> list[JobLabelRead]:
    job = _get_job_for_label_management(job_id, db)
    labels, changed = _ensure_job_label_scope(job, db)
    if changed:
        db.commit()
        labels = _job_scoped_labels(job, db)

    return [_label_to_read(label, job, db) for label in labels]


@router.post("/{job_id}/labels", response_model=JobLabelRead, status_code=status.HTTP_201_CREATED)
def create_job_label(
    job_id: int,
    payload: JobLabelPayload,
    db: Session = Depends(get_db),
) -> JobLabelRead:
    job = _get_job_for_label_management(job_id, db)
    labels, _ = _ensure_job_label_scope(job, db)
    _validate_unique_label_name(payload.name, labels)
    _validate_distinct_label_color(payload.color, labels)
    sort_order = max((label.sort_order for label in labels), default=-1) + 1
    label = Label(
        job_id=job.id,
        name=payload.name,
        color=normalize_hex_color(payload.color) or payload.color,
        shape_type=payload.shape_type,
        sort_order=sort_order,
    )
    db.add(label)
    db.commit()
    db.refresh(label)
    return _label_to_read(label, job, db)


@router.put("/{job_id}/labels/{label_id}", response_model=JobLabelRead)
def update_job_label(
    job_id: int,
    label_id: int,
    payload: JobLabelPayload,
    db: Session = Depends(get_db),
) -> JobLabelRead:
    job = _get_job_for_label_management(job_id, db)
    labels, _ = _ensure_job_label_scope(job, db)
    label = _get_job_label_or_404(job, label_id, db)
    if _is_undefined_label(label) and payload.name.lower() != UNDEFINED_LABEL_NAME:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The undefined label is reserved and cannot be renamed",
        )

    _validate_unique_label_name(payload.name, labels, exclude_label_id=label.id)
    _validate_distinct_label_color(payload.color, labels, exclude_label_id=label.id)
    label.name = payload.name
    label.color = normalize_hex_color(payload.color) or payload.color
    label.shape_type = payload.shape_type
    db.commit()
    db.refresh(label)
    return _label_to_read(label, job, db)


@router.get("/{job_id}/labels/{label_id}/usage", response_model=JobLabelUsageRead)
def get_job_label_usage(
    job_id: int,
    label_id: int,
    db: Session = Depends(get_db),
) -> JobLabelUsageRead:
    job = _get_job_for_label_management(job_id, db)
    _ensure_job_label_scope(job, db)
    label = _get_job_label_or_404(job, label_id, db)
    annotation_count, frame_count = _label_usage(label, job, db)
    return JobLabelUsageRead(
        label_id=label.id,
        label_name=label.name,
        annotation_count=annotation_count,
        frame_count=frame_count,
    )


@router.delete("/{job_id}/labels/{label_id}", response_model=JobLabelDeleteResponse)
def delete_job_label(
    job_id: int,
    label_id: int,
    payload: JobLabelDeleteRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> JobLabelDeleteResponse:
    job = _get_job_for_label_management(job_id, db)
    _ensure_job_label_scope(job, db)
    label = _get_job_label_or_404(job, label_id, db)
    annotation_count, _ = _label_usage(label, job, db)
    strategy = payload.strategy if payload else None
    target_label: Label | None = None

    if annotation_count > 0:
        if strategy is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Label is used by annotations. Choose a delete strategy.",
            )

        if strategy == "reassign":
            if payload is None or payload.target_label_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="target_label_id is required when strategy is reassign",
                )
            target_label = _get_job_label_or_404(job, payload.target_label_id, db)
            if target_label.id == label.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="target_label_id cannot be the label being deleted",
                )
            db.execute(
                update(Annotation)
                .where(Annotation.label_id == label.id, _annotation_job_scope(job))
                .values(label_id=target_label.id)
            )
        elif strategy == "move_to_undefined":
            if _is_undefined_label(label):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot move undefined label annotations to undefined.",
                )
            target_label = _get_or_create_undefined_label(job, db)
            db.execute(
                update(Annotation)
                .where(Annotation.label_id == label.id, _annotation_job_scope(job))
                .values(label_id=target_label.id)
            )
        elif strategy == "delete_annotations":
            db.execute(delete(Annotation).where(Annotation.label_id == label.id, _annotation_job_scope(job)))
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported delete strategy")

    db.delete(label)
    db.commit()
    return JobLabelDeleteResponse(
        deleted_label_id=label_id,
        strategy=strategy,
        affected_annotations=annotation_count,
        target_label=target_label.name if target_label is not None else None,
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
            attributes=annotation.attributes,
        )
        for annotation in payload.annotations
    ]
    db.add_all(saved_annotations)
    db.commit()

    for annotation in saved_annotations:
        db.refresh(annotation)

    return saved_annotations


@router.post("/{job_id}/import-labels", response_model=JobImportResponse)
async def import_job_labels(
    job_id: int,
    format: str = Form("auto"),
    import_mode: str = Form("append"),
    missing_label_policy: str = Form("auto_create"),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> JobImportResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    try:
        payload = JobImportRequest(
            format=format,
            import_mode=import_mode,
            missing_label_policy=missing_label_policy,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    uploads: list[tuple[str, bytes]] = []
    for upload in files:
        filename = upload.filename or "upload"
        content = await upload.read()
        uploads.append((filename, content))

    try:
        result = import_labels_for_job(
            job=job,
            db=db,
            uploads=uploads,
            import_format=payload.format,
            import_mode=payload.import_mode,
            missing_label_policy=payload.missing_label_policy,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to import labels for job %s: %s", job_id, exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Import failed") from exc

    return JobImportResponse(**result)


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
def export_job_labelme(
    job_id: int,
    export_scope: ExportScope = "all",
    db: Session = Depends(get_db),
) -> StreamingResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    try:
        archive = build_job_labelme_zip(job, db, export_scope=export_scope)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    filename = build_job_export_filename(job, "labelme", export_scope=export_scope)
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": build_attachment_content_disposition(filename, "export_labelme.zip")},
    )


@router.get("/{job_id}/export/overlay")
def export_job_overlay_images(
    job_id: int,
    export_scope: ExportScope = "all",
    db: Session = Depends(get_db),
) -> StreamingResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    try:
        archive = build_job_overlay_zip(job, db, export_scope=export_scope)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    filename = build_job_export_filename(job, "overlay", export_scope=export_scope)
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": build_attachment_content_disposition(filename, "export_overlay.zip")},
    )


@router.get("/{job_id}/export/indexed-mask")
def export_job_indexed_masks(
    job_id: int,
    export_scope: ExportScope = "all",
    db: Session = Depends(get_db),
) -> StreamingResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    try:
        archive = build_job_indexed_mask_zip(job, db, export_scope=export_scope)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    filename = build_job_export_filename(job, "mask_indexed", export_scope=export_scope)
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": build_attachment_content_disposition(filename, "export_mask_indexed.zip")},
    )


@router.get("/{job_id}/export/color-mask")
def export_job_color_masks(
    job_id: int,
    export_scope: ExportScope = "all",
    db: Session = Depends(get_db),
) -> StreamingResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    try:
        archive = build_job_color_mask_zip(job, db, export_scope=export_scope)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    filename = build_job_export_filename(job, "mask_color", export_scope=export_scope)
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": build_attachment_content_disposition(filename, "export_mask_color.zip")},
    )


def _get_job_for_label_management(job_id: int, db: Session) -> Job:
    job = db.scalar(
        select(Job)
        .where(Job.id == job_id)
        .options(
            selectinload(Job.labels),
            selectinload(Job.images),
            selectinload(Job.project).selectinload(Project.labels),
            selectinload(Job.task).selectinload(Task.images),
            selectinload(Job.task).selectinload(Task.project).selectinload(Project.labels),
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


def _job_scoped_labels(job: Job, db: Session) -> list[Label]:
    return list(
        db.scalars(
            select(Label)
            .where(Label.job_id == job.id)
            .order_by(Label.sort_order.asc(), Label.id.asc())
        ).all()
    )


def _ensure_job_label_scope(job: Job, db: Session) -> tuple[list[Label], bool]:
    labels = _job_scoped_labels(job, db)
    if labels:
        return labels, False

    source_labels = []
    if job.project is not None and job.project.labels:
        source_labels = sorted(job.project.labels, key=lambda label: (label.sort_order, label.id))
    elif job.task is not None and job.task.project is not None:
        source_labels = sorted(job.task.project.labels, key=lambda label: (label.sort_order, label.id))

    if not source_labels:
        return [], False

    created: list[Label] = []
    source_to_created: list[tuple[int, Label]] = []
    seen_names: set[str] = set()
    for index, source_label in enumerate(source_labels):
        key = source_label.name.strip().lower()
        if not key or key in seen_names:
            continue
        seen_names.add(key)
        created_label = Label(
            job_id=job.id,
            name=source_label.name.strip(),
            color=source_label.color,
            shape_type=source_label.shape_type,
            sort_order=index,
        )
        created.append(created_label)
        source_to_created.append((source_label.id, created_label))

    if not created:
        return [], False

    db.add_all(created)
    db.flush()
    scope = _annotation_job_scope(job)
    for source_label_id, created_label in source_to_created:
        db.execute(
            update(Annotation)
            .where(Annotation.label_id == source_label_id, scope)
            .values(label_id=created_label.id)
        )

    return _job_scoped_labels(job, db), True


def _label_to_read(label: Label, job: Job, db: Session) -> JobLabelRead:
    annotation_count, _ = _label_usage(label, job, db)
    return JobLabelRead(
        id=label.id,
        name=label.name,
        color=label.color,
        shape_type=label.shape_type,
        sort_order=label.sort_order,
        annotation_count=annotation_count,
    )


def _get_job_label_or_404(job: Job, label_id: int, db: Session) -> Label:
    label = db.get(Label, label_id)
    if label is None or label.job_id != job.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Label not found")
    return label


def _validate_unique_label_name(
    name: str,
    labels: list[Label],
    *,
    exclude_label_id: int | None = None,
) -> None:
    key = name.strip().lower()
    for label in labels:
        if label.id == exclude_label_id:
            continue
        if label.name.strip().lower() == key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f'Label "{name}" already exists in this job',
            )


def _validate_distinct_label_color(
    color: str,
    labels: list[Label],
    *,
    exclude_label_id: int | None = None,
) -> None:
    normalized = normalize_hex_color(color)
    if normalized is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Label color must be a 6-digit hex color")

    for label in labels:
        if label.id == exclude_label_id:
            continue
        if is_color_conflict(normalized, [label.color]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f'Label color is too similar to "{label.name}"',
            )


def _is_undefined_label(label: Label) -> bool:
    return label.name.strip().lower() == UNDEFINED_LABEL_NAME


def _get_or_create_undefined_label(job: Job, db: Session) -> Label:
    labels = _job_scoped_labels(job, db)
    for label in labels:
        if _is_undefined_label(label):
            return label

    label = Label(
        job_id=job.id,
        name=UNDEFINED_LABEL_NAME,
        color=pick_distinct_label_color(UNDEFINED_LABEL_COLOR, [item.color for item in labels if item.color]),
        shape_type="polygon",
        sort_order=max((item.sort_order for item in labels), default=-1) + 1,
    )
    db.add(label)
    db.flush()
    return label


def _annotation_job_scope(job: Job):
    image_ids = [image.id for image in _job_images(job)]
    if image_ids:
        return or_(Annotation.job_id == job.id, Annotation.image_id.in_(image_ids))
    return Annotation.job_id == job.id


def _label_usage(label: Label, job: Job, db: Session) -> tuple[int, int]:
    scope = _annotation_job_scope(job)
    annotation_count = db.scalar(
        select(func.count(Annotation.id)).where(Annotation.label_id == label.id, scope)
    ) or 0
    frame_count = db.scalar(
        select(func.count(func.distinct(Annotation.image_id))).where(Annotation.label_id == label.id, scope)
    ) or 0
    return annotation_count, frame_count


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
