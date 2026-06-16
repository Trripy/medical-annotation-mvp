from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ImportFormat = Literal[
    "auto",
    "labelme",
    "coco",
    "cvat",
    "yolo",
    "mask",
    "voc",
    "via",
    "supervisely",
]
ImportMode = Literal["append", "replace_matched_images", "replace_all_job"]
MissingLabelPolicy = Literal["auto_create", "skip"]
ShapeType = Literal["polygon", "rectangle", "point"]


@dataclass(frozen=True)
class ImportSourceFile:
    name: str
    content: bytes


@dataclass(frozen=True)
class ImportSkippedItem:
    source: str
    reason: str


@dataclass(frozen=True)
class ImportedAnnotation:
    image_name: str
    label_name: str
    shape_type: ShapeType
    points: list[list[float]]
    source_file: str
    label_color: str | None = None


@dataclass
class ImportParseResult:
    format_detected: str
    annotations: list[ImportedAnnotation] = field(default_factory=list)
    skipped_items: list[ImportSkippedItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def extend(self, other: "ImportParseResult") -> None:
        if self.format_detected == "auto" and other.format_detected != "auto":
            self.format_detected = other.format_detected
        elif other.format_detected != "auto" and self.format_detected != other.format_detected:
            self.format_detected = "mixed"

        self.annotations.extend(other.annotations)
        self.skipped_items.extend(other.skipped_items)
        self.errors.extend(other.errors)
