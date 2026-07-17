from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

import cv2
from fastapi import UploadFile


class InvalidVideoError(ValueError):
    pass


class VideoImportWarning(UserWarning):
    pass


def save_uploaded_video(upload: UploadFile, *, videos_root: Path) -> tuple[str, str]:
    videos_root.mkdir(parents=True, exist_ok=True)
    original_name = Path(upload.filename or "video.mp4").name
    suffix = Path(original_name).suffix.lower() or ".mp4"
    stored_name = f"{uuid4().hex}{suffix}"
    video_path = videos_root / stored_name

    upload.file.seek(0)
    with video_path.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)

    return str(video_path), original_name


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
