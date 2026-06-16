from __future__ import annotations

import xml.etree.ElementTree as ET

from app.services.importers.base import ImportParseResult, ImportSkippedItem, ImportSourceFile, ImportedAnnotation


def parse_voc(files: list[ImportSourceFile]) -> ImportParseResult:
    result = ImportParseResult(format_detected="voc")

    for source in files:
        try:
            root = ET.fromstring(source.content)
        except ET.ParseError as exc:
            result.errors.append(f"{source.name}: invalid XML ({exc})")
            continue

        if root.tag.lower() != "annotation":
            result.skipped_items.append(ImportSkippedItem(source.name, "not a Pascal VOC XML"))
            continue

        image_name = (root.findtext("filename") or source.name).strip()
        for obj in root.findall("object"):
            label_name = (obj.findtext("name") or "").strip()
            box = obj.find("bndbox")
            if not label_name or box is None:
                result.skipped_items.append(ImportSkippedItem(source.name, "object missing name or bndbox"))
                continue

            try:
                rectangle = [
                    [float(box.findtext("xmin") or 0), float(box.findtext("ymin") or 0)],
                    [float(box.findtext("xmax") or 0), float(box.findtext("ymax") or 0)],
                ]
            except ValueError:
                result.skipped_items.append(ImportSkippedItem(source.name, f"{label_name}: invalid bndbox"))
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
