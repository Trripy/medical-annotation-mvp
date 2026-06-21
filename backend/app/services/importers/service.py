from __future__ import annotations

from collections import defaultdict
from io import BytesIO
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Annotation, Image, Job, Label
from app.services.importers.base import (
    ImportFormat,
    ImportMode,
    ImportParseResult,
    ImportSkippedItem,
    ImportSourceFile,
    MissingLabelPolicy,
)
from app.services.importers.coco_importer import parse_coco
from app.services.importers.cvat_importer import parse_cvat
from app.services.importers.format_detect import detect_import_format_from_content
from app.services.importers.labelme_importer import parse_labelme
from app.services.importers.mask_importer import parse_mask
from app.services.importers.utils import (
    build_image_lookup,
    clamp_point,
    ensure_import_label,
    job_images_for_import,
    job_labels_for_import,
    label_color_changed,
    match_image_for_name,
)
from app.services.label_colors import normalize_hex_color
from app.services.importers.via_importer import parse_via
from app.services.importers.voc_importer import parse_voc
from app.services.importers.yolo_importer import parse_yolo


MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 1024 * 1024 * 1024


def import_labels_for_job(
    *,
    job: Job,
    db: Session,
    uploads: list[tuple[str, bytes]],
    import_format: ImportFormat,
    import_mode: ImportMode,
    missing_label_policy: MissingLabelPolicy,
) -> dict:
    if not uploads:
        raise ValueError("At least one annotation file is required")

    source_files = _expand_source_files(uploads)
    images = job_images_for_import(job, db)
    labels = job_labels_for_import(job, db)
    parse_result = _parse_sources(source_files, import_format, images, labels)

    image_lookup = build_image_lookup(images)
    annotations_by_image: dict[int, list[tuple[Label, str, list[list[float]], str]]] = defaultdict(list)
    matched_image_ids: set[int] = set()
    created_labels: list[str] = []
    created_label_details: list[dict[str, object]] = []
    skipped_items = list(parse_result.skipped_items)
    prefer_job_scope = db.scalar(select(Label.id).where(Label.job_id == job.id).limit(1)) is not None

    existing_labels = {
        label.name.lower(): label
        for label in db.scalars(select(Label).where(Label.job_id == job.id)).all()
    }
    if not existing_labels:
        existing_labels = {label.name.lower(): label for label in labels}

    for imported in parse_result.annotations:
        image = match_image_for_name(imported.image_name, image_lookup)
        if image is None:
            skipped_items.append(ImportSkippedItem(imported.source_file, f"{imported.image_name}: image not matched"))
            continue

        label_key = imported.label_name.strip().lower()
        label = existing_labels.get(label_key)
        if label is None:
            if missing_label_policy == "skip":
                skipped_items.append(ImportSkippedItem(imported.source_file, f"{imported.label_name}: unknown label"))
                continue
            label = ensure_import_label(
                job,
                db,
                label_name=imported.label_name,
                label_color=imported.label_color,
                shape_type=imported.shape_type,
                prefer_job_scope=prefer_job_scope,
            )
            existing_labels[label_key] = label
            created_labels.append(label.name)
            requested_color = normalize_hex_color(imported.label_color)
            changed = label_color_changed(imported.label_color, label.color)
            created_label_details.append(
                {
                    "name": label.name,
                    "color": label.color,
                    "requested_color": requested_color,
                    "color_changed": changed,
                    "reason": "requested color conflicts with an existing label color" if changed else None,
                }
            )

        clamped_points = [clamp_point(point, image.width, image.height) for point in imported.points]
        annotations_by_image[image.id].append((label, imported.shape_type, clamped_points, imported.source_file))
        matched_image_ids.add(image.id)

    if import_mode == "replace_all_job":
        db.execute(delete(Annotation).where(Annotation.job_id == job.id))
    elif import_mode == "replace_matched_images" and matched_image_ids:
        db.execute(
            delete(Annotation).where(
                Annotation.job_id == job.id,
                Annotation.image_id.in_(matched_image_ids),
            )
        )

    created_annotation_count = 0
    for image_id, rows in annotations_by_image.items():
        for label, shape_type, points, source_file in rows:
            db.add(
                Annotation(
                    image_id=image_id,
                    job_id=job.id,
                    label_id=label.id,
                    shape_type=shape_type,
                    points=points,
                    attributes={"import_source": source_file},
                )
            )
            created_annotation_count += 1

    db.flush()
    return {
        "job_id": job.id,
        "format_detected": parse_result.format_detected,
        "matched_images": len(matched_image_ids),
        "unmatched_items": sum(1 for item in skipped_items if "image not matched" in item.reason),
        "created_annotations": created_annotation_count,
        "created_labels": list(dict.fromkeys(created_labels)),
        "created_label_details": _dedupe_created_label_details(created_label_details),
        "reassigned_conflicting_colors": sum(1 for item in created_label_details if item["color_changed"]),
        "skipped_items": [{"source": item.source, "reason": item.reason} for item in skipped_items],
        "errors": parse_result.errors,
    }


def _dedupe_created_label_details(details: list[dict[str, object]]) -> list[dict[str, object]]:
    deduped: dict[str, dict[str, object]] = {}
    for detail in details:
        deduped.setdefault(str(detail["name"]).lower(), detail)
    return list(deduped.values())


def _expand_source_files(uploads: list[tuple[str, bytes]]) -> list[ImportSourceFile]:
    source_files: list[ImportSourceFile] = []
    total_bytes = 0
    for filename, content in uploads:
        total_bytes += len(content)
        if total_bytes > MAX_UPLOAD_BYTES:
            raise ValueError("Uploaded annotation files exceed 200MB")
        if Path(filename).suffix.lower() == ".zip":
            source_files.extend(_expand_zip(filename, content))
        else:
            if _is_ignored_path(filename) or not content:
                continue
            source_files.append(ImportSourceFile(name=filename, content=content))
    return source_files


def _expand_zip(filename: str, content: bytes) -> list[ImportSourceFile]:
    expanded: list[ImportSourceFile] = []
    total_uncompressed = 0
    try:
        with ZipFile(BytesIO(content)) as archive:
            for info in archive.infolist():
                if info.is_dir() or _is_ignored_path(info.filename):
                    continue
                if _is_unsafe_zip_path(info.filename):
                    raise ValueError(f"{filename}: unsafe zip path {info.filename}")
                total_uncompressed += info.file_size
                if total_uncompressed > MAX_ZIP_TOTAL_BYTES:
                    raise ValueError(f"{filename}: uncompressed zip content exceeds 1GB")
                data = archive.read(info)
                if data:
                    expanded.append(ImportSourceFile(name=info.filename, content=data))
    except BadZipFile as exc:
        raise ValueError(f"{filename}: invalid zip file") from exc
    return expanded


def _parse_sources(
    source_files: list[ImportSourceFile],
    import_format: ImportFormat,
    images: list[Image],
    labels: list[Label],
) -> ImportParseResult:
    if import_format != "auto":
        return _parse_by_format(import_format, source_files, images, labels)

    grouped: dict[str, list[ImportSourceFile]] = defaultdict(list)
    result = ImportParseResult(format_detected="auto")
    support_files: list[ImportSourceFile] = []
    for source in source_files:
        if Path(source.name).name.lower() in {"classes.txt", "obj.names", "data.yaml", "dataset.yaml"}:
            support_files.append(source)
            continue
        detected = detect_import_format_from_content(source.name, source.content)
        if detected is None:
            result.skipped_items.append(
                ImportSkippedItem(source.name, "Cannot detect annotation format. Please select the format manually.")
            )
            continue
        grouped[detected].append(source)

    if "yolo" in grouped:
        grouped["yolo"].extend(support_files)
    else:
        for source in support_files:
            result.skipped_items.append(
                ImportSkippedItem(source.name, "Cannot detect annotation format. Please select the format manually.")
            )

    for detected_format, files in grouped.items():
        result.extend(_parse_by_format(detected_format, files, images, labels))
    return result


def _parse_by_format(
    import_format: str,
    source_files: list[ImportSourceFile],
    images: list[Image],
    labels: list[Label],
) -> ImportParseResult:
    if import_format == "labelme":
        return parse_labelme(_files_with_suffix(source_files, {".json"}))
    if import_format == "coco":
        return parse_coco(_files_with_suffix(source_files, {".json"}))
    if import_format == "cvat":
        return parse_cvat(_files_with_suffix(source_files, {".xml"}))
    if import_format == "yolo":
        return parse_yolo(source_files, images)
    if import_format == "mask":
        return parse_mask(source_files, images, labels)
    if import_format == "voc":
        return parse_voc(_files_with_suffix(source_files, {".xml"}))
    if import_format == "via":
        return parse_via(_files_with_suffix(source_files, {".json"}))
    if import_format == "supervisely":
        return ImportParseResult(
            format_detected="supervisely",
            skipped_items=[ImportSkippedItem(source.name, "Supervisely JSON import is not implemented yet") for source in source_files],
        )
    return ImportParseResult(
        format_detected=import_format,
        errors=[f"Unsupported import format: {import_format}"],
    )


def _files_with_suffix(files: list[ImportSourceFile], suffixes: set[str]) -> list[ImportSourceFile]:
    return [file for file in files if Path(file.name).suffix.lower() in suffixes]


def _is_ignored_path(path: str) -> bool:
    parts = PurePosixPath(path.replace("\\", "/")).parts
    return any(part == "__MACOSX" or part.startswith(".") for part in parts)


def _is_unsafe_zip_path(path: str) -> bool:
    posix = PurePosixPath(path.replace("\\", "/"))
    return posix.is_absolute() or any(part == ".." for part in posix.parts)
