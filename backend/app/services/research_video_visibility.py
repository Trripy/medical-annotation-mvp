from __future__ import annotations

from datetime import datetime, timezone

from app.models import ResearchVideo

TRIMMED_SOURCE_HIDDEN_REASON = "trimmed_source"
MANUAL_HIDDEN_REASON = "manual"


def hide_research_video_from_list(
    video: ResearchVideo,
    *,
    reason: str,
    now: datetime | None = None,
    preserve_existing_reason: bool = True,
) -> bool:
    """Hide a video from the regular research list without changing media or annotations."""
    if video.hidden_from_video_list:
        if not preserve_existing_reason and video.hidden_reason is None:
            video.hidden_reason = reason
        return False
    hidden_at = now or datetime.now(timezone.utc)
    video.hidden_from_video_list = True
    video.hidden_at = hidden_at
    video.hidden_reason = reason
    video.updated_at = hidden_at
    return True


def restore_research_video_to_list(video: ResearchVideo, *, now: datetime | None = None) -> bool:
    if not video.hidden_from_video_list and video.hidden_at is None and video.hidden_reason is None:
        return False
    restored_at = now or datetime.now(timezone.utc)
    video.hidden_from_video_list = False
    video.hidden_at = None
    video.hidden_reason = None
    video.updated_at = restored_at
    return True
