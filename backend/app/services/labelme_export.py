import json
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Annotation, Image, Job, Task


def build_labelme_zip(task: Task, db: Session) -> BytesIO:
    images = db.scalars(
        select(Image)
        .where(Image.task_id == task.id)
        .options(selectinload(Image.annotations).selectinload(Annotation.label))
    ).all()

    return build_labelme_zip_for_images(_ordered_images(images))


def build_job_labelme_zip(job: Job, db: Session) -> BytesIO:
    images = db.scalars(select(Image).where(Image.job_id == job.id)).all()
    if not images and job.task_id is not None:
        images = db.scalars(select(Image).where(Image.task_id == job.task_id)).all()
    image_ids = [image.id for image in images]
    annotations = db.scalars(
        select(Annotation)
        .where(Annotation.job_id == job.id, Annotation.image_id.in_(image_ids))
        .options(selectinload(Annotation.label))
    ).all()
    annotations_by_image: dict[int, list[Annotation]] = {}
    for annotation in annotations:
        annotations_by_image.setdefault(annotation.image_id, []).append(annotation)

    return build_labelme_zip_for_images(
        _ordered_images(images),
        annotations_by_image=annotations_by_image,
    )


def build_labelme_zip_for_images(
    images: list[Image],
    *,
    annotations_by_image: dict[int, list[Annotation]] | None = None,
) -> BytesIO:
    buffer = BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as zip_file:
        for image in images:
            annotations = annotations_by_image.get(image.id, []) if annotations_by_image is not None else image.annotations
            labelme_json = _build_labelme_json(image, annotations)
            json_name = f"{Path(image.filename).stem}.json"
            zip_file.writestr(
                json_name,
                json.dumps(labelme_json, ensure_ascii=False, indent=2),
            )

    buffer.seek(0)
    return buffer


def _build_labelme_json(image: Image, annotations: list[Annotation]) -> dict:
    return {
        "version": "5.0.0",
        "flags": {},
        "shapes": [_build_shape(annotation) for annotation in annotations],
        "imagePath": image.filename,
        "imageData": None,
        "imageHeight": image.height,
        "imageWidth": image.width,
    }


def _build_shape(annotation: Annotation) -> dict:
    shape_type = annotation.shape_type
    points = annotation.points
    if shape_type == "rectangle":
        shape_type = "polygon"
        points = _rectangle_to_polygon(points)

    return {
        "label": annotation.label.name,
        "points": points,
        "group_id": None,
        "description": "",
        "shape_type": shape_type,
        "flags": {},
    }


def _rectangle_to_polygon(points: list[list[float]]) -> list[list[float]]:
    if len(points) < 2:
        return points

    x1, y1 = points[0]
    x2, y2 = points[1]
    return [
        [x1, y1],
        [x2, y1],
        [x2, y2],
        [x1, y2],
    ]


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
