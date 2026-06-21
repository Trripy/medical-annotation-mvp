from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image as PILImage
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Image, Job, Label, Task
from app.services.importers.base import ImportSkippedItem, ImportedAnnotation
from app.services.label_colors import LABEL_COLOR_PALETTE, normalize_hex_color, pick_distinct_label_color


@dataclass(frozen=True)
class MatchedImage:
    image: Image
    key: str


def normalize_name_variants(name: str) -> list[str]:
    base = Path(name).name
    stem = Path(base).stem
    lowered_base = base.lower()
    lowered_stem = stem.lower()
    variants = [base, lowered_base]
    if stem:
        variants.extend([stem, lowered_stem])
    return list(dict.fromkeys(variants))


def build_image_lookup(images: Iterable[Image]) -> dict[str, Image]:
    lookup: dict[str, Image] = {}
    for image in images:
        for variant in normalize_name_variants(image.filename):
            lookup.setdefault(variant, image)
    return lookup


def match_image_for_name(name: str, lookup: dict[str, Image]) -> Image | None:
    path = Path(name)
    stem = path.stem
    candidates = [
        name,
        stem,
        stem.removesuffix("_mask"),
        stem.removesuffix("_color_mask"),
        f"{stem.removesuffix('_mask')}.jpg",
        f"{stem.removesuffix('_mask')}.jpeg",
        f"{stem.removesuffix('_mask')}.png",
        f"{stem.removesuffix('_color_mask')}.jpg",
        f"{stem.removesuffix('_color_mask')}.jpeg",
        f"{stem.removesuffix('_color_mask')}.png",
    ]
    for candidate in candidates:
        for variant in normalize_name_variants(candidate):
            matched = lookup.get(variant)
            if matched is not None:
                return matched
    for variant in normalize_name_variants(name):
        matched = lookup.get(variant)
        if matched is not None:
            return matched
    return None


def safe_json_loads(content: bytes) -> dict | list:
    return json.loads(content.decode("utf-8"))


def generate_label_color(index: int) -> str:
    return LABEL_COLOR_PALETTE[index % len(LABEL_COLOR_PALETTE)]


def clamp_point(point: list[float], width: int | None, height: int | None) -> list[float]:
    x, y = float(point[0]), float(point[1])
    if width is not None:
        x = min(max(x, 0.0), float(width))
    if height is not None:
        y = min(max(y, 0.0), float(height))
    return [x, y]


def scale_polygon(points: list[list[float]], width: int, height: int) -> list[list[float]]:
    return [[float(x) * width, float(y) * height] for x, y in points]


def bbox_to_rectangle(bbox: list[float]) -> list[list[float]]:
    x, y, w, h = [float(value) for value in bbox]
    return [[x, y], [x + w, y + h]]


def points_to_rectangle(points: list[list[float]]) -> list[list[float]]:
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return [[min(xs), min(ys)], [max(xs), max(ys)]]


def mask_to_polygons(mask, *, min_area: int = 10, epsilon_ratio: float = 0.002) -> list[list[list[float]]]:
    import cv2

    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    polygons: list[list[list[float]]] = []

    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < min_area:
            continue

        epsilon = max(1.0, epsilon_ratio * cv2.arcLength(contour, True))
        approx = cv2.approxPolyDP(contour, epsilon, True)
        points = [[float(point[0][0]), float(point[0][1])] for point in approx]
        if len(points) >= 3:
            polygons.append(points)

    return polygons


def image_size_from_file(path: str) -> tuple[int, int]:
    with PILImage.open(path) as image:
        return image.size


def job_images_for_import(job: Job, db: Session) -> list[Image]:
    images = list(db.scalars(select(Image).where(Image.job_id == job.id)).all())
    if not images and job.task_id is not None:
        images = list(db.scalars(select(Image).where(Image.task_id == job.task_id)).all())
    return sorted(
        images,
        key=lambda image: (
            image.frame_index is None,
            image.frame_index if image.frame_index is not None else 0,
            image.filename.lower(),
            image.id,
        ),
    )


def job_labels_for_import(job: Job, db: Session) -> list[Label]:
    labels = list(db.scalars(select(Label).where(Label.job_id == job.id)).all())
    if labels:
        return sorted(labels, key=lambda label: (label.sort_order, label.id))

    project_id = job.project_id
    if project_id is None and job.task_id is not None:
        project_id = db.scalar(select(Task.project_id).where(Task.id == job.task_id))
    if project_id is not None:
        labels = list(db.scalars(select(Label).where(Label.project_id == project_id)).all())
    return sorted(labels, key=lambda label: (label.sort_order, label.id))


def ensure_job_label(
    job: Job,
    db: Session,
    *,
    label_name: str,
    label_color: str | None,
    shape_type: str = "polygon",
) -> Label:
    normalized = label_name.strip()
    if not normalized:
        raise ValueError("Label name is required")

    existing = db.scalar(
        select(Label).where(Label.job_id == job.id, Label.name.ilike(normalized))
    )
    if existing is not None:
        return existing

    sort_order = db.scalar(select(Label.sort_order).where(Label.job_id == job.id).order_by(Label.sort_order.desc()))
    next_sort_order = (sort_order or 0) + 1 if sort_order is not None else 0
    used_colors = [
        label.color
        for label in db.scalars(select(Label).where(Label.job_id == job.id)).all()
        if label.color
    ]
    color = pick_distinct_label_color(label_color or generate_label_color(next_sort_order), used_colors)
    label = Label(
        job_id=job.id,
        name=normalized,
        color=color,
        shape_type=shape_type or "polygon",
        sort_order=next_sort_order,
    )
    db.add(label)
    db.flush()
    return label


def ensure_import_label(
    job: Job,
    db: Session,
    *,
    label_name: str,
    label_color: str | None,
    shape_type: str = "polygon",
    prefer_job_scope: bool = True,
) -> Label:
    if prefer_job_scope:
        return ensure_job_label(
            job,
            db,
            label_name=label_name,
            label_color=label_color,
            shape_type=shape_type,
        )

    project_id = job.project_id
    if project_id is None and job.task_id is not None:
        project_id = db.scalar(select(Task.project_id).where(Task.id == job.task_id))
    if project_id is None:
        return ensure_job_label(
            job,
            db,
            label_name=label_name,
            label_color=label_color,
            shape_type=shape_type,
        )

    normalized = label_name.strip()
    existing = db.scalar(
        select(Label).where(Label.project_id == project_id, Label.name.ilike(normalized))
    )
    if existing is not None:
        return existing

    sort_order = db.scalar(select(Label.sort_order).where(Label.project_id == project_id).order_by(Label.sort_order.desc()))
    next_sort_order = (sort_order or 0) + 1 if sort_order is not None else 0
    used_colors = [
        label.color
        for label in db.scalars(select(Label).where(Label.project_id == project_id)).all()
        if label.color
    ]
    color = pick_distinct_label_color(label_color or generate_label_color(next_sort_order), used_colors)
    label = Label(
        project_id=project_id,
        name=normalized,
        color=color,
        shape_type=shape_type or "polygon",
        sort_order=next_sort_order,
    )
    db.add(label)
    db.flush()
    return label


def label_color_changed(requested_color: str | None, actual_color: str) -> bool:
    normalized_requested = normalize_hex_color(requested_color)
    normalized_actual = normalize_hex_color(actual_color)
    return normalized_requested is not None and normalized_actual is not None and normalized_requested != normalized_actual


def build_imported_annotation(
    *,
    image: Image,
    label: Label,
    shape_type: str,
    points: list[list[float]],
    source_file: str,
) -> ImportedAnnotation:
    return ImportedAnnotation(
        image_name=image.filename,
        label_name=label.name,
        shape_type=shape_type,  # type: ignore[arg-type]
        points=points,
        source_file=source_file,
        label_color=label.color,
    )
