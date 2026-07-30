from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models import User
from app.models.research import ResearchVideo
from app.schemas.research import (
    ResearchVideoRead,
    ResearchVideoUploadResponse,
    ServerVideoBrowseRead,
    ServerVideoImportFileRequest,
    ServerVideoImportRootsRead,
    ServerVideoImportRootRead,
    ServerVideoScanFolderRead,
    ServerVideoScanFolderRequest,
)
from app.services.server_video_import import (
    browse_directory,
    parse_server_import_roots,
    resolve_import_path,
    scan_folder,
)
from app.services.video_import import (
    InvalidVideoError,
    copy_server_video_to_managed_storage,
    import_managed_research_video,
)

router = APIRouter(prefix="/server-video-import", tags=["research-server-video-import"])


@router.get("/roots", response_model=ServerVideoImportRootsRead)
def list_server_video_import_roots() -> ServerVideoImportRootsRead:
    roots = parse_server_import_roots()
    return ServerVideoImportRootsRead(
        enabled=bool(roots),
        roots=[ServerVideoImportRootRead(id=root.id, name=root.name) for root in roots.values()],
    )


@router.get("/browse", response_model=ServerVideoBrowseRead)
def browse_server_video_import_directory(
    root_id: str = Query(...),
    relative_path: str = Query(default=""),
) -> ServerVideoBrowseRead:
    return ServerVideoBrowseRead.model_validate(browse_directory(root_id, relative_path))


@router.post("/scan-folder", response_model=ServerVideoScanFolderRead)
def scan_server_video_import_folder(payload: ServerVideoScanFolderRequest) -> ServerVideoScanFolderRead:
    return ServerVideoScanFolderRead.model_validate(
        scan_folder(payload.root_id, payload.relative_path, recursive=payload.recursive)
    )


@router.post("/file", response_model=ResearchVideoUploadResponse, status_code=status.HTTP_201_CREATED)
def import_server_video_file(
    payload: ServerVideoImportFileRequest,
    db: Session = Depends(get_db),
) -> ResearchVideoUploadResponse:
    source_path = resolve_import_path(payload.root_id, payload.relative_path, expected="file")

    created_by_id: int | None = None
    if payload.username:
        user = db.scalar(select(User).where(User.username == payload.username.strip()))
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        created_by_id = user.id

    storage_root = Path(settings.local_storage_root) / "research" / "videos"
    raw_root = storage_root / "raw"
    managed_video_path: str | None = None
    try:
        managed_video_path, original_filename = copy_server_video_to_managed_storage(source_path, videos_root=raw_root)
        video, warnings = import_managed_research_video(
            db=db,
            video_path=managed_video_path,
            original_filename=original_filename,
            display_name=payload.display_name,
            created_by_id=created_by_id,
            storage_root=storage_root,
            origin_type="server_imported",
        )
    except InvalidVideoError as exc:
        if managed_video_path:
            Path(managed_video_path).unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return ResearchVideoUploadResponse(
        **_research_video_to_read(video).model_dump(),
        warnings=warnings,
    )


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
        source_video_id=video.source_video_id,
        origin_type=video.origin_type,
        trim_start_frame=video.trim_start_frame,
        trim_end_frame_exclusive=video.trim_end_frame_exclusive,
        thumbnail_url=f"/api/research/videos/{video.id}/thumbnail" if video.thumbnail_path else None,
        created_at=video.created_at.isoformat(),
        updated_at=video.updated_at.isoformat(),
    )
