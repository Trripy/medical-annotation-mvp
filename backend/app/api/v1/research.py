from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
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
    ResearchVideoDetailRead,
    ResearchVideoFrameAnnotationsRead,
    ResearchVideoFrameRead,
    ResearchVideoFramesPageRead,
    ResearchVideoLabelPayload,
    ResearchVideoLabelRead,
    ResearchVideoRead,
    ResearchVideoUploadResponse,
    ResearchVideoWorkspaceRead,
)
from app.api.v1 import research_phases, research_skills
from app.services.range_file_response import create_range_file_response
from app.services.video_import import InvalidVideoError, extract_video_frames, save_uploaded_video

router = APIRouter()
router.include_router(research_phases.router)
router.include_router(research_skills.router)


@router.get("/videos", response_model=list[ResearchVideoRead])
def list_research_videos(db: Session = Depends(get_db)) -> list[ResearchVideoRead]:
    videos = db.scalars(
        select(ResearchVideo)
        .order_by(ResearchVideo.created_at.desc(), ResearchVideo.id.desc())
    ).all()
    return [_research_video_to_read(video) for video in videos]


@router.post("/videos", response_model=ResearchVideoUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_research_video(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    username: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> ResearchVideoUploadResponse:
    storage_root = Path(settings.local_storage_root) / "research" / "videos"
    raw_root = storage_root / "raw"
    thumbnails_root = storage_root / "thumbnails"

    created_by_id: int | None = None
    if username:
        user = db.scalar(select(User).where(User.username == username.strip()))
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        created_by_id = user.id

    video_path, original_filename = save_uploaded_video(file, videos_root=raw_root)
    video = ResearchVideo(
        name=(name or original_filename).strip() or original_filename,
        original_filename=original_filename,
        file_path=video_path,
        status="processing",
        created_by_id=created_by_id,
    )
    db.add(video)
    db.flush()

    video_frames_root = storage_root / str(video.id) / "frames"
    thumbnail_path = thumbnails_root / f"{video.id}.jpg"

    try:
        metadata = extract_video_frames(video_path, video_frames_root, thumbnail_path=thumbnail_path)
    except InvalidVideoError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    video.thumbnail_path = str(thumbnail_path)
    video.width = metadata["width"]
    video.height = metadata["height"]
    video.fps = metadata["fps"]
    video.frame_count = metadata["frame_count"]
    video.duration_ms = metadata["duration_ms"]
    video.status = "ready"
    video.frames = [
        ResearchVideoFrame(
            frame_index=frame["frame_index"],
            timestamp_ms=frame["timestamp_ms"],
            filename=frame["filename"],
            file_path=frame["file_path"],
            width=frame["width"],
            height=frame["height"],
        )
        for frame in metadata["frames"]
    ]
    video.labels = [
        ResearchVideoLabel(
            name="default",
            color="#22c55e",
            shape_type="polygon",
            sort_order=0,
        )
    ]

    db.commit()
    db.refresh(video)
    return ResearchVideoUploadResponse(
        **_research_video_to_read(video).model_dump(),
        warnings=metadata["warnings"],
    )


@router.get("/videos/{video_id}", response_model=ResearchVideoDetailRead)
def get_research_video(video_id: int, db: Session = Depends(get_db)) -> ResearchVideoDetailRead:
    video = _get_research_video_or_404(video_id, db)
    return _research_video_to_detail(video)


@router.get("/videos/{video_id}/workspace", response_model=ResearchVideoWorkspaceRead)
def get_research_video_workspace(video_id: int, db: Session = Depends(get_db)) -> ResearchVideoWorkspaceRead:
    video = _get_research_video_workspace_or_404(video_id, db)
    return _research_video_to_workspace(video)


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
    for index, annotation in enumerate(payload.annotations):
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


def _research_video_to_read(video: ResearchVideo) -> ResearchVideoRead:
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
