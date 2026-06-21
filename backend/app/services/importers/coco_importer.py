from __future__ import annotations

from app.services.importers.base import ImportParseResult, ImportSkippedItem, ImportSourceFile, ImportedAnnotation
from app.services.importers.utils import bbox_to_rectangle, safe_json_loads
from app.services.label_colors import normalize_hex_color


def parse_coco(files: list[ImportSourceFile]) -> ImportParseResult:
    result = ImportParseResult(format_detected="coco")

    for source in files:
        try:
            data = safe_json_loads(source.content)
        except Exception as exc:
            result.errors.append(f"{source.name}: invalid JSON ({exc})")
            continue

        if not isinstance(data, dict) or not {"images", "annotations", "categories"}.issubset(data.keys()):
            result.skipped_items.append(ImportSkippedItem(source.name, "not a COCO JSON"))
            continue

        categories = {
            int(category["id"]): (
                str(category.get("name") or f"class_{category['id']}"),
                _parse_coco_color(category.get("color") or category.get("rgb")),
            )
            for category in data.get("categories", [])
            if isinstance(category, dict) and "id" in category
        }
        images = {
            int(image["id"]): image
            for image in data.get("images", [])
            if isinstance(image, dict) and "id" in image
        }

        for annotation in data.get("annotations", []):
            if not isinstance(annotation, dict):
                continue
            image_id = annotation.get("image_id")
            category_id = annotation.get("category_id")
            image = images.get(int(image_id)) if image_id is not None else None
            if image is None:
                result.skipped_items.append(ImportSkippedItem(source.name, f"annotation {annotation.get('id')}: image not found"))
                continue

            label_name, label_color = categories.get(int(category_id), (f"class_{category_id}", None))
            segmentation = annotation.get("segmentation")
            bbox = annotation.get("bbox")

            if isinstance(segmentation, list) and segmentation:
                polygon = _parse_coco_segmentation(segmentation, image)
                if polygon is None:
                    result.skipped_items.append(ImportSkippedItem(source.name, f"annotation {annotation.get('id')}: unsupported segmentation"))
                    continue
                result.annotations.append(
                    ImportedAnnotation(
                        image_name=str(image.get("file_name") or ""),
                        label_name=label_name,
                        shape_type="polygon",
                        points=polygon,
                        source_file=source.name,
                        label_color=label_color,
                    )
                )
                continue

            if isinstance(bbox, list) and len(bbox) >= 4:
                result.annotations.append(
                    ImportedAnnotation(
                        image_name=str(image.get("file_name") or ""),
                        label_name=label_name,
                        shape_type="rectangle",
                        points=bbox_to_rectangle(bbox[:4]),
                        source_file=source.name,
                        label_color=label_color,
                    )
                )
                continue

            result.skipped_items.append(ImportSkippedItem(source.name, f"annotation {annotation.get('id')}: no usable segmentation or bbox"))

    return result


def _parse_coco_color(value: object) -> str | None:
    if isinstance(value, str):
        return normalize_hex_color(value)
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            r, g, b = [max(0, min(255, int(float(part)))) for part in value[:3]]
        except (TypeError, ValueError):
            return None
        return f"#{r:02x}{g:02x}{b:02x}"
    return None


def _parse_coco_segmentation(segmentation: list, image: dict) -> list[list[float]] | None:
    if not segmentation:
        return None

    first = segmentation[0]
    if isinstance(first, list):
        if len(first) < 6:
            return None
        points = [[float(first[i]), float(first[i + 1])] for i in range(0, len(first), 2)]
        return points if len(points) >= 3 else None

    return None
