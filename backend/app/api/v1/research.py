from __future__ import annotations

import mimetypes
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.db.session import get_db
from app.models import User
from app.models.research import (
    ResearchVideo,
    ResearchVideoAnnotation,
    ResearchVideoFrame,
    ResearchVideoLabel,
)
from app.schemas.research import (
    ResearchVideoAnnotationRead,
    ResearchVideoAnnotationSaveRequest,
    ResearchVideoBatchExportPreviewRead,
    ResearchVideoBatchExportRequest,
    ResearchVideoChecklistPageRead,
    ResearchVideoChecklistDefaultPhaseSelectionRead,
    ResearchVideoDetailRead,
    ResearchVideoFrameAnnotationsRead,
    ResearchVideoFrameRead,
    ResearchVideoFramesPageRead,
    ResearchVideoLabelPayload,
    ResearchVideoLabelRead,
    ResearchVideoRead,
    ResearchVideoTrimInfoRead,
    ResearchVideoTrimLinkedDataRead,
    ResearchVideoTrimRequest,
    ResearchVideoTrimResponse,
    ResearchVideoUploadResponse,
    ResearchVideoNotesRequest,
    ResearchVideoNotesResponse,
    ResearchVideoPhaseSummaryRead,
    ResearchVideoVisibility,
    ResearchVideoVisibilityBulkPreviewRead,
    ResearchVideoVisibilityBulkResultRead,
    ResearchVideoVisibilityRequest,
    ResearchVideoVisibilityResponse,
    ResearchVideoWorkspaceRead,
)
from app.api.v1 import research_phases, research_skills
from app.services.range_file_response import create_range_file_response
from app.services.research_video_trim import (
    ResearchVideoTrimConflictError,
    ResearchVideoTrimError,
    get_linked_video_data,
    minimum_keep_frames,
    trim_research_video,
)
from app.services.research_video_visibility import (
    MANUAL_HIDDEN_REASON,
    hide_research_video_from_list,
    restore_research_video_to_list,
)
from app.services.research_video_checklist import (
    build_video_batch_export,
    hide_trimmed_source_videos,
    list_default_phase_export_selections,
    list_research_video_phase_summaries,
    list_video_operation_checklist,
    preview_hide_trimmed_source_videos,
    preview_restore_trimmed_source_videos,
    preview_video_batch_export,
    remove_batch_export_file,
    restore_trimmed_source_videos,
)
from app.services.video_import import InvalidVideoError, import_managed_research_video, save_uploaded_video

router = APIRouter()
router.include_router(research_phases.router)
router.include_router(research_skills.router)


@router.get("/videos", response_model=list[ResearchVideoRead])
def list_research_videos(
    visibility: ResearchVideoVisibility = Query(default="visible"),
    db: Session = Depends(get_db),
) -> list[ResearchVideoRead]:
    statement = select(ResearchVideo)
    if visibility == "visible":
        statement = statement.where(ResearchVideo.hidden_from_video_list.is_(False))
    elif visibility == "hidden":
        statement = statement.where(ResearchVideo.hidden_from_video_list.is_(True))
    videos = db.scalars(
        statement.order_by(ResearchVideo.created_at.desc(), ResearchVideo.id.desc())
    ).all()
    phase_summaries = list_research_video_phase_summaries(db, [video.id for video in videos])
    return [_research_video_to_read(video, phase_summaries.get(video.id)) for video in videos]


@router.get("/video-operation-checklist", response_model=ResearchVideoChecklistPageRead)
def get_research_video_operation_checklist(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    search: str | None = Query(default=None),
    video_status: str | None = Query(default=None),
    trim_status: str = Query(default="all"),
    phase_status: str = Query(default="all"),
    protocol_id: int | None = Query(default=None),
    visibility: str = Query(default="all"),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc"),
    db: Session = Depends(get_db),
) -> ResearchVideoChecklistPageRead:
    return list_video_operation_checklist(
        db,
        page=page,
        page_size=page_size,
        search=search,
        video_status=video_status,
        trim_status=trim_status,
        phase_status=phase_status,
        protocol_id=protocol_id,
        visibility=visibility,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get(
    "/video-operation-checklist/default-phase-selections",
    response_model=list[ResearchVideoChecklistDefaultPhaseSelectionRead],
)
def get_research_video_operation_checklist_default_phase_selections(
    search: str | None = Query(default=None),
    video_status: str | None = Query(default=None),
    trim_status: str = Query(default="all"),
    phase_status: str = Query(default="all"),
    protocol_id: int | None = Query(default=None),
    visibility: str = Query(default="all"),
    db: Session = Depends(get_db),
) -> list[ResearchVideoChecklistDefaultPhaseSelectionRead]:
    return list_default_phase_export_selections(
        db,
        search=search,
        video_status=video_status,
        trim_status=trim_status,
        phase_status=phase_status,
        protocol_id=protocol_id,
        visibility=visibility,
    )


@router.post(
    "/videos/visibility/hide-trimmed-sources/preview",
    response_model=ResearchVideoVisibilityBulkPreviewRead,
)
def preview_hide_research_video_trimmed_sources(
    db: Session = Depends(get_db),
) -> ResearchVideoVisibilityBulkPreviewRead:
    return preview_hide_trimmed_source_videos(db)


@router.post(
    "/videos/visibility/hide-trimmed-sources",
    response_model=ResearchVideoVisibilityBulkResultRead,
)
def hide_research_video_trimmed_sources(
    db: Session = Depends(get_db),
) -> ResearchVideoVisibilityBulkResultRead:
    return hide_trimmed_source_videos(db)


@router.post(
    "/videos/visibility/restore-trimmed-sources/preview",
    response_model=ResearchVideoVisibilityBulkPreviewRead,
)
def preview_restore_research_video_trimmed_sources(
    db: Session = Depends(get_db),
) -> ResearchVideoVisibilityBulkPreviewRead:
    return preview_restore_trimmed_source_videos(db)


@router.post(
    "/videos/visibility/restore-trimmed-sources",
    response_model=ResearchVideoVisibilityBulkResultRead,
)
def restore_research_video_trimmed_sources(
    db: Session = Depends(get_db),
) -> ResearchVideoVisibilityBulkResultRead:
    return restore_trimmed_source_videos(db)


@router.post("/video-batch-export/preview", response_model=ResearchVideoBatchExportPreviewRead)
def preview_research_video_batch_export(
    payload: ResearchVideoBatchExportRequest,
    db: Session = Depends(get_db),
) -> ResearchVideoBatchExportPreviewRead:
    return preview_video_batch_export(db, payload)


@router.post("/video-batch-export")
def export_research_video_batch(
    payload: ResearchVideoBatchExportRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> FileResponse:
    export_file = build_video_batch_export(db, payload)
    background_tasks.add_task(remove_batch_export_file, export_file.path)
    return FileResponse(
        export_file.path,
        media_type=export_file.media_type,
        filename=export_file.filename,
        headers=export_file.headers,
        background=background_tasks,
    )


@router.post("/videos", response_model=ResearchVideoUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_research_video(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    username: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> ResearchVideoUploadResponse:
    storage_root = Path(settings.local_storage_root) / "research" / "videos"
    raw_root = storage_root / "raw"

    created_by_id: int | None = None
    if username:
        user = db.scalar(select(User).where(User.username == username.strip()))
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        created_by_id = user.id

    try:
        video_path, original_filename = save_uploaded_video(file, videos_root=raw_root)
        video, warnings = import_managed_research_video(
            db=db,
            video_path=video_path,
            original_filename=original_filename,
            display_name=name,
            created_by_id=created_by_id,
            storage_root=storage_root,
        )
    except InvalidVideoError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ResearchVideoUploadResponse(
        **_research_video_to_read(video).model_dump(),
        warnings=warnings,
    )


@router.get("/videos/{video_id}", response_model=ResearchVideoDetailRead)
def get_research_video(video_id: int, db: Session = Depends(get_db)) -> ResearchVideoDetailRead:
    video = _get_research_video_or_404(video_id, db)
    return _research_video_to_detail(video)


@router.patch("/videos/{video_id}/notes", response_model=ResearchVideoNotesResponse)
def update_research_video_notes(
    video_id: int,
    payload: ResearchVideoNotesRequest,
    db: Session = Depends(get_db),
) -> ResearchVideoNotesResponse:
    video = db.get(ResearchVideo, video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research video not found")
    video.notes = payload.notes
    video.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(video)
    return ResearchVideoNotesResponse(
        video_id=video.id,
        notes=video.notes,
        updated_at=video.updated_at.isoformat(),
    )


@router.patch("/videos/{video_id}/visibility", response_model=ResearchVideoVisibilityResponse)
def update_research_video_visibility(
    video_id: int,
    payload: ResearchVideoVisibilityRequest,
    db: Session = Depends(get_db),
) -> ResearchVideoVisibilityResponse:
    video = db.get(ResearchVideo, video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research video not found")
    if payload.hidden_from_video_list:
        hide_research_video_from_list(video, reason=MANUAL_HIDDEN_REASON, preserve_existing_reason=False)
    else:
        restore_research_video_to_list(video)
    db.commit()
    db.refresh(video)
    return ResearchVideoVisibilityResponse(
        video_id=video.id,
        hidden_from_video_list=video.hidden_from_video_list,
        hidden_at=video.hidden_at.isoformat() if video.hidden_at else None,
        hidden_reason=video.hidden_reason,
        updated_at=video.updated_at.isoformat(),
    )


@router.get("/videos/{video_id}/workspace", response_model=ResearchVideoWorkspaceRead)
def get_research_video_workspace(video_id: int, db: Session = Depends(get_db)) -> ResearchVideoWorkspaceRead:
    video = _get_research_video_workspace_or_404(video_id, db)
    return _research_video_to_workspace(video)


@router.get("/videos/{video_id}/trim-info", response_model=ResearchVideoTrimInfoRead)
def get_research_video_trim_info(video_id: int, db: Session = Depends(get_db)) -> ResearchVideoTrimInfoRead:
    video = _get_research_video_workspace_or_404(video_id, db)
    if video.status != "ready":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Only ready research videos can be trimmed.")
    linked_data = get_linked_video_data(db, video.id)
    return ResearchVideoTrimInfoRead(
        video=_research_video_to_workspace(video),
        linked_data=ResearchVideoTrimLinkedDataRead(
            frame_annotation_count=linked_data.frame_annotation_count,
            phase_annotation_set_count=linked_data.phase_annotation_set_count,
            phase_segment_count=linked_data.phase_segment_count,
            skill_assessment_count=linked_data.skill_assessment_count,
            skill_evidence_count=linked_data.skill_evidence_count,
        ),
        minimum_keep_frames=minimum_keep_frames(video),
    )


@router.post("/videos/{video_id}/trim", response_model=ResearchVideoTrimResponse, status_code=status.HTTP_201_CREATED)
def trim_research_video_endpoint(
    video_id: int,
    payload: ResearchVideoTrimRequest,
    db: Session = Depends(get_db),
) -> ResearchVideoTrimResponse:
    source_video = _get_research_video_workspace_or_404(video_id, db)
    storage_root = Path(settings.local_storage_root) / "research" / "videos"
    try:
        trimmed_video, warnings, source_video_hidden = trim_research_video(
            db=db,
            source_video=source_video,
            start_frame=payload.start_frame,
            end_frame_exclusive=payload.end_frame_exclusive,
            display_name=payload.display_name,
            acknowledge_annotations_not_copied=payload.acknowledge_annotations_not_copied,
            hide_source_after_success=payload.hide_source_after_success,
            storage_root=storage_root,
        )
    except ResearchVideoTrimConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ResearchVideoTrimError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except InvalidVideoError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ResearchVideoTrimResponse(
        source_video_id=source_video.id,
        trimmed_video_id=trimmed_video.id,
        status=trimmed_video.status,
        source_video_hidden=source_video_hidden,
        warnings=warnings,
    )


@router.get("/videos/{video_id}/frames", response_model=ResearchVideoFramesPageRead)
def list_research_video_frames(
    video_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> ResearchVideoFramesPageRead:
    video = _get_research_video_workspace_or_404(video_id, db)
    frames = db.scalars(
        select(ResearchVideoFrame)
        .where(ResearchVideoFrame.video_id == video_id)
        .order_by(ResearchVideoFrame.frame_index)
        .offset(offset)
        .limit(limit)
    ).all()
    total = video.frame_count
    return ResearchVideoFramesPageRead(
        items=[_research_frame_to_read(frame, video_id) for frame in frames],
        offset=offset,
        limit=limit,
        total=total,
        has_more=offset + len(frames) < total,
    )


@router.delete("/videos/{video_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_research_video(video_id: int, db: Session = Depends(get_db)) -> Response:
    video = db.get(ResearchVideo, video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research video not found")
    db.delete(video)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/videos/{video_id}/file")
def get_research_video_file(request: Request, video_id: int, db: Session = Depends(get_db)) -> Response:
    video = _get_research_video_or_404(video_id, db)
    file_path = _resolve_research_storage_path(video.file_path)
    media_type, _ = mimetypes.guess_type(video.original_filename or str(file_path))
    return create_range_file_response(
        request=request,
        file_path=file_path,
        media_type=media_type or "video/mp4",
        filename=video.original_filename,
    )


@router.head("/videos/{video_id}/file")
def head_research_video_file(request: Request, video_id: int, db: Session = Depends(get_db)) -> Response:
    video = _get_research_video_or_404(video_id, db)
    file_path = _resolve_research_storage_path(video.file_path)
    media_type, _ = mimetypes.guess_type(video.original_filename or str(file_path))
    return create_range_file_response(
        request=request,
        file_path=file_path,
        media_type=media_type or "video/mp4",
        filename=video.original_filename,
    )


@router.get("/videos/{video_id}/thumbnail")
def get_research_video_thumbnail(video_id: int, db: Session = Depends(get_db)) -> FileResponse:
    video = _get_research_video_or_404(video_id, db)
    if not video.thumbnail_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research video thumbnail not found")
    return _inline_file_response(video.thumbnail_path, default_media_type="image/jpeg")


@router.get("/videos/{video_id}/frames/{frame_index}/image")
def get_research_video_frame_image(video_id: int, frame_index: int, db: Session = Depends(get_db)) -> FileResponse:
    frame = _get_research_video_frame_or_404(video_id, frame_index, db)
    return _inline_file_response(frame.file_path, default_media_type="image/jpeg")


@router.get(
    "/videos/{video_id}/frames/{frame_index}/annotations",
    response_model=ResearchVideoFrameAnnotationsRead,
)
def get_research_video_frame_annotations(
    video_id: int,
    frame_index: int,
    db: Session = Depends(get_db),
) -> ResearchVideoFrameAnnotationsRead:
    frame = _get_research_video_frame_or_404(video_id, frame_index, db)
    annotations = db.scalars(
        select(ResearchVideoAnnotation)
        .where(ResearchVideoAnnotation.video_id == video_id, ResearchVideoAnnotation.frame_id == frame.id)
        .order_by(ResearchVideoAnnotation.z_order, ResearchVideoAnnotation.id)
    ).all()
    return ResearchVideoFrameAnnotationsRead(
        video_id=video_id,
        frame_index=frame_index,
        annotations=[ResearchVideoAnnotationRead.model_validate(annotation) for annotation in annotations],
    )


@router.put(
    "/videos/{video_id}/frames/{frame_index}/annotations",
    response_model=list[ResearchVideoAnnotationRead],
)
def save_research_video_frame_annotations(
    video_id: int,
    frame_index: int,
    payload: ResearchVideoAnnotationSaveRequest,
    db: Session = Depends(get_db),
) -> list[ResearchVideoAnnotationRead]:
    video = _get_research_video_or_404(video_id, db)
    frame = _get_research_video_frame_or_404(video_id, frame_index, db)
    label_ids = {label.id for label in video.labels}

    for annotation in payload.annotations:
        if annotation.label_id not in label_ids:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Label does not belong to this research video")

    db.execute(
        delete(ResearchVideoAnnotation).where(
            ResearchVideoAnnotation.video_id == video_id,
            ResearchVideoAnnotation.frame_id == frame.id,
        )
    )

    saved_annotations: list[ResearchVideoAnnotation] = []
    normalized_annotations = [
        annotation
        for _index, annotation in sorted(
            enumerate(payload.annotations),
            key=lambda item: (item[1].z_order, item[0]),
        )
    ]

    for index, annotation in enumerate(normalized_annotations):
        saved = ResearchVideoAnnotation(
            video_id=video_id,
            frame_id=frame.id,
            frame_index=frame_index,
            label_id=annotation.label_id,
            shape_type=annotation.shape_type,
            points=annotation.points,
            attributes=annotation.attributes,
            visible=annotation.visible,
            z_order=index,
        )
        db.add(saved)
        saved_annotations.append(saved)

    db.commit()
    for annotation in saved_annotations:
        db.refresh(annotation)
    return [ResearchVideoAnnotationRead.model_validate(annotation) for annotation in saved_annotations]


@router.get("/videos/{video_id}/labels", response_model=list[ResearchVideoLabelRead])
def list_research_video_labels(video_id: int, db: Session = Depends(get_db)) -> list[ResearchVideoLabelRead]:
    video = _get_research_video_or_404(video_id, db)
    return [_research_label_to_read(label, db) for label in video.labels]


@router.post("/videos/{video_id}/labels", response_model=ResearchVideoLabelRead, status_code=status.HTTP_201_CREATED)
def create_research_video_label(
    video_id: int,
    payload: ResearchVideoLabelPayload,
    db: Session = Depends(get_db),
) -> ResearchVideoLabelRead:
    video = _get_research_video_or_404(video_id, db)
    _validate_unique_research_label_name(payload.name, video.labels)
    sort_order = max((label.sort_order for label in video.labels), default=-1) + 1
    label = ResearchVideoLabel(
        video_id=video.id,
        name=payload.name,
        color=payload.color,
        shape_type=payload.shape_type,
        sort_order=sort_order,
    )
    db.add(label)
    db.commit()
    db.refresh(label)
    return _research_label_to_read(label, db)


@router.put("/videos/{video_id}/labels/{label_id}", response_model=ResearchVideoLabelRead)
def update_research_video_label(
    video_id: int,
    label_id: int,
    payload: ResearchVideoLabelPayload,
    db: Session = Depends(get_db),
) -> ResearchVideoLabelRead:
    video = _get_research_video_or_404(video_id, db)
    label = _get_research_video_label_or_404(video, label_id)
    _validate_unique_research_label_name(payload.name, video.labels, exclude_label_id=label.id)
    label.name = payload.name
    label.color = payload.color
    label.shape_type = payload.shape_type
    db.commit()
    db.refresh(label)
    return _research_label_to_read(label, db)


@router.delete("/videos/{video_id}/labels/{label_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_research_video_label(video_id: int, label_id: int, db: Session = Depends(get_db)) -> Response:
    video = _get_research_video_or_404(video_id, db)
    label = _get_research_video_label_or_404(video, label_id)
    annotation_count = db.scalar(
        select(func.count(ResearchVideoAnnotation.id)).where(ResearchVideoAnnotation.label_id == label.id)
    ) or 0
    if annotation_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Delete annotations using this label before removing the label.",
        )
    db.delete(label)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _get_research_video_or_404(video_id: int, db: Session) -> ResearchVideo:
    video = db.scalar(
        select(ResearchVideo)
        .where(ResearchVideo.id == video_id)
        .options(
            selectinload(ResearchVideo.frames),
            selectinload(ResearchVideo.labels),
        )
    )
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research video not found")
    return video


def _get_research_video_workspace_or_404(video_id: int, db: Session) -> ResearchVideo:
    video = db.scalar(
        select(ResearchVideo)
        .where(ResearchVideo.id == video_id)
        .options(selectinload(ResearchVideo.labels))
    )
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research video not found")
    return video


def _get_research_video_frame_or_404(video_id: int, frame_index: int, db: Session) -> ResearchVideoFrame:
    frame = db.scalar(
        select(ResearchVideoFrame).where(
            ResearchVideoFrame.video_id == video_id,
            ResearchVideoFrame.frame_index == frame_index,
        )
    )
    if frame is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research video frame not found")
    return frame


def _get_research_video_label_or_404(video: ResearchVideo, label_id: int) -> ResearchVideoLabel:
    label = next((item for item in video.labels if item.id == label_id), None)
    if label is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research video label not found")
    return label


def _research_video_to_read(
    video: ResearchVideo,
    phase_summary: ResearchVideoPhaseSummaryRead | None = None,
) -> ResearchVideoRead:
    return ResearchVideoRead(
        id=video.id,
        name=video.name,
        original_filename=video.original_filename,
        width=video.width,
        height=video.height,
        fps=video.fps,
        frame_count=video.frame_count,
        duration_ms=video.duration_ms,
        status=video.status,
        source_video_id=video.source_video_id,
        origin_type=video.origin_type,
        trim_start_frame=video.trim_start_frame,
        trim_end_frame_exclusive=video.trim_end_frame_exclusive,
        hidden_from_video_list=video.hidden_from_video_list,
        hidden_at=video.hidden_at.isoformat() if video.hidden_at else None,
        hidden_reason=video.hidden_reason,
        notes=video.notes,
        phase_summary=phase_summary or ResearchVideoPhaseSummaryRead(),
        thumbnail_url=f"/api/research/videos/{video.id}/thumbnail" if video.thumbnail_path else None,
        created_at=video.created_at.isoformat(),
        updated_at=video.updated_at.isoformat(),
    )


def _research_video_to_detail(video: ResearchVideo) -> ResearchVideoDetailRead:
    return ResearchVideoDetailRead(
        **_research_video_to_read(video).model_dump(),
        file_url=f"/api/research/videos/{video.id}/file",
        frames=[
            _research_frame_to_read(frame, video.id)
            for frame in video.frames
        ],
        labels=[_research_label_to_read(label, None) for label in video.labels],
    )


def _research_video_to_workspace(video: ResearchVideo) -> ResearchVideoWorkspaceRead:
    return ResearchVideoWorkspaceRead(
        **_research_video_to_read(video).model_dump(),
        file_url=f"/api/research/videos/{video.id}/file",
        labels=[_research_label_to_read(label, None) for label in video.labels],
    )


def _research_frame_to_read(frame: ResearchVideoFrame, video_id: int) -> ResearchVideoFrameRead:
    return ResearchVideoFrameRead(
        id=frame.id,
        frame_index=frame.frame_index,
        timestamp_ms=frame.timestamp_ms,
        filename=frame.filename,
        width=frame.width,
        height=frame.height,
        image_url=f"/api/research/videos/{video_id}/frames/{frame.frame_index}/image",
    )


def _research_label_to_read(label: ResearchVideoLabel, db: Session | None) -> ResearchVideoLabelRead:
    annotation_count = 0
    if db is not None:
        annotation_count = db.scalar(
            select(func.count(ResearchVideoAnnotation.id)).where(ResearchVideoAnnotation.label_id == label.id)
        ) or 0
    return ResearchVideoLabelRead(
        id=label.id,
        name=label.name,
        color=label.color,
        shape_type=label.shape_type,
        sort_order=label.sort_order,
        annotation_count=annotation_count,
    )


def _validate_unique_research_label_name(
    name: str,
    labels: list[ResearchVideoLabel],
    *,
    exclude_label_id: int | None = None,
) -> None:
    normalized = name.strip().lower()
    for label in labels:
        if exclude_label_id is not None and label.id == exclude_label_id:
            continue
        if label.name.strip().lower() == normalized:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Label name already exists")


def _inline_file_response(path: str, *, default_media_type: str) -> FileResponse:
    file_path = _resolve_research_storage_path(path)
    if not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    media_type, _ = mimetypes.guess_type(str(file_path))
    return FileResponse(
        file_path,
        media_type=media_type or default_media_type,
        headers={"Content-Disposition": "inline"},
    )


def _resolve_research_storage_path(path: str) -> Path:
    file_path = Path(path).expanduser()
    resolved = file_path.resolve(strict=False)
    allowed_root = (Path(settings.local_storage_root) / "research" / "videos").resolve(strict=False)

    try:
        resolved.relative_to(allowed_root)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found") from exc

    return resolved
