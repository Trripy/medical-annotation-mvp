from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image as PILImage
from PIL import ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Annotation, Image, Job, Label, Task
from app.services.export_scope import load_job_export_bundle

OVERLAY_ALPHA = 90
OVERLAY_OUTLINE_WIDTH = 2
POINT_RADIUS = 4


def build_job_overlay_zip(job: Job, db: Session, *, export_scope: str | None = "all") -> BytesIO:
    images, annotations_by_image, _labels = _load_export_data(job, db, export_scope=export_scope)
    buffer = BytesIO()

    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as zip_file:
        for image in images:
            with PILImage.open(image.file_path) as original:
                base = original.convert("RGBA")
                overlay = PILImage.new("RGBA", base.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay)
                for annotation in _ordered_annotations(annotations_by_image.get(image.id, [])):
                    _draw_overlay_annotation(draw, annotation)

                rendered = PILImage.alpha_composite(base, overlay).convert("RGB")
                zip_file.writestr(_output_name(image.filename, "_overlay.png"), _png_bytes(rendered))

    buffer.seek(0)
    return buffer


def build_job_indexed_mask_zip(job: Job, db: Session, *, export_scope: str | None = "all") -> BytesIO:
    images, annotations_by_image, labels = _load_export_data(job, db, export_scope=export_scope)
    if len(labels) > 255:
        raise ValueError("Indexed mask export supports up to 255 labels")

    label_to_index = {label.id: index + 1 for index, label in enumerate(labels)}
    buffer = BytesIO()

    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as zip_file:
        for image in images:
            size = _image_size(image)
            mask = PILImage.new("L", size, 0)
            draw = ImageDraw.Draw(mask)
            for annotation in _ordered_annotations(annotations_by_image.get(image.id, [])):
                class_index = label_to_index.get(annotation.label_id)
                if class_index is None:
                    continue
                _draw_mask_annotation(draw, annotation, class_index)

            zip_file.writestr(_output_name(image.filename, "_mask.png"), _png_bytes(mask))

    buffer.seek(0)
    return buffer


def build_job_color_mask_zip(job: Job, db: Session, *, export_scope: str | None = "all") -> BytesIO:
    images, annotations_by_image, labels = _load_export_data(job, db, export_scope=export_scope)
    label_colors = {label.id: _hex_to_rgb(label.color) for label in labels}
    buffer = BytesIO()

    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as zip_file:
        for image in images:
            size = _image_size(image)
            mask = PILImage.new("RGB", size, (0, 0, 0))
            draw = ImageDraw.Draw(mask)
            for annotation in _ordered_annotations(annotations_by_image.get(image.id, [])):
                color = label_colors.get(annotation.label_id)
                if color is None:
                    continue
                _draw_mask_annotation(draw, annotation, color)

            zip_file.writestr(_output_name(image.filename, "_color_mask.png"), _png_bytes(mask))

    buffer.seek(0)
    return buffer


def _load_export_data(
    job: Job,
    db: Session,
    *,
    export_scope: str | None = "all",
) -> tuple[list[Image], dict[int, list[Annotation]], list[Label]]:
    images, annotations_by_image = load_job_export_bundle(job, db, export_scope=export_scope)
    return images, annotations_by_image, _job_labels(job, db)


def _job_labels(job: Job, db: Session) -> list[Label]:
    labels = list(db.scalars(select(Label).where(Label.job_id == job.id)).all())
    if labels:
        return _ordered_labels(labels)

    project_id = job.project_id
    if project_id is None and job.task_id is not None:
        project_id = db.scalar(select(Task.project_id).where(Task.id == job.task_id))
    if project_id is None:
        return []

    return _ordered_labels(list(db.scalars(select(Label).where(Label.project_id == project_id)).all()))


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


def _ordered_labels(labels: list[Label]) -> list[Label]:
    return sorted(labels, key=lambda label: (label.sort_order, label.id))


def _ordered_annotations(annotations: list[Annotation]) -> list[Annotation]:
    return sorted(annotations, key=lambda annotation: (annotation.z_order, annotation.id))


def _draw_overlay_annotation(draw: ImageDraw.ImageDraw, annotation: Annotation) -> None:
    rgb = _hex_to_rgb(annotation.label.color if annotation.label else "#22c55e")
    fill = (*rgb, OVERLAY_ALPHA)
    outline = (*rgb, 255)

    if annotation.shape_type == "polygon":
        points = _points(annotation.points)
        if len(points) >= 3:
            draw.polygon(points, fill=fill)
            draw.line([*points, points[0]], fill=outline, width=OVERLAY_OUTLINE_WIDTH)
        return

    if annotation.shape_type == "rectangle":
        rectangle = _rectangle(annotation.points)
        if rectangle:
            draw.rectangle(rectangle, fill=fill, outline=outline, width=OVERLAY_OUTLINE_WIDTH)
        return

    if annotation.shape_type == "point":
        point = _first_point(annotation.points)
        if point:
            x, y = point
            draw.ellipse(
                (x - POINT_RADIUS, y - POINT_RADIUS, x + POINT_RADIUS, y + POINT_RADIUS),
                fill=outline,
            )


def _draw_mask_annotation(draw: ImageDraw.ImageDraw, annotation: Annotation, fill: int | tuple[int, int, int]) -> None:
    if annotation.shape_type == "polygon":
        points = _points(annotation.points)
        if len(points) >= 3:
            draw.polygon(points, fill=fill)
        return

    if annotation.shape_type == "rectangle":
        rectangle = _rectangle(annotation.points)
        if rectangle:
            draw.rectangle(rectangle, fill=fill)


def _points(points: list) -> list[tuple[float, float]]:
    return [(float(point[0]), float(point[1])) for point in points if len(point) >= 2]


def _first_point(points: list) -> tuple[float, float] | None:
    parsed = _points(points)
    return parsed[0] if parsed else None


def _rectangle(points: list) -> tuple[float, float, float, float] | None:
    parsed = _points(points)
    if len(parsed) < 2:
        return None

    x1, y1 = parsed[0]
    x2, y2 = parsed[1]
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    normalized = value.strip().lstrip("#")
    if len(normalized) == 3:
        normalized = "".join(part * 2 for part in normalized)
    if len(normalized) != 6:
        return 34, 197, 94

    try:
        return int(normalized[0:2], 16), int(normalized[2:4], 16), int(normalized[4:6], 16)
    except ValueError:
        return 34, 197, 94


def _image_size(image: Image) -> tuple[int, int]:
    if image.width and image.height:
        return image.width, image.height

    with PILImage.open(image.file_path) as original:
        return original.size


def _output_name(filename: str, suffix: str) -> str:
    return f"{Path(filename).stem}{suffix}"


def _png_bytes(image: PILImage.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
