from __future__ import annotations

import xml.etree.ElementTree as ET

from app.services.importers.base import ImportParseResult, ImportSkippedItem, ImportSourceFile, ImportedAnnotation


def parse_cvat(files: list[ImportSourceFile]) -> ImportParseResult:
    result = ImportParseResult(format_detected="cvat")

    for source in files:
        try:
            root = ET.fromstring(source.content)
        except ET.ParseError as exc:
            result.errors.append(f"{source.name}: invalid XML ({exc})")
            continue

        if root.tag.lower() != "annotations":
            result.skipped_items.append(ImportSkippedItem(source.name, "not a CVAT XML"))
            continue

        for image in root.findall(".//image"):
            image_name = image.attrib.get("name", "").strip()
            if not image_name:
                result.skipped_items.append(ImportSkippedItem(source.name, "image entry missing name"))
                continue

            for polygon in image.findall("polygon"):
                label_name = polygon.attrib.get("label", "").strip()
                points = _parse_cvat_points(polygon.attrib.get("points", ""))
                if not label_name or len(points) < 3:
                    result.skipped_items.append(ImportSkippedItem(source.name, f"{image_name}: invalid polygon"))
                    continue
                result.annotations.append(
                    ImportedAnnotation(
                        image_name=image_name,
                        label_name=label_name,
                        shape_type="polygon",
                        points=points,
                        source_file=source.name,
                    )
                )

            for box in image.findall("box"):
                label_name = box.attrib.get("label", "").strip()
                rectangle = _parse_box(box.attrib)
                if not label_name or rectangle is None:
                    result.skipped_items.append(ImportSkippedItem(source.name, f"{image_name}: invalid box"))
                    continue
                result.annotations.append(
                    ImportedAnnotation(
                        image_name=image_name,
                        label_name=label_name,
                        shape_type="rectangle",
                        points=rectangle,
                        source_file=source.name,
                    )
                )

    return result


def _parse_cvat_points(value: str) -> list[list[float]]:
    points: list[list[float]] = []
    for pair in value.split(";"):
        if not pair.strip():
            continue
        parts = pair.split(",")
        if len(parts) < 2:
            continue
        try:
            points.append([float(parts[0]), float(parts[1])])
        except ValueError:
            continue
    return points


def _parse_box(attributes: dict[str, str]) -> list[list[float]] | None:
    try:
        return [
            [float(attributes["xtl"]), float(attributes["ytl"])],
            [float(attributes["xbr"]), float(attributes["ybr"])],
        ]
    except (KeyError, ValueError):
        return None
