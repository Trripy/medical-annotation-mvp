from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image as PILImage

from app.models import Image, Label
from app.services.importers.base import ImportParseResult, ImportSkippedItem, ImportSourceFile, ImportedAnnotation
from app.services.importers.utils import build_image_lookup, mask_to_polygons, match_image_for_name


MASK_EXTENSIONS = {".png", ".bmp", ".tif", ".tiff"}


def parse_mask(files: list[ImportSourceFile], images: list[Image], labels: list[Label]) -> ImportParseResult:
    result = ImportParseResult(format_detected="mask")
    image_lookup = build_image_lookup(images)
    label_by_index = {index + 1: label for index, label in enumerate(labels)}
    label_by_color = {_hex_to_rgb(label.color): label for label in labels}

    for source in files:
        if Path(source.name).suffix.lower() not in MASK_EXTENSIONS:
            continue

        image = _match_mask_image(source.name, image_lookup)
        if image is None:
            result.skipped_items.append(ImportSkippedItem(source.name, "image not matched"))
            continue

        try:
            with PILImage.open(BytesIO(source.content)) as raw:
                mask_image = raw.copy()
        except Exception as exc:
            result.errors.append(f"{source.name}: invalid mask image ({exc})")
            continue

        if mask_image.mode in {"L", "P", "I;16", "I"}:
            _parse_indexed_mask(result, source, image.filename, mask_image, label_by_index)
        else:
            _parse_color_mask(result, source, image.filename, mask_image.convert("RGB"), label_by_color)

    return result


def _parse_indexed_mask(
    result: ImportParseResult,
    source: ImportSourceFile,
    image_name: str,
    mask_image: PILImage.Image,
    label_by_index: dict[int, Label],
) -> None:
    import numpy as np

    array = np.array(mask_image.convert("L"))
    for value in sorted(int(v) for v in np.unique(array) if int(v) != 0):
        label = label_by_index.get(value)
        label_name = label.name if label is not None else f"class_{value - 1}"
        label_color = label.color if label is not None else None
        binary = (array == value).astype(np.uint8) * 255
        polygons = mask_to_polygons(binary)
        if not polygons:
            result.skipped_items.append(ImportSkippedItem(source.name, f"mask value {value}: no usable contour"))
            continue
        for polygon in polygons:
            result.annotations.append(
                ImportedAnnotation(
                    image_name=image_name,
                    label_name=label_name,
                    shape_type="polygon",
                    points=polygon,
                    source_file=source.name,
                    label_color=label_color,
                )
            )


def _parse_color_mask(
    result: ImportParseResult,
    source: ImportSourceFile,
    image_name: str,
    mask_image: PILImage.Image,
    label_by_color: dict[tuple[int, int, int], Label],
) -> None:
    import numpy as np

    array = np.array(mask_image)
    colors = sorted({tuple(int(part) for part in color) for color in array.reshape(-1, 3)})
    for color in colors:
        if color == (0, 0, 0):
            continue
        label = label_by_color.get(color)
        label_name = label.name if label is not None else f"color_{color[0]:02x}{color[1]:02x}{color[2]:02x}"
        label_color = label.color if label is not None else f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
        binary = np.all(array == color, axis=2).astype(np.uint8) * 255
        polygons = mask_to_polygons(binary)
        if not polygons:
            result.skipped_items.append(ImportSkippedItem(source.name, f"color {label_color}: no usable contour"))
            continue
        for polygon in polygons:
            result.annotations.append(
                ImportedAnnotation(
                    image_name=image_name,
                    label_name=label_name,
                    shape_type="polygon",
                    points=polygon,
                    source_file=source.name,
                    label_color=label_color,
                )
            )


def _match_mask_image(source_name: str, lookup: dict[str, Image]) -> Image | None:
    path = Path(source_name)
    stem = path.stem
    candidates = [
        path.name,
        stem,
        stem.removesuffix("_mask"),
        stem.removesuffix("_color_mask"),
        f"{stem.removesuffix('_mask')}.jpg",
        f"{stem.removesuffix('_mask')}.png",
        f"{stem.removesuffix('_color_mask')}.jpg",
        f"{stem.removesuffix('_color_mask')}.png",
    ]
    for candidate in candidates:
        matched = match_image_for_name(candidate, lookup)
        if matched is not None:
            return matched
    return None


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
