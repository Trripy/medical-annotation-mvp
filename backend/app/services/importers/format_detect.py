from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


SUPPORTED_IMAGE_EXTENSIONS = {".png", ".bmp", ".tif", ".tiff"}


def detect_import_format_from_path(path: str, content: bytes) -> str | None:
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        try:
            data = json.loads(content.decode("utf-8"))
        except Exception:
            return None
        if isinstance(data, dict):
            if "shapes" in data and "imagePath" in data:
                return "labelme"
            if {"images", "annotations", "categories"}.issubset(data.keys()):
                return "coco"
            if "_via_img_metadata" in data or "metadata" in data:
                return "via"
            if "annotations" in data and isinstance(data["annotations"], list):
                return "supervisely"
        return None

    if suffix == ".xml":
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            return None
        tag = root.tag.lower()
        if tag == "annotations":
            return "cvat"
        if tag == "annotation":
            return "voc"
        return None

    if suffix == ".txt":
        text = content.decode("utf-8", errors="ignore").strip()
        if not text:
            return None
        if all(re.fullmatch(r"[0-9.\s-]+", line.strip()) for line in text.splitlines() if line.strip()):
            return "yolo"
        return None

    if suffix in SUPPORTED_IMAGE_EXTENSIONS:
        return "mask"

    return None


def detect_import_format_from_content(path: str, content: bytes) -> str | None:
    detected = detect_import_format_from_path(path, content)
    if detected is not None:
        return detected

    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        try:
            data = json.loads(content.decode("utf-8"))
        except Exception:
            return None
        if isinstance(data, dict):
            if "shapes" in data:
                return "labelme"
            if {"images", "annotations", "categories"}.issubset(data.keys()):
                return "coco"
            if "_via_img_metadata" in data or "metadata" in data:
                return "via"
            if "annotations" in data:
                return "supervisely"
    return None
