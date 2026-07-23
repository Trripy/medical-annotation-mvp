from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import research as research_api
from app.core.config import settings
from app.db.base import Base
from app.models.research import ResearchVideo, ResearchVideoFrame, ResearchVideoLabel
from app.schemas.research import ResearchVideoDetailRead, ResearchVideoFramesPageRead, ResearchVideoWorkspaceRead


@pytest.fixture()
def research_db_context(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)

    original_local_storage_root = settings.local_storage_root
    settings.local_storage_root = str(tmp_path)
    try:
        yield SessionLocal
    finally:
        settings.local_storage_root = original_local_storage_root
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed_research_video(session_factory: sessionmaker, *, frame_count: int = 550) -> int:
    with session_factory() as db:
        video = ResearchVideo(
            name="Paged Workspace Video",
            original_filename="paged-workspace.mp4",
            file_path="/tmp/research/paged-workspace.mp4",
            width=3840,
            height=2160,
            fps=25.0,
            frame_count=frame_count,
            duration_ms=frame_count * 40,
            status="ready",
        )
        db.add(video)
        db.flush()

        db.add_all([
            ResearchVideoLabel(
                video_id=video.id,
                name="default",
                color="#22c55e",
                shape_type="polygon",
                sort_order=0,
            ),
            ResearchVideoLabel(
                video_id=video.id,
                name="secondary",
                color="#ef4444",
                shape_type="rectangle",
                sort_order=1,
            ),
        ])

        db.add_all([
            ResearchVideoFrame(
                video_id=video.id,
                frame_index=frame_index,
                timestamp_ms=frame_index * 40,
                filename=f"frame_{frame_index:06d}.jpg",
                file_path=f"/tmp/research/frames/frame_{frame_index:06d}.jpg",
                width=3840,
                height=2160,
            )
            for frame_index in range(frame_count - 1, -1, -1)
        ])
        db.commit()
        return video.id


def test_workspace_endpoint_returns_lightweight_video_detail(research_db_context) -> None:
    session_factory = research_db_context
    video_id = _seed_research_video(session_factory)

    with session_factory() as db:
        payload = research_api.get_research_video_workspace(video_id, db)

    assert isinstance(payload, ResearchVideoWorkspaceRead)
    dumped = payload.model_dump()
    assert dumped["id"] == video_id
    assert dumped["file_url"] == f"/api/research/videos/{video_id}/file"
    assert dumped["frame_count"] == 550
    assert "frames" not in dumped
    assert [label["name"] for label in dumped["labels"]] == ["default", "secondary"]


def test_frames_endpoint_uses_default_page_size_and_sorted_frame_order(research_db_context) -> None:
    session_factory = research_db_context
    video_id = _seed_research_video(session_factory)

    with session_factory() as db:
        payload = research_api.list_research_video_frames(video_id=video_id, offset=0, limit=500, db=db)

    assert isinstance(payload, ResearchVideoFramesPageRead)
    dumped = payload.model_dump()
    assert dumped["offset"] == 0
    assert dumped["limit"] == 500
    assert dumped["total"] == 550
    assert dumped["has_more"] is True
    assert len(dumped["items"]) == 500
    assert dumped["items"][0]["frame_index"] == 0
    assert dumped["items"][-1]["frame_index"] == 499
    assert "points" not in dumped["items"][0]


def test_frames_endpoint_supports_offset_and_limit(research_db_context) -> None:
    session_factory = research_db_context
    video_id = _seed_research_video(session_factory)

    with session_factory() as db:
        payload = research_api.list_research_video_frames(video_id=video_id, offset=520, limit=50, db=db)

    dumped = payload.model_dump()
    assert dumped["offset"] == 520
    assert dumped["limit"] == 50
    assert dumped["total"] == 550
    assert dumped["has_more"] is False
    assert [item["frame_index"] for item in dumped["items"]] == list(range(520, 550))


def test_frames_endpoint_declares_default_and_maximum_limit_constraints() -> None:
    route = next(
        candidate
        for candidate in research_api.router.routes
        if getattr(candidate, "path", None) == "/videos/{video_id}/frames"
    )
    limit_parameter = next(parameter for parameter in route.dependant.query_params if parameter.name == "limit")
    offset_parameter = next(parameter for parameter in route.dependant.query_params if parameter.name == "offset")
    limit_constraints = {type(constraint).__name__: constraint for constraint in limit_parameter.field_info.metadata}
    offset_constraints = {type(constraint).__name__: constraint for constraint in offset_parameter.field_info.metadata}

    assert limit_parameter.default == 500
    assert getattr(limit_constraints["Ge"], "ge") == 1
    assert getattr(limit_constraints["Le"], "le") == 1000
    assert offset_parameter.default == 0
    assert getattr(offset_constraints["Ge"], "ge") == 0


@pytest.mark.parametrize(
    "endpoint",
    [
        lambda video_id, db: research_api.get_research_video_workspace(video_id, db),
        lambda video_id, db: research_api.list_research_video_frames(video_id=video_id, offset=0, limit=500, db=db),
    ],
)
def test_workspace_and_frames_endpoints_return_404_for_unknown_video(
    research_db_context,
    endpoint,
) -> None:
    session_factory = research_db_context

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            endpoint(999999, db)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Research video not found"


def test_legacy_detail_endpoint_still_returns_full_frame_list(research_db_context) -> None:
    session_factory = research_db_context
    video_id = _seed_research_video(session_factory, frame_count=12)

    with session_factory() as db:
        payload = research_api.get_research_video(video_id, db)

    assert isinstance(payload, ResearchVideoDetailRead)
    dumped = payload.model_dump()
    assert len(dumped["frames"]) == 12
    assert dumped["frames"][0]["frame_index"] == 0
    assert dumped["frames"][-1]["frame_index"] == 11
    assert [label["name"] for label in dumped["labels"]] == ["default", "secondary"]
