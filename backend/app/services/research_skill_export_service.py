from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import io
import json
from typing import Any, Iterator

from sqlalchemy.orm import Session

from app.schemas.research_skill import ResearchSkillAssessmentDetail, ResearchSkillValidationResponse
from app.services.download_filenames import build_attachment_content_disposition, sanitize_filename
from app.services.research_skill_service import get_skill_assessment
from app.services.research_skill_validation_service import validate_skill_assessment

SKILL_EXPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SkillJsonExportResult:
    filename: str
    payload: dict[str, Any]
    headers: dict[str, str]


@dataclass(frozen=True)
class SkillCsvExportResult:
    filename: str
    iterator: Iterator[bytes]
    headers: dict[str, str]


def build_skill_json_export(db: Session, assessment_id: int) -> SkillJsonExportResult:
    detail = get_skill_assessment(db, assessment_id)
    validation = validate_skill_assessment(db, assessment_id)
    filename = _json_filename(detail)
    payload = {
        "schema_version": SKILL_EXPORT_SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "video": detail.video.model_dump(mode="json"),
        "rubric": detail.rubric.model_dump(mode="json"),
        "assessment": {
            "id": detail.id,
            "status": detail.status,
            "revision": detail.revision,
            "rater_id": detail.rater_id,
            "rater_username": detail.rater_username,
            "overall_comment": detail.overall_comment,
            "submitted_at": detail.submitted_at.isoformat() if detail.submitted_at is not None else None,
            "reviewed_at": detail.reviewed_at.isoformat() if detail.reviewed_at is not None else None,
            "locked_at": detail.locked_at.isoformat() if detail.locked_at is not None else None,
            "created_at": detail.created_at.isoformat(),
            "updated_at": detail.updated_at.isoformat(),
        },
        "phase_annotation_set": detail.phase_annotation_set.model_dump(mode="json") if detail.phase_annotation_set is not None else None,
        "scores": [score.model_dump(mode="json") for score in detail.scores],
        "validation": validation.model_dump(mode="json"),
    }
    return SkillJsonExportResult(
        filename=filename,
        payload=payload,
        headers=_export_headers(filename, ascii_fallback=f"video_{detail.video_id}_skill_assessment.json"),
    )


def iter_skill_csv_export(db: Session, assessment_id: int) -> SkillCsvExportResult:
    detail = get_skill_assessment(db, assessment_id)
    filename = _csv_filename(detail)
    header = [
        "video_id",
        "video_name",
        "assessment_id",
        "assessment_status",
        "revision",
        "rubric_id",
        "rubric_name",
        "rubric_version",
        "rater_id",
        "rater_username",
        "criterion_id",
        "criterion_key",
        "criterion_name",
        "criterion_scope",
        "score_type",
        "required",
        "allow_na",
        "weight",
        "target_key",
        "phase_segment_id",
        "phase_key",
        "phase_name",
        "segment_start_frame",
        "segment_end_frame_exclusive",
        "value",
        "is_na",
        "comment",
        "evidence_json",
        "created_at",
        "updated_at",
    ]

    def rows() -> Iterator[list[Any]]:
        segment_by_id = {
            segment.id: segment
            for segment in (detail.phase_annotation_set.segments if detail.phase_annotation_set is not None else [])
        }
        for score in detail.scores:
            criterion = next((item for item in detail.rubric.criteria if item.id == score.criterion_id), None)
            segment = segment_by_id.get(score.phase_segment_id) if score.phase_segment_id is not None else None
            yield [
                detail.video_id,
                detail.video.name,
                detail.id,
                detail.status,
                detail.revision,
                detail.rubric_id,
                detail.rubric.name,
                detail.rubric.version,
                detail.rater_id,
                detail.rater_username,
                score.criterion_id,
                score.criterion_key,
                score.criterion_name,
                score.scope,
                score.score_type,
                criterion.required if criterion is not None else "",
                criterion.allow_na if criterion is not None else "",
                criterion.weight if criterion is not None else "",
                score.target_key,
                score.phase_segment_id,
                segment.phase_key if segment is not None else "",
                segment.phase_name if segment is not None else "",
                segment.start_frame if segment is not None else "",
                segment.end_frame_exclusive if segment is not None else "",
                json.dumps(score.value, ensure_ascii=False) if isinstance(score.value, (dict, list)) else score.value,
                score.is_na,
                score.comment,
                json.dumps([evidence.model_dump(mode="json") for evidence in score.evidence], ensure_ascii=False),
                score.created_at.isoformat(),
                score.updated_at.isoformat(),
            ]

    return SkillCsvExportResult(
        filename=filename,
        iterator=_iter_csv_bytes(header, rows()),
        headers=_export_headers(filename, ascii_fallback=f"video_{detail.video_id}_skill_assessment.csv"),
    )


def serialize_skill_json_export(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _json_filename(detail: ResearchSkillAssessmentDetail) -> str:
    return f"{sanitize_filename(detail.video.name, fallback=f'video_{detail.video_id}')}_skill_assessment.json"


def _csv_filename(detail: ResearchSkillAssessmentDetail) -> str:
    return f"{sanitize_filename(detail.video.name, fallback=f'video_{detail.video_id}')}_skill_assessment.csv"


def _export_headers(filename: str, ascii_fallback: str) -> dict[str, str]:
    return {
        "Content-Disposition": build_attachment_content_disposition(filename, ascii_fallback),
    }


def _iter_csv_bytes(header: list[str], rows: Iterator[list[Any]]) -> Iterator[bytes]:
    yield b"\xef\xbb\xbf"
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    yield _pop_csv_buffer(buffer)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
        yield _pop_csv_buffer(buffer)


def _pop_csv_buffer(buffer: io.StringIO) -> bytes:
    value = buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    return value.encode("utf-8")
