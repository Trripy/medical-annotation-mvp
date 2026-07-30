from __future__ import annotations

import math
import json
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.research import ResearchVideo, ResearchVideoAnnotation
from app.models.research_phase import ResearchPhaseAnnotationSet, ResearchPhaseSegment
from app.models.research_skill import ResearchSkillAssessment, ResearchSkillEvidence, ResearchSkillScore
from app.services.video_import import InvalidVideoError, import_managed_research_video


class ResearchVideoTrimError(ValueError):
    pass


class ResearchVideoTrimConflictError(ResearchVideoTrimError):
    pass


@dataclass(frozen=True)
class LinkedResearchVideoData:
    frame_annotation_count: int
    phase_annotation_set_count: int
    phase_segment_count: int
    skill_assessment_count: int
    skill_evidence_count: int

    @property
    def has_any(self) -> bool:
        return any((
            self.frame_annotation_count,
            self.phase_annotation_set_count,
            self.phase_segment_count,
            self.skill_assessment_count,
            self.skill_evidence_count,
        ))


_trim_semaphore = threading.BoundedSemaphore(max(1, int(settings.research_video_trim_max_concurrency or 1)))


def minimum_keep_frames(video: ResearchVideo) -> int:
    fps = float(video.fps or 0)
    if math.isfinite(fps) and fps > 0:
        return max(10, int(math.ceil(fps)))
    return 10


def get_linked_video_data(db: Session, video_id: int) -> LinkedResearchVideoData:
    frame_annotation_count = db.scalar(
        select(func.count(ResearchVideoAnnotation.id)).where(ResearchVideoAnnotation.video_id == video_id)
    ) or 0
    phase_annotation_set_count = db.scalar(
        select(func.count(ResearchPhaseAnnotationSet.id)).where(ResearchPhaseAnnotationSet.video_id == video_id)
    ) or 0
    phase_segment_count = db.scalar(
        select(func.count(ResearchPhaseSegment.id))
        .join(ResearchPhaseAnnotationSet, ResearchPhaseSegment.annotation_set_id == ResearchPhaseAnnotationSet.id)
        .where(ResearchPhaseAnnotationSet.video_id == video_id)
    ) or 0
    skill_assessment_count = db.scalar(
        select(func.count(ResearchSkillAssessment.id)).where(ResearchSkillAssessment.video_id == video_id)
    ) or 0
    skill_evidence_count = db.scalar(
        select(func.count(ResearchSkillEvidence.id))
        .join(ResearchSkillScore, ResearchSkillEvidence.skill_score_id == ResearchSkillScore.id)
        .join(ResearchSkillAssessment, ResearchSkillScore.assessment_id == ResearchSkillAssessment.id)
        .where(ResearchSkillAssessment.video_id == video_id)
    ) or 0
    return LinkedResearchVideoData(
        frame_annotation_count=frame_annotation_count,
        phase_annotation_set_count=phase_annotation_set_count,
        phase_segment_count=phase_segment_count,
        skill_assessment_count=skill_assessment_count,
        skill_evidence_count=skill_evidence_count,
    )


def validate_trim_range(video: ResearchVideo, start_frame: int, end_frame_exclusive: int) -> None:
    frame_count = int(video.frame_count or 0)
    if start_frame < 0:
        raise ResearchVideoTrimError("Invalid trim range.")
    if end_frame_exclusive > frame_count:
        raise ResearchVideoTrimError("Invalid trim range.")
    if start_frame >= end_frame_exclusive:
        raise ResearchVideoTrimError("Invalid trim range.")
    if start_frame == 0 and end_frame_exclusive == frame_count:
        raise ResearchVideoTrimError("Trim range is unchanged.")
    if end_frame_exclusive - start_frame < minimum_keep_frames(video):
        raise ResearchVideoTrimError("Trim range is too short.")


def sanitize_trim_display_name(source_name: str, display_name: str | None) -> str:
    candidate = (display_name or default_trimmed_name(source_name)).strip()
    candidate = Path(candidate.replace("\\", "/")).name
    if not candidate:
        candidate = default_trimmed_name(source_name)
    if not candidate.lower().endswith(".mp4"):
        candidate = f"{Path(candidate).stem or 'trimmed_video'}.mp4"
    return candidate[:255]


def default_trimmed_name(source_name: str) -> str:
    stem = Path(source_name).stem or "video"
    return f"{stem}_trimmed.mp4"


def trim_research_video(
    *,
    db: Session,
    source_video: ResearchVideo,
    start_frame: int,
    end_frame_exclusive: int,
    display_name: str | None,
    acknowledge_annotations_not_copied: bool,
    storage_root: Path,
) -> tuple[ResearchVideo, list[str]]:
    if source_video.status != "ready":
        raise ResearchVideoTrimError("Only ready research videos can be trimmed.")
    validate_trim_range(source_video, start_frame, end_frame_exclusive)

    linked_data = get_linked_video_data(db, source_video.id)
    if linked_data.has_any and not acknowledge_annotations_not_copied:
        raise ResearchVideoTrimError("Existing annotations must be acknowledged before trimming.")

    duplicate = db.scalar(
        select(ResearchVideo).where(
            ResearchVideo.source_video_id == source_video.id,
            ResearchVideo.trim_start_frame == start_frame,
            ResearchVideo.trim_end_frame_exclusive == end_frame_exclusive,
            ResearchVideo.status == "processing",
        )
    )
    if duplicate is not None:
        raise ResearchVideoTrimConflictError("A trim with the same range is already processing.")

    source_path = Path(source_video.file_path)
    if not source_path.is_file():
        raise ResearchVideoTrimError("Source video file not found.")

    output_name = sanitize_trim_display_name(source_video.original_filename or source_video.name, display_name)
    raw_root = storage_root / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    output_path = raw_root / f"{uuid4().hex}.mp4"
    part_path = output_path.with_name(f"{output_path.name}.part")
    expected_frame_count = end_frame_exclusive - start_frame

    _ensure_managed_storage_space(source_path, storage_root, start_frame, end_frame_exclusive, int(source_video.frame_count or 0))
    ffmpeg_binary = resolve_ffmpeg_binary()

    acquired = _trim_semaphore.acquire(timeout=1)
    if not acquired:
        raise ResearchVideoTrimConflictError("Another video trim is currently running.")
    try:
        _run_ffmpeg_trim(
            ffmpeg_binary=ffmpeg_binary,
            source_path=source_path,
            part_path=part_path,
            start_frame=start_frame,
            end_frame_exclusive=end_frame_exclusive,
            fps=float(source_video.fps or 0),
        )
        part_path.replace(output_path)
        try:
            return import_managed_research_video(
                db=db,
                video_path=str(output_path),
                original_filename=output_name,
                display_name=output_name,
                created_by_id=source_video.created_by_id,
                storage_root=storage_root,
                origin_type="trimmed",
                source_video_id=source_video.id,
                trim_start_frame=start_frame,
                trim_end_frame_exclusive=end_frame_exclusive,
                expected_frame_count=expected_frame_count,
            )
        except Exception:
            output_path.unlink(missing_ok=True)
            raise
    except OSError as exc:
        part_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        raise ResearchVideoTrimError("Trimmed video could not be created.") from exc
    finally:
        part_path.unlink(missing_ok=True)
        _trim_semaphore.release()


def resolve_ffmpeg_binary() -> str:
    configured = settings.research_video_ffmpeg_binary.strip()
    candidates = [
        configured,
        shutil.which("ffmpeg") or "",
        "/data1/zhangyuzhu/code/autoannotate/conda_envs/sam/bin/ffmpeg",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise ResearchVideoTrimError("FFmpeg is not available.")


def _run_ffmpeg_trim(
    *,
    ffmpeg_binary: str,
    source_path: Path,
    part_path: Path,
    start_frame: int,
    end_frame_exclusive: int,
    fps: float,
) -> None:
    if fps <= 0 or not math.isfinite(fps):
        raise ResearchVideoTrimError("Source video FPS is invalid.")
    start_seconds = start_frame / fps
    duration_seconds = (end_frame_exclusive - start_frame) / fps
    video_filter = (
        f"select=between(n\\,{start_frame}\\,{end_frame_exclusive - 1}),"
        "setpts=PTS-STARTPTS"
    )
    has_audio = _source_has_audio(ffmpeg_binary, source_path)
    command = [
        ffmpeg_binary,
        "-hide_banner",
        "-y",
        "-i",
        str(source_path),
        "-vf",
        video_filter,
        "-map",
        "0:v:0",
        "-vsync",
        "0",
        *_video_encoder_args(ffmpeg_binary),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        str(part_path),
    ]
    if has_audio:
        output_index = command.index("-vsync")
        command[output_index:output_index] = [
            "-af",
            f"atrim=start={start_seconds:.9f}:duration={duration_seconds:.9f},asetpts=PTS-STARTPTS",
            "-map",
            "0:a?",
        ]
        command[-3:-3] = ["-c:a", "aac"]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=3600, shell=False)
    if completed.returncode != 0:
        raise ResearchVideoTrimError("FFmpeg failed to create the trimmed video.")
    _validate_trimmed_container(
        ffmpeg_binary=ffmpeg_binary,
        video_path=part_path,
    )


def _source_has_audio(ffmpeg_binary: str, source_path: Path) -> bool:
    ffprobe_binary = str(Path(ffmpeg_binary).with_name("ffprobe"))
    if not Path(ffprobe_binary).is_file():
        return False
    completed = subprocess.run(
        [
            ffprobe_binary,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(source_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        shell=False,
    )
    return completed.returncode == 0 and bool(completed.stdout.strip())


def _video_encoder_args(ffmpeg_binary: str) -> list[str]:
    try:
        completed = subprocess.run(
            [ffmpeg_binary, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=15,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        completed = None
    encoders = completed.stdout if completed and completed.returncode == 0 else ""
    if "libx264" in encoders:
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]
    if "libopenh264" in encoders:
        return ["-c:v", "libopenh264", "-b:v", "6M"]
    raise ResearchVideoTrimError("No supported H.264 encoder is available for video trimming.")


def _validate_trimmed_container(*, ffmpeg_binary: str, video_path: Path) -> None:
    ffprobe_binary = str(Path(ffmpeg_binary).with_name("ffprobe"))
    if not Path(ffprobe_binary).is_file():
        raise ResearchVideoTrimError("FFprobe is not available.")
    completed = subprocess.run(
        [
            ffprobe_binary,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt,width,height,start_time",
            "-show_entries",
            "format=format_name,start_time",
            "-of",
            "json",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        shell=False,
    )
    if completed.returncode != 0:
        raise ResearchVideoTrimError("Trimmed video could not be validated.")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ResearchVideoTrimError("Trimmed video could not be validated.") from exc
    streams = payload.get("streams") or []
    stream = streams[0] if streams else {}
    codec_name = stream.get("codec_name")
    format_name = str((payload.get("format") or {}).get("format_name") or "")
    if codec_name != "h264" or "mp4" not in format_name:
        raise ResearchVideoTrimError("Trimmed video is not browser-compatible H.264 MP4.")
    pix_fmt = stream.get("pix_fmt")
    if pix_fmt and pix_fmt != "yuv420p":
        raise ResearchVideoTrimError("Trimmed video pixel format is not browser-compatible.")
    start_time = stream.get("start_time") or (payload.get("format") or {}).get("start_time")
    if start_time is not None:
        try:
            if abs(float(start_time)) > 0.1:
                raise ResearchVideoTrimError("Trimmed video timestamps do not start at zero.")
        except ValueError as exc:
            raise ResearchVideoTrimError("Trimmed video could not be validated.") from exc


def _ensure_managed_storage_space(
    source_path: Path,
    storage_root: Path,
    start_frame: int,
    end_frame_exclusive: int,
    frame_count: int,
) -> None:
    if frame_count <= 0:
        raise ResearchVideoTrimError("Source video frame count is invalid.")
    retained_ratio = (end_frame_exclusive - start_frame) / frame_count
    estimated_output = max(256 * 1024 * 1024, int(source_path.stat().st_size * retained_ratio * 1.5))
    usage = shutil.disk_usage(storage_root if storage_root.exists() else storage_root.parent)
    if usage.free < estimated_output:
        raise ResearchVideoTrimError("Insufficient managed storage space for the trimmed video.")
