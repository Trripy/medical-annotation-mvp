from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import zipfile
from typing import Any, Iterable

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ResearchPhaseAnnotationSet,
    ResearchPhaseLabelMappingProfile,
    ResearchPhaseProtocol,
    ResearchPhaseSegment,
    ResearchVideo,
)
from app.schemas.research import (
    ResearchVideoBatchExportInvalidItemRead,
    ResearchVideoBatchExportItemRequest,
    ResearchVideoBatchExportPreviewRead,
    ResearchVideoBatchExportRequest,
    ResearchVideoChecklistAnnotationSetRead,
    ResearchVideoChecklistDefaultPhaseSelectionRead,
    ResearchVideoChecklistDerivedVideoRead,
    ResearchVideoChecklistItemRead,
    ResearchVideoChecklistMappingProfileRead,
    ResearchVideoChecklistPageRead,
    ResearchVideoChecklistPhaseRead,
    ResearchVideoChecklistStatsRead,
    ResearchVideoChecklistTrimRead,
    ResearchVideoChecklistVideoRead,
    ResearchVideoPhaseSummaryRead,
    ResearchVideoVisibilityBulkItemRead,
    ResearchVideoVisibilityBulkPreviewRead,
    ResearchVideoVisibilityBulkResultRead,
)
from app.services.download_filenames import build_attachment_content_disposition, sanitize_filename
from app.services.phase_label_mapping import profile_key
from app.services.research_phase_export_service import build_phase_json_export, serialize_phase_json_export
from app.services.research_video_visibility import (
    TRIMMED_SOURCE_HIDDEN_REASON,
    hide_research_video_from_list,
    restore_research_video_to_list,
)

MAX_CHECKLIST_PAGE_SIZE = 100
MAX_BATCH_EXPORT_VIDEOS = 500
MAX_BATCH_PHASE_EXPORTS = 1000


@dataclass(frozen=True)
class BatchExportFile:
    path: Path
    filename: str
    media_type: str
    headers: dict[str, str]


@dataclass(frozen=True)
class _PhaseMetrics:
    segment_count: int
    coverage_percent: float
    error_count: int
    warning_count: int


def list_video_operation_checklist(
    db: Session,
    *,
    page: int,
    page_size: int,
    search: str | None = None,
    video_status: str | None = None,
    trim_status: str = "all",
    phase_status: str = "all",
    protocol_id: int | None = None,
    visibility: str = "all",
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> ResearchVideoChecklistPageRead:
    normalized_page = max(1, page)
    normalized_page_size = min(max(1, page_size), MAX_CHECKLIST_PAGE_SIZE)
    videos = db.scalars(_video_select(search=search, video_status=video_status)).all()
    if not videos:
        return ResearchVideoChecklistPageRead(items=[], page=normalized_page, page_size=normalized_page_size, total=0)

    video_ids = [video.id for video in videos]
    context = _ChecklistContext.load(db, video_ids)
    all_items = [_build_checklist_item(video, context) for video in videos]
    filtered_items = [
        item for item in all_items
        if _matches_trim_status(item, trim_status)
        and _matches_phase_status(item, phase_status)
        and _matches_protocol(item, protocol_id)
        and _matches_visibility(item, visibility)
    ]
    filtered_items = _sort_items(filtered_items, sort_by=sort_by, sort_order=sort_order)
    start = (normalized_page - 1) * normalized_page_size
    end = start + normalized_page_size
    return ResearchVideoChecklistPageRead(
        items=filtered_items[start:end],
        page=normalized_page,
        page_size=normalized_page_size,
        total=len(filtered_items),
        stats=_build_stats(filtered_items),
    )


def list_default_phase_export_selections(
    db: Session,
    *,
    search: str | None = None,
    video_status: str | None = None,
    trim_status: str = "all",
    phase_status: str = "all",
    protocol_id: int | None = None,
    visibility: str = "all",
) -> list[ResearchVideoChecklistDefaultPhaseSelectionRead]:
    videos = db.scalars(_video_select(search=search, video_status=video_status)).all()
    if not videos:
        return []
    video_ids = [video.id for video in videos]
    context = _ChecklistContext.load(db, video_ids)
    items = [
        _build_checklist_item(video, context)
        for video in videos
    ]
    filtered_items = [
        item for item in items
        if _matches_trim_status(item, trim_status)
        and _matches_phase_status(item, phase_status)
        and _matches_protocol(item, protocol_id)
        and _matches_visibility(item, visibility)
    ]
    selections: list[ResearchVideoChecklistDefaultPhaseSelectionRead] = []
    for item in filtered_items:
        latest = _latest_submitted_annotation_set(item.phase.sets)
        if latest is None:
            continue
        selections.append(
            ResearchVideoChecklistDefaultPhaseSelectionRead(
                video_id=item.video.id,
                annotation_set_id=latest.annotation_set_id,
                status=latest.status,
                version=latest.version,
                submitted_at=latest.submitted_at,
                protocol_id=latest.protocol_id,
                protocol_name=latest.protocol_name,
            )
        )
    return selections


def list_research_video_phase_summaries(
    db: Session,
    video_ids: list[int],
) -> dict[int, ResearchVideoPhaseSummaryRead]:
    if not video_ids:
        return {}
    context = _ChecklistContext.load(db, video_ids)
    summaries: dict[int, ResearchVideoPhaseSummaryRead] = {}
    for video_id in video_ids:
        video = context.videos_by_id.get(video_id)
        if video is None:
            continue
        phase = _build_phase_summary(video, context)
        latest_submitted = _latest_submitted_annotation_set(phase.sets)
        latest_draft = _latest_draft_annotation_set(phase.sets)
        summaries[video_id] = ResearchVideoPhaseSummaryRead(
            annotation_set_count=phase.annotation_set_count,
            draft_count=phase.draft_count,
            submitted_count=phase.submitted_count,
            latest_submitted_set_id=latest_submitted.annotation_set_id if latest_submitted else None,
            latest_submitted_version=latest_submitted.version if latest_submitted else None,
            latest_submitted_protocol_name=latest_submitted.protocol_name if latest_submitted else None,
            latest_submitted_coverage_percent=latest_submitted.coverage_percent if latest_submitted else 0.0,
            latest_draft_set_id=latest_draft.annotation_set_id if latest_draft else None,
            latest_draft_version=latest_draft.version if latest_draft else None,
            latest_error_count=phase.latest_error_count,
            latest_warning_count=phase.latest_warning_count,
        )
    return summaries


def preview_hide_trimmed_source_videos(db: Session) -> ResearchVideoVisibilityBulkPreviewRead:
    eligible = _eligible_trimmed_source_videos(db)
    already_hidden = _already_hidden_trimmed_source_count(db)
    total_roots = _root_source_count(db)
    skipped = max(0, total_roots - len(eligible) - already_hidden)
    return ResearchVideoVisibilityBulkPreviewRead(
        eligible_count=len(eligible),
        already_hidden_count=already_hidden,
        skipped_count=skipped,
        items=eligible[:50],
    )


def hide_trimmed_source_videos(db: Session) -> ResearchVideoVisibilityBulkResultRead:
    eligible_items = _eligible_trimmed_source_videos(db)
    if not eligible_items:
        return ResearchVideoVisibilityBulkResultRead(affected_count=0, items=[])
    video_ids = [item.video_id for item in eligible_items]
    videos = db.scalars(select(ResearchVideo).where(ResearchVideo.id.in_(video_ids))).all()
    for video in videos:
        hide_research_video_from_list(video, reason=TRIMMED_SOURCE_HIDDEN_REASON)
    db.commit()
    return ResearchVideoVisibilityBulkResultRead(affected_count=len(videos), items=eligible_items)


def preview_restore_trimmed_source_videos(db: Session) -> ResearchVideoVisibilityBulkPreviewRead:
    items = _hidden_trimmed_source_videos(db)
    return ResearchVideoVisibilityBulkPreviewRead(
        eligible_count=len(items),
        already_hidden_count=len(items),
        skipped_count=0,
        items=items[:50],
    )


def restore_trimmed_source_videos(db: Session) -> ResearchVideoVisibilityBulkResultRead:
    items = _hidden_trimmed_source_videos(db)
    if not items:
        return ResearchVideoVisibilityBulkResultRead(affected_count=0, items=[])
    video_ids = [item.video_id for item in items]
    videos = db.scalars(select(ResearchVideo).where(ResearchVideo.id.in_(video_ids))).all()
    for video in videos:
        restore_research_video_to_list(video)
    db.commit()
    return ResearchVideoVisibilityBulkResultRead(affected_count=len(videos), items=items)


def preview_video_batch_export(
    db: Session,
    payload: ResearchVideoBatchExportRequest,
) -> ResearchVideoBatchExportPreviewRead:
    validation = _validate_batch_export_request(db, payload)
    selected_video_ids = {item.video_id for item in payload.items if item.include_trim_info or item.phase_exports}
    phase_exports = [
        phase_export
        for item in payload.items
        for phase_export in item.phase_exports
    ]
    return ResearchVideoBatchExportPreviewRead(
        video_count=len(selected_video_ids),
        trim_export_count=sum(1 for item in payload.items if item.include_trim_info),
        phase_export_count=len(phase_exports),
        original_phase_export_count=sum(1 for export in phase_exports if export.mapping_profile_id is None),
        mapped_phase_export_count=sum(1 for export in phase_exports if export.mapping_profile_id is not None),
        archive_entry_count=2 + sum(1 for item in payload.items if item.include_trim_info) + len(phase_exports),
        warnings=validation.warnings,
        invalid_items=validation.invalid_items,
        suggested_filename=_build_batch_zip_filename(payload.batch_name),
    )


def build_video_batch_export(
    db: Session,
    payload: ResearchVideoBatchExportRequest,
) -> BatchExportFile:
    preview = preview_video_batch_export(db, payload)
    if preview.invalid_items:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=[item.model_dump() for item in preview.invalid_items])
    if preview.video_count == 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Select at least one export item.")

    selected_video_ids = sorted({item.video_id for item in payload.items if item.include_trim_info or item.phase_exports})
    context = _ChecklistContext.load(db, selected_video_ids)
    videos_by_id = {video.id: video for video in db.scalars(select(ResearchVideo).where(ResearchVideo.id.in_(selected_video_ids))).all()}
    temp_file = tempfile.NamedTemporaryFile(prefix="research-video-batch-export-", suffix=".zip", delete=False)
    temp_file.close()
    zip_path = Path(temp_file.name)
    try:
        with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            manifest = _build_batch_manifest(payload, preview)
            summary_rows: list[dict[str, Any]] = []
            for item in payload.items:
                video = videos_by_id.get(item.video_id)
                if video is None or (not item.include_trim_info and not item.phase_exports):
                    continue
                checklist_item = _build_checklist_item(video, context)
                video_dir = _video_export_directory(video)
                generated_files: list[str] = []
                if item.include_trim_info:
                    trim_entry = f"{video_dir}/trim.json"
                    archive.writestr(trim_entry, _json_bytes(_build_trim_export_payload(checklist_item)))
                    generated_files.append(trim_entry)
                for phase_spec in item.phase_exports:
                    export_result = build_phase_json_export(
                        db,
                        phase_spec.annotation_set_id,
                        mapping_profile_id=phase_spec.mapping_profile_id,
                    )
                    phase_entry = f"{video_dir}/phase/{sanitize_filename(export_result.filename, fallback=f'phase-{phase_spec.annotation_set_id}.json')}"
                    archive.writestr(phase_entry, serialize_phase_json_export(export_result.payload))
                    generated_files.append(phase_entry)
                manifest["videos"].append({
                    "video_id": video.id,
                    "display_name": video.name,
                    "selected_trim_info": item.include_trim_info,
                    "selected_phase_exports": [spec.model_dump() for spec in item.phase_exports],
                    "generated_files": generated_files,
                })
                summary_rows.append(_summary_row(checklist_item, item))

            if payload.include_summary_csv:
                archive.writestr("summary.csv", _summary_csv_bytes(summary_rows))
            archive.writestr("manifest.json", _json_bytes(manifest))
    except Exception:
        try:
            zip_path.unlink(missing_ok=True)
        finally:
            raise

    filename = _build_batch_zip_filename(payload.batch_name)
    return BatchExportFile(
        path=zip_path,
        filename=filename,
        media_type="application/zip",
        headers={
            "Content-Disposition": build_attachment_content_disposition(filename, "research-video-export.zip"),
        },
    )


def remove_batch_export_file(path: Path) -> None:
    path.unlink(missing_ok=True)


def _video_select(*, search: str | None, video_status: str | None) -> Select[tuple[ResearchVideo]]:
    statement = select(ResearchVideo)
    normalized_search = (search or "").strip()
    if normalized_search:
        statement = statement.where(ResearchVideo.name.ilike(f"%{normalized_search}%"))
    if video_status and video_status != "all":
        statement = statement.where(ResearchVideo.status == video_status)
    return statement.order_by(ResearchVideo.created_at.desc(), ResearchVideo.id.desc())


def _root_source_count(db: Session) -> int:
    return db.scalar(
        select(func.count(ResearchVideo.id))
        .where(ResearchVideo.source_video_id.is_(None))
        .where(ResearchVideo.origin_type.in_(("uploaded", "server_imported")))
    ) or 0


def _already_hidden_trimmed_source_count(db: Session) -> int:
    return db.scalar(
        select(func.count(ResearchVideo.id))
        .where(ResearchVideo.hidden_from_video_list.is_(True))
        .where(ResearchVideo.hidden_reason == TRIMMED_SOURCE_HIDDEN_REASON)
    ) or 0


def _eligible_trimmed_source_videos(db: Session) -> list[ResearchVideoVisibilityBulkItemRead]:
    ready_child_counts = dict(
        db.execute(
            select(ResearchVideo.source_video_id, func.count(ResearchVideo.id))
            .where(ResearchVideo.source_video_id.is_not(None))
            .where(ResearchVideo.origin_type == "trimmed")
            .where(ResearchVideo.status == "ready")
            .group_by(ResearchVideo.source_video_id)
        ).all()
    )
    if not ready_child_counts:
        return []
    sources = db.scalars(
        select(ResearchVideo)
        .where(ResearchVideo.id.in_(ready_child_counts.keys()))
        .where(ResearchVideo.source_video_id.is_(None))
        .where(ResearchVideo.origin_type.in_(("uploaded", "server_imported")))
        .where(ResearchVideo.hidden_from_video_list.is_(False))
        .order_by(ResearchVideo.created_at.desc(), ResearchVideo.id.desc())
    ).all()
    return [
        ResearchVideoVisibilityBulkItemRead(
            video_id=source.id,
            display_name=source.name,
            ready_derived_count=int(ready_child_counts.get(source.id, 0)),
        )
        for source in sources
    ]


def _hidden_trimmed_source_videos(db: Session) -> list[ResearchVideoVisibilityBulkItemRead]:
    videos = db.scalars(
        select(ResearchVideo)
        .where(ResearchVideo.hidden_from_video_list.is_(True))
        .where(ResearchVideo.hidden_reason == TRIMMED_SOURCE_HIDDEN_REASON)
        .order_by(ResearchVideo.hidden_at.desc().nullslast(), ResearchVideo.id.desc())
    ).all()
    ready_child_counts = dict(
        db.execute(
            select(ResearchVideo.source_video_id, func.count(ResearchVideo.id))
            .where(ResearchVideo.source_video_id.in_([video.id for video in videos] or [-1]))
            .where(ResearchVideo.origin_type == "trimmed")
            .where(ResearchVideo.status == "ready")
            .group_by(ResearchVideo.source_video_id)
        ).all()
    )
    return [
        ResearchVideoVisibilityBulkItemRead(
            video_id=video.id,
            display_name=video.name,
            ready_derived_count=int(ready_child_counts.get(video.id, 0)),
        )
        for video in videos
    ]


class _ChecklistContext:
    def __init__(
        self,
        *,
        videos_by_id: dict[int, ResearchVideo],
        sources_by_id: dict[int, ResearchVideo],
        derivatives_by_source: dict[int, list[ResearchVideo]],
        annotation_sets_by_video: dict[int, list[ResearchPhaseAnnotationSet]],
        segments_by_set: dict[int, list[ResearchPhaseSegment]],
        metrics_by_set: dict[int, _PhaseMetrics],
        mapping_profiles_by_protocol: dict[int, list[ResearchPhaseLabelMappingProfile]],
    ) -> None:
        self.videos_by_id = videos_by_id
        self.sources_by_id = sources_by_id
        self.derivatives_by_source = derivatives_by_source
        self.annotation_sets_by_video = annotation_sets_by_video
        self.segments_by_set = segments_by_set
        self.metrics_by_set = metrics_by_set
        self.mapping_profiles_by_protocol = mapping_profiles_by_protocol

    @classmethod
    def load(cls, db: Session, video_ids: list[int]) -> _ChecklistContext:
        if not video_ids:
            return cls(
                videos_by_id={},
                sources_by_id={},
                derivatives_by_source={},
                annotation_sets_by_video={},
                segments_by_set={},
                metrics_by_set={},
                mapping_profiles_by_protocol={},
            )
        videos = db.scalars(select(ResearchVideo).where(ResearchVideo.id.in_(video_ids))).all()
        videos_by_id = {video.id: video for video in videos}
        source_ids = {video.source_video_id for video in videos if video.source_video_id is not None}
        sources = db.scalars(select(ResearchVideo).where(ResearchVideo.id.in_(source_ids))).all() if source_ids else []
        derivatives = db.scalars(
            select(ResearchVideo)
            .where(ResearchVideo.source_video_id.in_(video_ids))
            .order_by(ResearchVideo.created_at.desc(), ResearchVideo.id.desc())
        ).all()
        derivatives_by_source: dict[int, list[ResearchVideo]] = defaultdict(list)
        for derivative in derivatives:
            if derivative.source_video_id is not None:
                derivatives_by_source[derivative.source_video_id].append(derivative)

        annotation_sets = db.scalars(
            select(ResearchPhaseAnnotationSet)
            .where(ResearchPhaseAnnotationSet.video_id.in_(video_ids))
            .options(selectinload(ResearchPhaseAnnotationSet.protocol))
            .order_by(ResearchPhaseAnnotationSet.updated_at.desc(), ResearchPhaseAnnotationSet.id.desc())
        ).all()
        annotation_sets_by_video: dict[int, list[ResearchPhaseAnnotationSet]] = defaultdict(list)
        for annotation_set in annotation_sets:
            annotation_sets_by_video[annotation_set.video_id].append(annotation_set)
        annotation_set_ids = [annotation_set.id for annotation_set in annotation_sets]
        segments = db.scalars(
            select(ResearchPhaseSegment)
            .where(ResearchPhaseSegment.annotation_set_id.in_(annotation_set_ids))
            .options(selectinload(ResearchPhaseSegment.phase_label))
            .order_by(ResearchPhaseSegment.annotation_set_id, ResearchPhaseSegment.start_frame, ResearchPhaseSegment.id)
        ).all() if annotation_set_ids else []
        segments_by_set: dict[int, list[ResearchPhaseSegment]] = defaultdict(list)
        for segment in segments:
            segments_by_set[segment.annotation_set_id].append(segment)
        metrics_by_set = {
            annotation_set.id: _calculate_phase_metrics(
                segments_by_set.get(annotation_set.id, []),
                frame_count=videos_by_id[annotation_set.video_id].frame_count if annotation_set.video_id in videos_by_id else 0,
                fps=videos_by_id[annotation_set.video_id].fps if annotation_set.video_id in videos_by_id else None,
            )
            for annotation_set in annotation_sets
        }
        protocol_ids = {annotation_set.protocol_id for annotation_set in annotation_sets}
        mapping_profiles = db.scalars(
            select(ResearchPhaseLabelMappingProfile)
            .where(ResearchPhaseLabelMappingProfile.protocol_id.in_(protocol_ids))
            .where(ResearchPhaseLabelMappingProfile.status == "published")
            .order_by(ResearchPhaseLabelMappingProfile.created_at.desc(), ResearchPhaseLabelMappingProfile.id.desc())
        ).all() if protocol_ids else []
        mapping_profiles_by_protocol: dict[int, list[ResearchPhaseLabelMappingProfile]] = defaultdict(list)
        for profile in mapping_profiles:
            mapping_profiles_by_protocol[profile.protocol_id].append(profile)
        return cls(
            videos_by_id=videos_by_id,
            sources_by_id={source.id: source for source in sources},
            derivatives_by_source=derivatives_by_source,
            annotation_sets_by_video=annotation_sets_by_video,
            segments_by_set=segments_by_set,
            metrics_by_set=metrics_by_set,
            mapping_profiles_by_protocol=mapping_profiles_by_protocol,
        )


def _build_checklist_item(video: ResearchVideo, context: _ChecklistContext) -> ResearchVideoChecklistItemRead:
    return ResearchVideoChecklistItemRead(
        video=ResearchVideoChecklistVideoRead(
            id=video.id,
            display_name=video.name,
            status=video.status,
            duration_ms=video.duration_ms,
            fps=video.fps,
            frame_count=video.frame_count,
            width=video.width,
            height=video.height,
            created_at=video.created_at,
            thumbnail_url=f"/api/research/videos/{video.id}/thumbnail" if video.thumbnail_path else None,
            hidden_from_video_list=video.hidden_from_video_list,
            hidden_at=video.hidden_at,
            hidden_reason=video.hidden_reason,
            notes=video.notes,
        ),
        trim=_build_trim_summary(video, context),
        phase=_build_phase_summary(video, context),
    )


def _build_trim_summary(video: ResearchVideo, context: _ChecklistContext) -> ResearchVideoChecklistTrimRead:
    source = context.sources_by_id.get(video.source_video_id) if video.source_video_id is not None else None
    derivatives = context.derivatives_by_source.get(video.id, [])
    kept_frame_count = (
        video.trim_end_frame_exclusive - video.trim_start_frame
        if video.trim_start_frame is not None and video.trim_end_frame_exclusive is not None
        else None
    )
    trim_start_time_ms = _frame_time_ms(video.trim_start_frame, source.fps if source else video.fps) if video.trim_start_frame is not None else None
    trim_end_time_ms = _frame_time_ms(video.trim_end_frame_exclusive, source.fps if source else video.fps) if video.trim_end_frame_exclusive is not None else None
    return ResearchVideoChecklistTrimRead(
        origin_type=video.origin_type,
        is_trimmed=video.origin_type == "trimmed",
        source_video_id=video.source_video_id,
        source_video_display_name=source.name if source is not None else None,
        trim_start_frame=video.trim_start_frame,
        trim_end_frame_exclusive=video.trim_end_frame_exclusive,
        trim_start_time_ms=trim_start_time_ms,
        trim_end_time_ms=trim_end_time_ms,
        kept_frame_count=kept_frame_count,
        kept_duration_ms=video.duration_ms if video.origin_type == "trimmed" else None,
        derived_video_count=len(derivatives),
        derived_video_ids=[derivative.id for derivative in derivatives],
        latest_derived_at=max((derivative.created_at for derivative in derivatives), default=None),
        derived_videos=[
            ResearchVideoChecklistDerivedVideoRead(
                video_id=derivative.id,
                display_name=derivative.name,
                trim_start_frame=derivative.trim_start_frame,
                trim_end_frame_exclusive=derivative.trim_end_frame_exclusive,
                created_at=derivative.created_at,
            )
            for derivative in derivatives
        ],
    )


def _build_phase_summary(video: ResearchVideo, context: _ChecklistContext) -> ResearchVideoChecklistPhaseRead:
    annotation_sets = context.annotation_sets_by_video.get(video.id, [])
    set_reads = [_annotation_set_to_read(annotation_set, context) for annotation_set in annotation_sets]
    latest = annotation_sets[0] if annotation_sets else None
    latest_metrics = context.metrics_by_set.get(latest.id) if latest is not None else None
    return ResearchVideoChecklistPhaseRead(
        annotation_set_count=len(annotation_sets),
        draft_count=sum(1 for item in annotation_sets if item.status == "draft"),
        submitted_count=sum(1 for item in annotation_sets if item.status in {"submitted", "reviewed", "locked"}),
        latest_annotation_set_id=latest.id if latest is not None else None,
        latest_status=latest.status if latest is not None else None,
        latest_version=latest.revision if latest is not None else None,
        latest_protocol_id=latest.protocol_id if latest is not None else None,
        latest_protocol_name=latest.protocol.name if latest is not None and latest.protocol is not None else None,
        latest_segment_count=latest_metrics.segment_count if latest_metrics is not None else 0,
        latest_coverage_percent=latest_metrics.coverage_percent if latest_metrics is not None else 0.0,
        latest_error_count=latest_metrics.error_count if latest_metrics is not None else 0,
        latest_warning_count=latest_metrics.warning_count if latest_metrics is not None else 0,
        latest_updated_at=latest.updated_at if latest is not None else None,
        latest_submitted_at=latest.submitted_at if latest is not None else None,
        sets=set_reads,
    )


def _latest_submitted_annotation_set(
    annotation_sets: Iterable[ResearchVideoChecklistAnnotationSetRead],
) -> ResearchVideoChecklistAnnotationSetRead | None:
    submitted = [
        annotation_set for annotation_set in annotation_sets
        if annotation_set.status == "submitted"
    ]
    if not submitted:
        return None
    return sorted(
        submitted,
        key=lambda item: (
            item.submitted_at or datetime.min.replace(tzinfo=timezone.utc),
            item.version,
            item.annotation_set_id,
        ),
        reverse=True,
    )[0]


def _latest_draft_annotation_set(
    annotation_sets: Iterable[ResearchVideoChecklistAnnotationSetRead],
) -> ResearchVideoChecklistAnnotationSetRead | None:
    drafts = [annotation_set for annotation_set in annotation_sets if annotation_set.status == "draft"]
    if not drafts:
        return None
    return sorted(
        drafts,
        key=lambda item: (
            item.updated_at,
            item.version,
            item.annotation_set_id,
        ),
        reverse=True,
    )[0]


def _annotation_set_to_read(annotation_set: ResearchPhaseAnnotationSet, context: _ChecklistContext) -> ResearchVideoChecklistAnnotationSetRead:
    metrics = context.metrics_by_set.get(annotation_set.id, _PhaseMetrics(0, 0.0, 0, 0))
    return ResearchVideoChecklistAnnotationSetRead(
        annotation_set_id=annotation_set.id,
        status=annotation_set.status,
        version=annotation_set.revision,
        protocol_id=annotation_set.protocol_id,
        protocol_name=annotation_set.protocol.name if annotation_set.protocol is not None else "",
        segment_count=metrics.segment_count,
        coverage_percent=metrics.coverage_percent,
        error_count=metrics.error_count,
        warning_count=metrics.warning_count,
        updated_at=annotation_set.updated_at,
        submitted_at=annotation_set.submitted_at,
        available_mapping_profiles=[
            ResearchVideoChecklistMappingProfileRead(
                id=profile.id,
                name=profile.name,
                version=profile.version,
                status=profile.status,
                key=profile_key(profile),
            )
            for profile in context.mapping_profiles_by_protocol.get(annotation_set.protocol_id, [])
        ],
    )


def _calculate_phase_metrics(segments: list[ResearchPhaseSegment], *, frame_count: int, fps: float | None) -> _PhaseMetrics:
    error_count = 0
    warning_count = 0
    ordered = sorted(segments, key=lambda item: (item.start_frame, item.id))
    if frame_count <= 0 and ordered:
        error_count += 1
    seen_starts: set[int] = set()
    intervals: list[tuple[int, int, int, int]] = []
    for segment in ordered:
        end_frame = segment.end_frame_exclusive
        if segment.start_frame in seen_starts:
            error_count += 1
        seen_starts.add(segment.start_frame)
        if end_frame is None:
            error_count += 1
            continue
        if segment.start_frame < 0 or segment.start_frame >= frame_count or end_frame > frame_count or end_frame <= segment.start_frame:
            error_count += 1
        clipped_start = max(0, min(segment.start_frame, frame_count))
        clipped_end = max(0, min(end_frame, frame_count))
        if clipped_end > clipped_start:
            intervals.append((clipped_start, clipped_end, segment.id, segment.phase_label_id))
    for left, right in zip(intervals, intervals[1:]):
        if right[0] < left[1]:
            error_count += 1
        if right[0] > left[1]:
            warning_count += 1
        if right[0] == left[1] and right[3] == left[3]:
            warning_count += 1
    if intervals:
        if intervals[0][0] > 0:
            warning_count += 1
        if intervals[-1][1] < frame_count:
            warning_count += 1
    warning_count += sum(1 for start, end, _id, _label_id in intervals if (end - start) < _short_segment_threshold(fps))
    return _PhaseMetrics(
        segment_count=len(segments),
        coverage_percent=_coverage_percent(intervals, frame_count),
        error_count=error_count,
        warning_count=warning_count,
    )


def _coverage_percent(intervals: list[tuple[int, int, int, int]], frame_count: int) -> float:
    if frame_count <= 0 or not intervals:
        return 0.0
    ordered = sorted((start, end) for start, end, _id, _label_id in intervals)
    covered = 0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
            continue
        covered += current_end - current_start
        current_start, current_end = start, end
    covered += current_end - current_start
    return round(max(0.0, min((covered / frame_count) * 100, 100.0)), 2)


def _short_segment_threshold(fps: float | None) -> int:
    if fps is None or fps <= 0:
        return 3
    return max(3, round(fps * 0.1))


def _frame_time_ms(frame: int | None, fps: float | None) -> int | None:
    if frame is None or fps is None or fps <= 0:
        return None
    return round(frame / fps * 1000)


def _matches_trim_status(item: ResearchVideoChecklistItemRead, trim_status: str) -> bool:
    if trim_status in {"", "all"}:
        return True
    if trim_status == "untrimmed":
        return not item.trim.is_trimmed and item.trim.derived_video_count == 0
    if trim_status == "has_derivatives":
        return not item.trim.is_trimmed and item.trim.derived_video_count > 0
    if trim_status == "trimmed":
        return item.trim.is_trimmed and item.trim.derived_video_count == 0
    if trim_status == "trimmed_with_derivatives":
        return item.trim.is_trimmed and item.trim.derived_video_count > 0
    return True


def _matches_phase_status(item: ResearchVideoChecklistItemRead, phase_status: str) -> bool:
    if phase_status in {"", "all"}:
        return True
    phase = item.phase
    has_draft = phase.draft_count > 0
    has_submitted = phase.submitted_count > 0
    if phase_status == "not_started":
        return phase.annotation_set_count == 0
    if phase_status == "draft":
        return has_draft and not has_submitted
    if phase_status == "submitted":
        return has_submitted and not has_draft
    if phase_status == "draft_and_submitted":
        return has_draft and has_submitted
    if phase_status == "has_errors":
        return phase.latest_error_count > 0
    if phase_status == "has_warnings":
        return phase.latest_warning_count > 0
    return True


def _matches_protocol(item: ResearchVideoChecklistItemRead, protocol_id: int | None) -> bool:
    if protocol_id is None:
        return True
    return any(annotation_set.protocol_id == protocol_id for annotation_set in item.phase.sets)


def _matches_visibility(item: ResearchVideoChecklistItemRead, visibility: str) -> bool:
    if visibility in {"", "all"}:
        return True
    if visibility == "visible":
        return not item.video.hidden_from_video_list
    if visibility == "hidden":
        return item.video.hidden_from_video_list
    return True


def _sort_items(items: list[ResearchVideoChecklistItemRead], *, sort_by: str, sort_order: str) -> list[ResearchVideoChecklistItemRead]:
    reverse = sort_order.lower() != "asc"
    key_map = {
        "created_at": lambda item: item.video.created_at,
        "name": lambda item: item.video.display_name.lower(),
        "phase_updated_at": lambda item: item.phase.latest_updated_at or datetime.min.replace(tzinfo=timezone.utc),
        "frame_count": lambda item: item.video.frame_count,
    }
    key = key_map.get(sort_by, key_map["created_at"])
    return sorted(items, key=key, reverse=reverse)


def _build_stats(items: list[ResearchVideoChecklistItemRead]) -> ResearchVideoChecklistStatsRead:
    return ResearchVideoChecklistStatsRead(
        total_videos=len(items),
        trimmed_videos=sum(1 for item in items if item.trim.is_trimmed),
        source_with_derivatives=sum(1 for item in items if item.trim.derived_video_count > 0),
        phase_submitted=sum(1 for item in items if item.phase.submitted_count > 0),
        phase_not_started=sum(1 for item in items if item.phase.annotation_set_count == 0),
    )


@dataclass(frozen=True)
class _BatchValidation:
    invalid_items: list[ResearchVideoBatchExportInvalidItemRead]
    warnings: list[str]


def _validate_batch_export_request(db: Session, payload: ResearchVideoBatchExportRequest) -> _BatchValidation:
    invalid: list[ResearchVideoBatchExportInvalidItemRead] = []
    warnings: list[str] = []
    if not payload.items:
        invalid.append(ResearchVideoBatchExportInvalidItemRead(message="Select at least one export item."))
        return _BatchValidation(invalid, warnings)
    selected_video_ids = [item.video_id for item in payload.items if item.include_trim_info or item.phase_exports]
    if not selected_video_ids:
        invalid.append(ResearchVideoBatchExportInvalidItemRead(message="Select at least one export item."))
    if len(set(selected_video_ids)) > MAX_BATCH_EXPORT_VIDEOS:
        invalid.append(ResearchVideoBatchExportInvalidItemRead(message=f"Batch export supports at most {MAX_BATCH_EXPORT_VIDEOS} videos."))
    phase_export_count = sum(len(item.phase_exports) for item in payload.items)
    if phase_export_count > MAX_BATCH_PHASE_EXPORTS:
        invalid.append(ResearchVideoBatchExportInvalidItemRead(message=f"Batch export supports at most {MAX_BATCH_PHASE_EXPORTS} phase exports."))

    videos_by_id = {video.id: video for video in db.scalars(select(ResearchVideo).where(ResearchVideo.id.in_(set(selected_video_ids)))).all()} if selected_video_ids else {}
    annotation_set_ids = {spec.annotation_set_id for item in payload.items for spec in item.phase_exports}
    annotation_sets = db.scalars(
        select(ResearchPhaseAnnotationSet)
        .where(ResearchPhaseAnnotationSet.id.in_(annotation_set_ids))
        .options(selectinload(ResearchPhaseAnnotationSet.protocol))
    ).all() if annotation_set_ids else []
    annotation_sets_by_id = {annotation_set.id: annotation_set for annotation_set in annotation_sets}
    profile_ids = {spec.mapping_profile_id for item in payload.items for spec in item.phase_exports if spec.mapping_profile_id is not None}
    profiles_by_id = {profile.id: profile for profile in db.scalars(select(ResearchPhaseLabelMappingProfile).where(ResearchPhaseLabelMappingProfile.id.in_(profile_ids))).all()} if profile_ids else {}
    seen_phase_specs: set[tuple[int, int, int | None]] = set()
    for item in payload.items:
        if not item.include_trim_info and not item.phase_exports:
            invalid.append(ResearchVideoBatchExportInvalidItemRead(video_id=item.video_id, message="Video item has no selected export content."))
            continue
        if item.video_id not in videos_by_id:
            invalid.append(ResearchVideoBatchExportInvalidItemRead(video_id=item.video_id, message="Research video not found."))
            continue
        for spec in item.phase_exports:
            key = (item.video_id, spec.annotation_set_id, spec.mapping_profile_id)
            if key in seen_phase_specs:
                invalid.append(ResearchVideoBatchExportInvalidItemRead(video_id=item.video_id, annotation_set_id=spec.annotation_set_id, mapping_profile_id=spec.mapping_profile_id, message="Duplicate phase export selection."))
                continue
            seen_phase_specs.add(key)
            annotation_set = annotation_sets_by_id.get(spec.annotation_set_id)
            if annotation_set is None:
                invalid.append(ResearchVideoBatchExportInvalidItemRead(video_id=item.video_id, annotation_set_id=spec.annotation_set_id, message="Phase annotation set not found."))
                continue
            if annotation_set.video_id != item.video_id:
                invalid.append(ResearchVideoBatchExportInvalidItemRead(video_id=item.video_id, annotation_set_id=spec.annotation_set_id, message="Phase annotation set does not belong to this video."))
            if annotation_set.status == "draft":
                warnings.append(f"Annotation set {annotation_set.id} is a draft.")
            if spec.mapping_profile_id is None:
                continue
            profile = profiles_by_id.get(spec.mapping_profile_id)
            if profile is None:
                invalid.append(ResearchVideoBatchExportInvalidItemRead(video_id=item.video_id, annotation_set_id=spec.annotation_set_id, mapping_profile_id=spec.mapping_profile_id, message="Mapping profile not found."))
                continue
            if profile.status != "published":
                invalid.append(ResearchVideoBatchExportInvalidItemRead(video_id=item.video_id, annotation_set_id=spec.annotation_set_id, mapping_profile_id=profile.id, message="Only published mapping profiles can be exported."))
            if profile.protocol_id != annotation_set.protocol_id:
                invalid.append(ResearchVideoBatchExportInvalidItemRead(video_id=item.video_id, annotation_set_id=spec.annotation_set_id, mapping_profile_id=profile.id, message="Mapping profile does not belong to the annotation set protocol."))
    return _BatchValidation(invalid, warnings)


def _build_batch_manifest(payload: ResearchVideoBatchExportRequest, preview: ResearchVideoBatchExportPreviewRead) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "batch_name": payload.batch_name,
        "application_export_type": "research_video_batch_export",
        "video_count": preview.video_count,
        "trim_export_count": preview.trim_export_count,
        "phase_export_count": preview.phase_export_count,
        "archive_entries": [],
        "selection": [item.model_dump() for item in payload.items],
        "warnings": preview.warnings,
        "videos": [],
    }


def _build_trim_export_payload(item: ResearchVideoChecklistItemRead) -> dict[str, Any]:
    trim = item.trim
    return {
        "schema_version": "1.0",
        "frame_interval_semantics": "[start_frame, end_frame_exclusive)",
        "video": {
            "id": item.video.id,
            "display_name": item.video.display_name,
            "origin_type": trim.origin_type,
            "frame_count": item.video.frame_count,
            "fps": item.video.fps,
            "duration_ms": item.video.duration_ms,
        },
        "trim": {
            "is_trimmed": trim.is_trimmed,
            "source_video_id": trim.source_video_id,
            "source_video_display_name": trim.source_video_display_name,
            "start_frame": trim.trim_start_frame,
            "end_frame_exclusive": trim.trim_end_frame_exclusive,
            "ui_start_frame": trim.trim_start_frame + 1 if trim.trim_start_frame is not None else None,
            "ui_end_frame_inclusive": trim.trim_end_frame_exclusive if trim.trim_end_frame_exclusive is not None else None,
            "kept_frame_count": trim.kept_frame_count,
            "kept_duration_ms": trim.kept_duration_ms,
        },
        "derived_videos": [derived.model_dump(mode="json") for derived in trim.derived_videos],
    }


def _video_export_directory(video: ResearchVideo) -> str:
    return f"videos/{sanitize_filename(video.name, fallback=f'research-video-{video.id}')}__video-{video.id}"


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _summary_csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    header = [
        "video_id",
        "video_name",
        "video_status",
        "origin_type",
        "is_trimmed",
        "source_video_id",
        "trim_start_frame",
        "trim_end_frame_exclusive",
        "derived_video_count",
        "phase_annotation_set_count",
        "phase_draft_count",
        "phase_submitted_count",
        "latest_phase_status",
        "latest_phase_version",
        "latest_phase_protocol",
        "latest_phase_segment_count",
        "latest_phase_coverage_percent",
        "latest_phase_error_count",
        "latest_phase_warning_count",
        "exported_trim_info",
        "exported_phase_count",
    ]
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.DictWriter(buffer, fieldnames=header, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_safe_cell(row.get(key)) for key in header})
    return buffer.getvalue().encode("utf-8")


def _summary_row(item: ResearchVideoChecklistItemRead, export_item: ResearchVideoBatchExportItemRequest) -> dict[str, Any]:
    return {
        "video_id": item.video.id,
        "video_name": item.video.display_name,
        "video_status": item.video.status,
        "origin_type": item.trim.origin_type,
        "is_trimmed": item.trim.is_trimmed,
        "source_video_id": item.trim.source_video_id,
        "trim_start_frame": item.trim.trim_start_frame,
        "trim_end_frame_exclusive": item.trim.trim_end_frame_exclusive,
        "derived_video_count": item.trim.derived_video_count,
        "phase_annotation_set_count": item.phase.annotation_set_count,
        "phase_draft_count": item.phase.draft_count,
        "phase_submitted_count": item.phase.submitted_count,
        "latest_phase_status": item.phase.latest_status,
        "latest_phase_version": item.phase.latest_version,
        "latest_phase_protocol": item.phase.latest_protocol_name,
        "latest_phase_segment_count": item.phase.latest_segment_count,
        "latest_phase_coverage_percent": item.phase.latest_coverage_percent,
        "latest_phase_error_count": item.phase.latest_error_count,
        "latest_phase_warning_count": item.phase.latest_warning_count,
        "exported_trim_info": export_item.include_trim_info,
        "exported_phase_count": len(export_item.phase_exports),
    }


def _csv_safe_cell(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"}:
        return f"'{value}"
    return value


def _build_batch_zip_filename(batch_name: str | None) -> str:
    if batch_name and batch_name.strip():
        return f"{sanitize_filename(batch_name, fallback='research-video-export')}.zip"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"research-video-export_{timestamp}.zip"
