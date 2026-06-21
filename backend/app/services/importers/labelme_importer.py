from __future__ import annotations

from app.services.importers.base import ImportParseResult, ImportSkippedItem, ImportSourceFile, ImportedAnnotation
from app.services.importers.utils import points_to_rectangle, safe_json_loads
from app.services.label_colors import normalize_hex_color


def parse_labelme(files: list[ImportSourceFile]) -> ImportParseResult:
    result = ImportParseResult(format_detected="labelme")

    for source in files:
        try:
            data = safe_json_loads(source.content)
        except Exception as exc:
            result.errors.append(f"{source.name}: invalid JSON ({exc})")
            continue

        if not isinstance(data, dict) or "shapes" not in data:
            result.skipped_items.append(ImportSkippedItem(source.name, "not a LabelMe JSON"))
            continue

        image_name = str(data.get("imagePath") or "").strip()
        if not image_name:
            result.skipped_items.append(ImportSkippedItem(source.name, "missing imagePath"))
            continue

        for index, shape in enumerate(data.get("shapes") or []):
            if not isinstance(shape, dict):
                continue
            label_name = str(shape.get("label") or "").strip()
            points = shape.get("points") or []
            if not label_name:
                result.skipped_items.append(ImportSkippedItem(source.name, f"shape {index}: missing label"))
                continue
            parsed_points = _parse_points(points)
            if not parsed_points:
                result.skipped_items.append(ImportSkippedItem(source.name, f"shape {index}: invalid points"))
                continue

            shape_type = str(shape.get("shape_type") or "polygon").lower()
            if shape_type == "rectangle":
                if len(parsed_points) < 2:
                    result.skipped_items.append(ImportSkippedItem(source.name, f"shape {index}: rectangle needs 2 points"))
                    continue
                imported_shape_type = "rectangle"
                imported_points = points_to_rectangle(parsed_points)
            elif shape_type == "point":
                imported_shape_type = "point"
                imported_points = [parsed_points[0]]
            else:
                if len(parsed_points) < 3:
                    result.skipped_items.append(ImportSkippedItem(source.name, f"shape {index}: polygon needs 3 points"))
                    continue
                imported_shape_type = "polygon"
                imported_points = parsed_points

            result.annotations.append(
                ImportedAnnotation(
                    image_name=image_name,
                    label_name=label_name,
                    shape_type=imported_shape_type,  # type: ignore[arg-type]
                    points=imported_points,
                    source_file=source.name,
                    label_color=_parse_labelme_color(shape.get("line_color") or shape.get("fill_color")),
                )
            )

    return result


def _parse_labelme_color(value: object) -> str | None:
    if isinstance(value, str):
        return normalize_hex_color(value)
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            r, g, b = [max(0, min(255, int(float(part)))) for part in value[:3]]
        except (TypeError, ValueError):
            return None
        return f"#{r:02x}{g:02x}{b:02x}"
    return None


def _parse_points(points: object) -> list[list[float]]:
    parsed: list[list[float]] = []
    if not isinstance(points, list):
        return parsed
    for point in points:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                parsed.append([float(point[0]), float(point[1])])
            except (TypeError, ValueError):
                continue
    return parsed
