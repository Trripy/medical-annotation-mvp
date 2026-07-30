from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Literal
from zipfile import ZipFile

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models import Annotation, Image, Job

ExportScope = Literal["all", "annotated_only"]
ExportRange = Literal["all", "annotated", "selected"]

_CONTROL_CHARACTERS_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_UNSAFE_MEMBER_CHARACTERS = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+")


class ExportSelectionError(ValueError):
    status_code = 422


class OriginalImageExportError(ValueError):
    status_code = 409


def normalize_export_scope(export_scope: str | None) -> ExportScope:
    normalized = (export_scope or "all").strip().lower()
    if normalized == "all":
        return "all"
    if normalized == "annotated_only":
        return "annotated_only"
    raise ValueError("Invalid export_scope. Use 'all' or 'annotated_only'.")


def normalize_export_range(export_range: str | None = None, *, export_scope: str | None = None) -> ExportRange:
    if export_range is None:
        legacy_scope = normalize_export_scope(export_scope)
        return "annotated" if legacy_scope == "annotated_only" else "all"

    normalized = export_range.strip().lower()
    if normalized == "annotated_only":
        return "annotated"
    if normalized in {"all", "annotated", "selected"}:
        return normalized  # type: ignore[return-value]
    raise ExportSelectionError("Invalid export_range. Use 'all', 'annotated', or 'selected'.")


def export_range_to_legacy_scope(export_range: str | None) -> ExportScope:
    normalized = normalize_export_range(export_range, export_scope="all")
    return "annotated_only" if normalized == "annotated" else "all"


def load_job_export_bundle(
    job: Job,
    db: Session,
    *,
    export_scope: str | None = "all",
    export_range: str | None = None,
    selected_image_ids: Iterable[int] | None = None,
) -> tuple[list[Image], dict[int, list[Annotation]]]:
    normalized_range = normalize_export_range(export_range, export_scope=export_scope)
    images = _job_images(job, db)
    image_ids = [image.id for image in images]
    annotations = _job_annotations(job.id, image_ids, db)

    annotations_by_image: dict[int, list[Annotation]] = {}
    for annotation in annotations:
        annotations_by_image.setdefault(annotation.image_id, []).append(annotation)

    if normalized_range == "annotated":
        annotated_image_ids = set(annotations_by_image)
        if not annotated_image_ids:
            raise ValueError("No annotated images found in this job.")
        images = [image for image in images if image.id in annotated_image_ids]
        annotations_by_image = {
            image_id: annotations_by_image[image_id]
            for image_id in annotated_image_ids
        }
    elif normalized_range == "selected":
        selected_ids = _dedupe_selected_image_ids(selected_image_ids)
        if not selected_ids:
            raise ExportSelectionError("At least one image must be selected for manual export.")
        job_image_ids = set(image_ids)
        invalid_ids = [image_id for image_id in selected_ids if image_id not in job_image_ids]
        if invalid_ids:
            raise ExportSelectionError("Selected images must belong to this job.")
        selected_id_set = set(selected_ids)
        images = [image for image in images if image.id in selected_id_set]
        annotations_by_image = {
            image_id: image_annotations
            for image_id, image_annotations in annotations_by_image.items()
            if image_id in selected_id_set
        }

    return _ordered_images(images), annotations_by_image


def add_original_images_to_archive(
    zip_file: ZipFile,
    images: list[Image],
    emitted_image_ids: Iterable[int],
) -> list[str]:
    emitted_id_set = set(emitted_image_ids)
    emitted_images = [image for image in images if image.id in emitted_id_set]
    written_paths: list[str] = []
    used_names: set[str] = set()

    for image in emitted_images:
        source_path = _validate_original_image_path(image)
        member_name = safe_original_image_member_name(image, used_names)
        zip_file.write(source_path, member_name)
        written_paths.append(member_name)
        used_names.add(member_name)

    return written_paths


def safe_original_image_member_name(image: Image, used_names: set[str] | None = None) -> str:
    safe_filename = _safe_member_filename(image.filename, fallback=f"image_{image.id}")
    member_name = f"images/{image.id}__{safe_filename}"
    if used_names is None or member_name not in used_names:
        return member_name

    stem = Path(safe_filename).stem or f"image_{image.id}"
    suffix = Path(safe_filename).suffix
    index = 2
    while True:
        candidate = f"images/{image.id}__{stem}_{index}{suffix}"
        if candidate not in used_names:
            return candidate
        index += 1


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


def get_job_image_annotation_counts(db: Session, image_ids: list[int], *, job_id: int) -> dict[int, int]:
    if not image_ids:
        return {}

    rows = db.execute(
        select(
            Annotation.image_id,
            func.count(Annotation.id),
        )
        .where(Annotation.job_id == job_id, Annotation.image_id.in_(image_ids))
        .group_by(Annotation.image_id)
    ).all()

    return {int(image_id): int(count) for image_id, count in rows}


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
            .order_by(Annotation.image_id, Annotation.z_order, Annotation.id)
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


def _dedupe_selected_image_ids(selected_image_ids: Iterable[int] | None) -> list[int]:
    deduped: list[int] = []
    seen: set[int] = set()
    for raw_id in selected_image_ids or []:
        image_id = int(raw_id)
        if image_id in seen:
            continue
        seen.add(image_id)
        deduped.append(image_id)
    return deduped


def _validate_original_image_path(image: Image) -> Path:
    storage_root = Path(settings.local_storage_root).resolve()
    source_path = Path(image.file_path).resolve()

    try:
        source_path.relative_to(storage_root)
    except ValueError as exc:
        raise OriginalImageExportError("A corresponding original image is missing or unreadable.") from exc

    if not source_path.is_file():
        raise OriginalImageExportError("A corresponding original image is missing or unreadable.")

    return source_path


def _safe_member_filename(filename: str | None, *, fallback: str) -> str:
    raw_name = Path(filename or "").name.strip()
    if not raw_name or raw_name in {".", ".."}:
        raw_name = fallback

    normalized = _CONTROL_CHARACTERS_PATTERN.sub("_", raw_name)
    normalized = normalized.replace("/", "_").replace("\\", "_")
    normalized = _UNSAFE_MEMBER_CHARACTERS.sub("_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("._")
    return normalized or fallback
