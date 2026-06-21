from __future__ import annotations

from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Annotation, Image, Job

ExportScope = Literal["all", "annotated_only"]


def normalize_export_scope(export_scope: str | None) -> ExportScope:
    normalized = (export_scope or "all").strip().lower()
    if normalized == "all":
        return "all"
    if normalized == "annotated_only":
        return "annotated_only"
    raise ValueError("Invalid export_scope. Use 'all' or 'annotated_only'.")


def load_job_export_bundle(
    job: Job,
    db: Session,
    *,
    export_scope: str | None = "all",
) -> tuple[list[Image], dict[int, list[Annotation]]]:
    normalized_scope = normalize_export_scope(export_scope)
    images = _job_images(job, db)
    image_ids = [image.id for image in images]
    annotations = _job_annotations(job.id, image_ids, db)

    annotations_by_image: dict[int, list[Annotation]] = {}
    for annotation in annotations:
        annotations_by_image.setdefault(annotation.image_id, []).append(annotation)

    if normalized_scope == "annotated_only":
        annotated_image_ids = set(annotations_by_image)
        if not annotated_image_ids:
            raise ValueError("No annotated images found in this job.")
        images = [image for image in images if image.id in annotated_image_ids]
        annotations_by_image = {
            image_id: annotations_by_image[image_id]
            for image_id in annotated_image_ids
        }

    return _ordered_images(images), annotations_by_image


def get_annotated_image_counts(db: Session, job_ids: list[int]) -> dict[int, int]:
    unique_job_ids = sorted(set(job_ids))
    if not unique_job_ids:
        return {}

    rows = db.execute(
        select(
            Annotation.job_id,
            func.count(func.distinct(Annotation.image_id)),
        )
        .where(Annotation.job_id.in_(unique_job_ids))
        .group_by(Annotation.job_id)
    ).all()

    return {int(job_id): int(count) for job_id, count in rows}


def _job_images(job: Job, db: Session) -> list[Image]:
    images = list(db.scalars(select(Image).where(Image.job_id == job.id)).all())
    if not images and job.task_id is not None:
        images = list(db.scalars(select(Image).where(Image.task_id == job.task_id)).all())
    return _ordered_images(images)


def _job_annotations(job_id: int, image_ids: list[int], db: Session) -> list[Annotation]:
    if not image_ids:
        return []

    return list(
        db.scalars(
            select(Annotation)
            .where(Annotation.job_id == job_id, Annotation.image_id.in_(image_ids))
            .options(selectinload(Annotation.label))
        ).all()
    )


def _ordered_images(images: list[Image]) -> list[Image]:
    return sorted(
        images,
        key=lambda image: (
            image.frame_index is None,
            image.frame_index if image.frame_index is not None else 0,
            image.filename.lower(),
            image.id,
        ),
    )
