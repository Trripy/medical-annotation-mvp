from __future__ import annotations

import re
from pathlib import Path

from app.models import Image
from app.services.importers.base import ImportParseResult, ImportSkippedItem, ImportSourceFile, ImportedAnnotation
from app.services.importers.utils import build_image_lookup, match_image_for_name


def parse_yolo(files: list[ImportSourceFile], images: list[Image]) -> ImportParseResult:
    result = ImportParseResult(format_detected="yolo")
    image_lookup = build_image_lookup(images)
    class_names = _load_class_names(files)

    for source in files:
        if Path(source.name).suffix.lower() != ".txt":
            continue
        if Path(source.name).name.lower() in {"classes.txt", "obj.names"}:
            continue

        image = _match_yolo_image(source.name, image_lookup)
        if image is None:
            result.skipped_items.append(ImportSkippedItem(source.name, "image not matched"))
            continue
        if not image.width or not image.height:
            result.skipped_items.append(ImportSkippedItem(source.name, "matched image has no dimensions"))
            continue

        lines = source.content.decode("utf-8", errors="ignore").splitlines()
        for line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            values = stripped.split()
            if len(values) < 5:
                result.skipped_items.append(ImportSkippedItem(source.name, f"line {line_number}: too few values"))
                continue

            try:
                class_id = int(float(values[0]))
                numbers = [float(value) for value in values[1:]]
            except ValueError:
                result.skipped_items.append(ImportSkippedItem(source.name, f"line {line_number}: non-numeric value"))
                continue

            label_name = class_names.get(class_id, f"class_{class_id}")
            if len(numbers) == 4:
                x_center, y_center, width, height = numbers
                x1 = (x_center - width / 2) * image.width
                y1 = (y_center - height / 2) * image.height
                x2 = (x_center + width / 2) * image.width
                y2 = (y_center + height / 2) * image.height
                result.annotations.append(
                    ImportedAnnotation(
                        image_name=image.filename,
                        label_name=label_name,
                        shape_type="rectangle",
                        points=[[x1, y1], [x2, y2]],
                        source_file=source.name,
                    )
                )
                continue

            if len(numbers) >= 6 and len(numbers) % 2 == 0:
                points = [
                    [numbers[index] * image.width, numbers[index + 1] * image.height]
                    for index in range(0, len(numbers), 2)
                ]
                result.annotations.append(
                    ImportedAnnotation(
                        image_name=image.filename,
                        label_name=label_name,
                        shape_type="polygon",
                        points=points,
                        source_file=source.name,
                    )
                )
                continue

            result.skipped_items.append(ImportSkippedItem(source.name, f"line {line_number}: unsupported YOLO row"))

    return result


def _match_yolo_image(source_name: str, lookup: dict[str, Image]) -> Image | None:
    path = Path(source_name)
    candidates = [
        path.name,
        path.with_suffix(".jpg").name,
        path.with_suffix(".jpeg").name,
        path.with_suffix(".png").name,
        path.with_suffix(".bmp").name,
        path.stem,
    ]
    for candidate in candidates:
        matched = match_image_for_name(candidate, lookup)
        if matched is not None:
            return matched
    return None


def _load_class_names(files: list[ImportSourceFile]) -> dict[int, str]:
    for source in files:
        if Path(source.name).name.lower() in {"classes.txt", "obj.names"}:
            names = [
                line.strip()
                for line in source.content.decode("utf-8", errors="ignore").splitlines()
                if line.strip()
            ]
            return {index: name for index, name in enumerate(names)}

    for source in files:
        if Path(source.name).name.lower() not in {"data.yaml", "dataset.yaml"}:
            continue
        text = source.content.decode("utf-8", errors="ignore")
        names = _parse_yaml_names(text)
        if names:
            return {index: name for index, name in enumerate(names)}

    return {}


def _parse_yaml_names(text: str) -> list[str]:
    inline = re.search(r"names\s*:\s*\[(.*?)\]", text, re.DOTALL)
    if inline:
        return [
            item.strip().strip("'\"")
            for item in inline.group(1).split(",")
            if item.strip().strip("'\"")
        ]

    lines = text.splitlines()
    names: list[str] = []
    in_names = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("names:"):
            in_names = True
            continue
        if in_names:
            if not stripped.startswith("-"):
                break
            name = stripped[1:].strip().strip("'\"")
            if name:
                names.append(name)
    return names
