from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import io
import json
import re
from typing import Any, Iterator

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import ResearchVideo
from app.schemas.research_phase import (
    ResearchPhaseAnnotationSetDetail,
    ResearchPhaseSegmentResponse,
    ResearchPhaseValidationResponse,
)
from app.services.download_filenames import build_attachment_content_disposition, sanitize_filename
from app.services.phase_label_mapping import (
    build_mapping_export_manifest,
    calculate_mapping_statistics,
    map_phase_segments,
    merge_adjacent_mapped_segments,
    profile_key,
    resolve_mapping_rules,
)
from app.services.research_phase_service import get_phase_annotation_set, validate_phase_annotation_set

CSV_BATCH_SIZE = 1000
FRAMEWISE_UNLABELED_KEY = "unlabeled"
FRAMEWISE_UNLABELED_NAME = "Unlabeled"
PHASE_EXPORT_SCHEMA_VERSION = 2
PHASE_EXPORT_VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm")
WINDOWS_RESERVED_FILENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass(frozen=True)
class PhaseJsonExportResult:
    filename: str
    payload: dict[str, Any]
    headers: dict[str, str]


@dataclass(frozen=True)
class PhaseStreamExportResult:
    filename: str
    iterator: Iterator[bytes]
    headers: dict[str, str]
    validation: ResearchPhaseValidationResponse | None = None


def build_phase_json_export(
    db: Session,
    annotation_set_id: int,
    *,
    mapping_profile_id: int | None = None,
) -> PhaseJsonExportResult:
    context = _load_export_context(db, annotation_set_id, include_validation=True)
    detail = context.annotation_set
    video = context.video
    validation = context.validation
    assert validation is not None
    mapping_profile = None
    segments_payload: list[dict[str, Any]]
    mapping_statistics: dict[str, Any] | None = None
    if mapping_profile_id is not None:
        mapping_profile = resolve_mapping_rules(
            db,
            mapping_profile_id,
            protocol_id=detail.protocol_id,
            require_published=True,
        )
        mapped_segments = merge_adjacent_mapped_segments(
            map_phase_segments(detail.segments, mapping_profile, frame_count=int(video.frame_count or 0))
        )
        mapping_statistics = calculate_mapping_statistics(
            detail.segments,
            mapped_segments,
            frame_count=int(video.frame_count or 0),
        )
        if not mapping_statistics["frame_conservation_passed"]:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Mapped phase export failed frame conservation.")
        segments_payload = [
            _mapped_segment_to_export_json(segment, video.fps)
            for segment in mapped_segments
        ]
    else:
        segments_payload = [
            _segment_to_export_json(segment, video.fps)
            for segment in detail.segments
        ]

    payload = {
        "schema_version": PHASE_EXPORT_SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "manifest": build_mapping_export_manifest(
            mapping_profile,
            video_id=video.id,
            video_display_name=video.name,
            annotation_set=detail,
        ),
        "video": {
            "id": video.id,
            "name": video.name,
            "original_filename": video.original_filename,
            "width": video.width,
            "height": video.height,
            "fps": video.fps,
            "frame_count": video.frame_count,
            "duration_ms": video.duration_ms,
        },
        "annotation_set": {
            "id": detail.id,
            "status": detail.status,
            "revision": detail.revision,
            "annotator_id": detail.annotator_id,
            "annotator_username": detail.annotator_username,
            "created_at": detail.created_at.isoformat(),
            "updated_at": detail.updated_at.isoformat(),
            "submitted_at": detail.submitted_at.isoformat() if detail.submitted_at is not None else None,
        },
        "protocol": {
            "id": detail.protocol.id,
            "name": detail.protocol.name,
            "version": detail.protocol.version,
            "status": detail.protocol.status,
            "labels": [label.model_dump(mode="json") for label in detail.protocol.labels],
        },
        "segments": segments_payload,
        "mapping_statistics": mapping_statistics,
        "validation": validation.model_dump(mode="json"),
    }
    filename = build_phase_export_filename(
        video_display_name=video.name,
        video_id=video.id,
        mapping_profile_key=profile_key(mapping_profile) if mapping_profile is not None else None,
        mapping_mode="profile" if mapping_profile is not None else "original",
    )
    return PhaseJsonExportResult(
        filename=filename,
        payload=payload,
        headers=build_phase_export_headers(
            filename,
            ascii_fallback=f"research-video-{detail.video_id}.json",
        ),
    )


def iter_phase_segment_csv(db: Session, annotation_set_id: int) -> PhaseStreamExportResult:
    context = _load_export_context(db, annotation_set_id, include_validation=False)
    detail = context.annotation_set
    video = context.video

    header = [
        "video_id",
        "video_name",
        "original_filename",
        "annotation_set_id",
        "annotation_status",
        "revision",
        "protocol_id",
        "protocol_name",
        "protocol_version",
        "annotator_id",
        "annotator_username",
        "segment_id",
        "phase_label_id",
        "phase_key",
        "phase_name",
        "start_frame",
        "end_frame_exclusive",
        "start_time_ms",
        "end_time_ms",
        "duration_frames",
        "duration_ms",
        "source",
        "confidence",
        "notes",
    ]

    def rows() -> Iterator[list[Any]]:
        for segment in detail.segments:
            segment_export = segment_to_export_row(detail, segment, video)
            yield [segment_export[column] for column in header]

    return PhaseStreamExportResult(
        filename=context.segment_csv_filename,
        iterator=_iter_csv_bytes(header, rows()),
        headers=build_phase_export_headers(
            context.segment_csv_filename,
            ascii_fallback=f"video_{detail.video_id}_phase_segments.csv",
        ),
    )


def iter_phase_framewise_csv(db: Session, annotation_set_id: int) -> PhaseStreamExportResult:
    context = _load_export_context(db, annotation_set_id, include_validation=True)
    detail = context.annotation_set
    video = context.video
    validation = context.validation
    assert validation is not None

    header = [
        "frame_index",
        "timestamp_ms",
        "phase_key",
        "phase_name",
        "phase_label_id",
        "segment_id",
        "annotation_status",
    ]
    ordered_segments = list(detail.segments)
    frame_count = max(0, int(video.frame_count or 0))

    def rows() -> Iterator[list[Any]]:
        active_segments: deque[ResearchPhaseSegmentResponse] = deque()
        next_segment_index = 0

        for frame_index in range(frame_count):
            while next_segment_index < len(ordered_segments):
                next_segment = ordered_segments[next_segment_index]
                if next_segment.start_frame > frame_index:
                    break
                active_segments.append(next_segment)
                next_segment_index += 1

            while active_segments:
                front = active_segments[0]
                if front.end_frame_exclusive is None or front.end_frame_exclusive > frame_index:
                    break
                active_segments.popleft()

            timestamp_ms = frame_to_timestamp_ms(frame_index, video.fps)
            covering_segment = active_segments[0] if active_segments else None
            if covering_segment is None:
                yield [
                    frame_index,
                    timestamp_ms,
                    FRAMEWISE_UNLABELED_KEY,
                    FRAMEWISE_UNLABELED_NAME,
                    None,
                    None,
                    detail.status,
                ]
                continue

            yield [
                frame_index,
                timestamp_ms,
                covering_segment.phase_label.key,
                covering_segment.phase_label.name,
                covering_segment.phase_label_id,
                covering_segment.id,
                detail.status,
            ]

    headers = build_phase_export_headers(
        context.framewise_csv_filename,
        ascii_fallback=f"video_{detail.video_id}_phase_framewise.csv",
        extra_headers={
            "X-Phase-Validation-Errors": str(validation.issue_counts.error),
            "X-Phase-Validation-Warnings": str(validation.issue_counts.warning),
        },
    )
    return PhaseStreamExportResult(
        filename=context.framewise_csv_filename,
        iterator=_iter_csv_bytes(header, rows()),
        headers=headers,
        validation=validation,
    )


def frame_to_timestamp_ms(frame_index: int, fps: float | None) -> int | None:
    if fps is None or fps <= 0:
        return None
    return round(frame_index / fps * 1000)


def segment_to_export_row(
    annotation_set: ResearchPhaseAnnotationSetDetail,
    segment: ResearchPhaseSegmentResponse,
    video: ResearchVideo,
) -> dict[str, Any]:
    start_time_ms = frame_to_timestamp_ms(segment.start_frame, video.fps)
    end_time_ms = frame_to_timestamp_ms(segment.end_frame_exclusive, video.fps) if segment.end_frame_exclusive is not None else None
    duration_frames = (
        segment.end_frame_exclusive - segment.start_frame
        if segment.end_frame_exclusive is not None
        else None
    )
    duration_ms = (
        round(duration_frames / video.fps * 1000)
        if duration_frames is not None and video.fps is not None and video.fps > 0
        else None
    )
    return {
        "video_id": annotation_set.video_id,
        "video_name": video.name,
        "original_filename": video.original_filename,
        "annotation_set_id": annotation_set.id,
        "annotation_status": annotation_set.status,
        "revision": annotation_set.revision,
        "protocol_id": annotation_set.protocol_id,
        "protocol_name": annotation_set.protocol.name,
        "protocol_version": annotation_set.protocol.version,
        "annotator_id": annotation_set.annotator_id,
        "annotator_username": annotation_set.annotator_username,
        "segment_id": segment.id,
        "phase_label_id": segment.phase_label_id,
        "phase_key": segment.phase_label.key,
        "phase_name": segment.phase_label.name,
        "start_frame": segment.start_frame,
        "end_frame_exclusive": segment.end_frame_exclusive,
        "start_time_ms": start_time_ms,
        "end_time_ms": end_time_ms,
        "duration_frames": duration_frames,
        "duration_ms": duration_ms,
        "source": segment.source,
        "confidence": segment.confidence,
        "notes": segment.notes,
    }


def build_phase_export_headers(
    filename: str,
    ascii_fallback: str,
    *,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json; charset=utf-8" if filename.endswith(".json") else "text/csv; charset=utf-8",
        "Content-Disposition": build_attachment_content_disposition(filename, ascii_fallback),
    }
    if extra_headers:
        headers.update(extra_headers)
    return headers


@dataclass(frozen=True)
class _PhaseExportContext:
    annotation_set: ResearchPhaseAnnotationSetDetail
    video: ResearchVideo
    validation: ResearchPhaseValidationResponse | None
    json_filename: str
    segment_csv_filename: str
    framewise_csv_filename: str


def _load_export_context(
    db: Session,
    annotation_set_id: int,
    *,
    include_validation: bool,
) -> _PhaseExportContext:
    annotation_set = get_phase_annotation_set(db, annotation_set_id)
    video = db.get(ResearchVideo, annotation_set.video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research video not found.")
    safe_video_name = sanitize_filename(video.name, fallback=f"video_{video.id}")
    validation = validate_phase_annotation_set(db, annotation_set_id) if include_validation else None
    return _PhaseExportContext(
        annotation_set=annotation_set,
        video=video,
        validation=validation,
        json_filename=build_phase_export_filename(
            video_display_name=video.name,
            video_id=video.id,
            mapping_profile_key=None,
            mapping_mode="original",
        ),
        segment_csv_filename=f"{safe_video_name}_phase_segments.csv",
        framewise_csv_filename=f"{safe_video_name}_phase_framewise.csv",
    )


def build_phase_export_filename(
    *,
    video_display_name: str | None,
    video_id: int,
    mapping_profile_key: str | None,
    mapping_mode: str,
) -> str:
    stem = _safe_phase_filename_stem(_strip_video_extension((video_display_name or "").strip()))
    if not stem:
        stem = f"research-video-{video_id}"
    if mapping_mode == "profile" and mapping_profile_key:
        profile_key_stem = _safe_phase_filename_stem(mapping_profile_key, fallback="mapping-profile")
        stem = f"{stem}__{profile_key_stem}"
    return f"{stem}.json"


def _strip_video_extension(display_name: str) -> str:
    lower_name = display_name.lower()
    for extension in PHASE_EXPORT_VIDEO_EXTENSIONS:
        if lower_name.endswith(extension):
            return display_name[: -len(extension)]
    return display_name


def _safe_phase_filename_stem(value: str, *, fallback: str = "") -> str:
    sanitized = re.sub(r"[\x00-\x1f\x7f]", "", value)
    sanitized = re.sub(r'[\\/:*?"<>|]', "_", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized)
    sanitized = sanitized.strip(" .")
    if sanitized.upper() in WINDOWS_RESERVED_FILENAMES:
        sanitized = f"{sanitized}_file"
    sanitized = sanitized[:180].rstrip(" .")
    return sanitized or fallback


def _segment_to_export_json(
    segment: ResearchPhaseSegmentResponse,
    fps: float | None,
) -> dict[str, Any]:
    start_time_ms = frame_to_timestamp_ms(segment.start_frame, fps)
    end_time_ms = frame_to_timestamp_ms(segment.end_frame_exclusive, fps) if segment.end_frame_exclusive is not None else None
    duration_frames = (
        segment.end_frame_exclusive - segment.start_frame
        if segment.end_frame_exclusive is not None
        else None
    )
    duration_ms = (
        round(duration_frames / fps * 1000)
        if duration_frames is not None and fps is not None and fps > 0
        else None
    )
    return {
        "id": segment.id,
        "phase_label_id": segment.phase_label_id,
        "phase_key": segment.phase_label.key,
        "phase_name": segment.phase_label.name,
        "color": segment.phase_label.color,
        "start_frame": segment.start_frame,
        "end_frame_exclusive": segment.end_frame_exclusive,
        "start_time_ms": start_time_ms,
        "end_time_ms": end_time_ms,
        "duration_frames": duration_frames,
        "duration_ms": duration_ms,
        "source": segment.source,
        "confidence": segment.confidence,
        "notes": segment.notes,
    }


def _mapped_segment_to_export_json(
    segment: Any,
    fps: float | None,
) -> dict[str, Any]:
    start_time_ms = frame_to_timestamp_ms(segment.start_frame, fps)
    end_time_ms = frame_to_timestamp_ms(segment.end_frame_exclusive, fps)
    duration_frames = segment.end_frame_exclusive - segment.start_frame
    duration_ms = (
        round(duration_frames / fps * 1000)
        if fps is not None and fps > 0
        else None
    )
    return {
        "target_id": segment.target_id,
        "target_key": segment.target_key,
        "target_name": segment.target_name,
        "target_color": segment.target_color,
        "start_frame": segment.start_frame,
        "end_frame_exclusive": segment.end_frame_exclusive,
        "start_time_ms": start_time_ms,
        "end_time_ms": end_time_ms,
        "duration_frames": duration_frames,
        "duration_ms": duration_ms,
        "source_segment_ids": segment.source_segment_ids,
        "source_label_ids": segment.source_label_ids,
        "source_label_names": segment.source_label_names,
        "source_segments": segment.source_segments,
        "notes": [
            {
                "source_segment_id": source_segment["segment_id"],
                "note": source_segment.get("notes"),
            }
            for source_segment in segment.source_segments
            if source_segment.get("notes") is not None
        ],
    }


def _iter_csv_bytes(
    header: list[str],
    rows: Iterator[list[Any]],
    *,
    batch_size: int = CSV_BATCH_SIZE,
) -> Iterator[bytes]:
    yield b"\xef\xbb\xbf"
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")

    writer.writerow(header)
    batch_count = 0
    for row in rows:
        writer.writerow([_csv_cell(value) for value in row])
        batch_count += 1
        if batch_count >= batch_size:
            yield buffer.getvalue().encode("utf-8")
            buffer.seek(0)
            buffer.truncate(0)
            batch_count = 0

    remaining = buffer.getvalue()
    if remaining:
        yield remaining.encode("utf-8")


def _csv_cell(value: Any) -> Any:
    return "" if value is None else value


def serialize_phase_json_export(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
