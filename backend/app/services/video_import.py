from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

import cv2
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models.research import ResearchVideo, ResearchVideoFrame, ResearchVideoLabel


class InvalidVideoError(ValueError):
    pass


class VideoImportWarning(UserWarning):
    pass


SUPPORTED_RESEARCH_VIDEO_EXTENSIONS = frozenset({
    ".mp4",
    ".mov",
    ".m4v",
    ".avi",
    ".mkv",
    ".webm",
})


def is_supported_research_video_filename(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_RESEARCH_VIDEO_EXTENSIONS


def save_uploaded_video(upload: UploadFile, *, videos_root: Path) -> tuple[str, str]:
    videos_root.mkdir(parents=True, exist_ok=True)
    original_name = Path(upload.filename or "video.mp4").name
    if not is_supported_research_video_filename(original_name):
        raise InvalidVideoError("Unsupported video format.")
    suffix = Path(original_name).suffix.lower() or ".mp4"
    stored_name = f"{uuid4().hex}{suffix}"
    video_path = videos_root / stored_name

    upload.file.seek(0)
    with video_path.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)

    return str(video_path), original_name


def copy_server_video_to_managed_storage(source_path: Path, *, videos_root: Path) -> tuple[str, str]:
    if not is_supported_research_video_filename(source_path.name):
        raise InvalidVideoError("Unsupported video format.")

    videos_root.mkdir(parents=True, exist_ok=True)
    original_name = source_path.name
    suffix = source_path.suffix.lower() or ".mp4"
    stored_name = f"{uuid4().hex}{suffix}"
    video_path = videos_root / stored_name
    part_path = video_path.with_name(f"{video_path.name}.part")

    try:
        with source_path.open("rb") as source, part_path.open("wb") as target:
            shutil.copyfileobj(source, target, length=8 * 1024 * 1024)
        part_path.replace(video_path)
    except OSError as exc:
        part_path.unlink(missing_ok=True)
        video_path.unlink(missing_ok=True)
        raise InvalidVideoError("The source video is unreadable.") from exc

    return str(video_path), original_name


def import_managed_research_video(
    *,
    db: Session,
    video_path: str,
    original_filename: str,
    display_name: str | None,
    created_by_id: int | None,
    storage_root: Path,
    origin_type: str = "uploaded",
    source_video_id: int | None = None,
    trim_start_frame: int | None = None,
    trim_end_frame_exclusive: int | None = None,
    expected_frame_count: int | None = None,
) -> tuple[ResearchVideo, list[str]]:
    video = ResearchVideo(
        name=(display_name or original_filename).strip() or original_filename,
        original_filename=original_filename,
        file_path=video_path,
        status="processing",
        created_by_id=created_by_id,
        origin_type=origin_type,
        source_video_id=source_video_id,
        trim_start_frame=trim_start_frame,
        trim_end_frame_exclusive=trim_end_frame_exclusive,
    )
    db.add(video)
    db.flush()

    video_frames_root = storage_root / str(video.id) / "frames"
    thumbnail_path = storage_root / "thumbnails" / f"{video.id}.jpg"

    try:
        metadata = extract_video_frames(video_path, video_frames_root, thumbnail_path=thumbnail_path)
        if expected_frame_count is not None and metadata["frame_count"] != expected_frame_count:
            raise InvalidVideoError("Trimmed video frame count does not match the requested range.")
    except Exception:
        db.rollback()
        shutil.rmtree(storage_root / str(video.id), ignore_errors=True)
        thumbnail_path.unlink(missing_ok=True)
        Path(video_path).unlink(missing_ok=True)
        raise

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
    return video, metadata["warnings"]


def extract_video_frames(video_path: str | Path, output_dir: Path, *, thumbnail_path: Path | None = None) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise InvalidVideoError("Unable to open the uploaded video file.")

    fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
    warnings: list[str] = []
    if not fps or fps <= 0:
        fps = 30.0
        warnings.append("Video FPS metadata was missing. Defaulted to 30 FPS.")

    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0) or None
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0) or None

    frames: list[dict] = []
    frame_index = 0
    thumbnail_written = False

    while True:
        ret, frame = capture.read()
        if not ret:
            break

        filename = f"{frame_index:06d}.jpg"
        frame_path = output_dir / filename
        if not cv2.imwrite(str(frame_path), frame):
            capture.release()
            raise InvalidVideoError(f"Failed to write frame {frame_index}.")

        if thumbnail_path and not thumbnail_written:
            thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(thumbnail_path), frame):
                capture.release()
                raise InvalidVideoError("Failed to write video thumbnail.")
            thumbnail_written = True

        frame_height, frame_width = frame.shape[:2]
        frames.append(
            {
                "frame_index": frame_index,
                "timestamp_ms": int(round((frame_index / fps) * 1000)),
                "filename": filename,
                "file_path": str(frame_path),
                "width": frame_width,
                "height": frame_height,
            }
        )
        frame_index += 1

    capture.release()

    if frame_index == 0:
        raise InvalidVideoError("The uploaded video does not contain readable frames.")

    duration_ms = int(round((frame_index / fps) * 1000))
    return {
        "width": width or frames[0]["width"],
        "height": height or frames[0]["height"],
        "fps": fps,
        "frame_count": frame_index,
        "duration_ms": duration_ms,
        "frames": frames,
        "warnings": warnings,
    }
