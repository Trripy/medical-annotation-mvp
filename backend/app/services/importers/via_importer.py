from __future__ import annotations

from app.services.importers.base import ImportParseResult, ImportSkippedItem, ImportSourceFile, ImportedAnnotation
from app.services.importers.utils import safe_json_loads


LABEL_KEYS = ("label", "name", "class", "category")


def parse_via(files: list[ImportSourceFile]) -> ImportParseResult:
    result = ImportParseResult(format_detected="via")

    for source in files:
        try:
            data = safe_json_loads(source.content)
        except Exception as exc:
            result.errors.append(f"{source.name}: invalid JSON ({exc})")
            continue

        image_entries = _image_entries(data)
        if not image_entries:
            result.skipped_items.append(ImportSkippedItem(source.name, "not a VIA JSON"))
            continue

        for entry in image_entries:
            filename = str(entry.get("filename") or entry.get("file_name") or "").strip()
            if not filename:
                result.skipped_items.append(ImportSkippedItem(source.name, "image entry missing filename"))
                continue

            for region in entry.get("regions") or []:
                if not isinstance(region, dict):
                    continue
                shape = region.get("shape_attributes") or {}
                attrs = region.get("region_attributes") or {}
                label_name = _label_from_attrs(attrs)
                if not label_name:
                    result.skipped_items.append(ImportSkippedItem(source.name, f"{filename}: region missing label"))
                    continue

                annotation = _parse_region(filename, label_name, shape, source.name)
                if annotation is None:
                    result.skipped_items.append(ImportSkippedItem(source.name, f"{filename}: unsupported region"))
                    continue
                result.annotations.append(annotation)

    return result


def _image_entries(data: object) -> list[dict]:
    if not isinstance(data, dict):
        return []
    if "_via_img_metadata" in data and isinstance(data["_via_img_metadata"], dict):
        return [value for value in data["_via_img_metadata"].values() if isinstance(value, dict)]
    if "metadata" in data and isinstance(data["metadata"], dict):
        entries = []
        for value in data["metadata"].values():
            if isinstance(value, dict) and "filename" in value:
                entries.append(value)
        return entries
    return [value for value in data.values() if isinstance(value, dict) and "regions" in value]


def _label_from_attrs(attrs: object) -> str:
    if not isinstance(attrs, dict):
        return ""
    for key in LABEL_KEYS:
        value = attrs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            selected = next((name for name, enabled in value.items() if enabled), "")
            if selected:
                return str(selected)
    return ""


def _parse_region(filename: str, label_name: str, shape: dict, source_file: str) -> ImportedAnnotation | None:
    shape_name = str(shape.get("name") or shape.get("shape") or "").lower()
    if shape_name in {"polygon", "polyline"}:
        xs = shape.get("all_points_x") or []
        ys = shape.get("all_points_y") or []
        if len(xs) != len(ys) or len(xs) < 3:
            return None
        points = [[float(x), float(y)] for x, y in zip(xs, ys)]
        return ImportedAnnotation(filename, label_name, "polygon", points, source_file)

    if shape_name in {"rect", "rectangle"}:
        try:
            x = float(shape.get("x"))
            y = float(shape.get("y"))
            width = float(shape.get("width"))
            height = float(shape.get("height"))
        except (TypeError, ValueError):
            return None
        return ImportedAnnotation(filename, label_name, "rectangle", [[x, y], [x + width, y + height]], source_file)

    return None
