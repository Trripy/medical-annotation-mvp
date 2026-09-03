from __future__ import annotations

from fastapi import FastAPI

from app.api.v1 import research
from app.db.base import Base
from app.db.session import get_db
from app.models import ResearchVideo
from app.services.research_video_checklist import (
    hide_trimmed_source_videos,
    list_video_operation_checklist,
    preview_hide_trimmed_source_videos,
    restore_trimmed_source_videos,
)
from tests._asgi_test_utils import asgi_request
from tests._research_phase_test_utils import create_phase_session_factory, seed_phase_data


def _visibility_app(session_factory):
    test_app = FastAPI()
    test_app.include_router(research.router, prefix="/api/research")

    async def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    test_app.dependency_overrides[get_db] = override_get_db
    return test_app


def test_video_visibility_default_list_excludes_hidden_but_detail_and_checklist_include_it(tmp_path) -> None:
    engine, session_factory = create_phase_session_factory(tmp_path)
    seeded = seed_phase_data(session_factory)
    app = _visibility_app(session_factory)
    try:
        with session_factory() as db:
            video = db.get(ResearchVideo, seeded.video_id)
            assert video is not None
            video.hidden_from_video_list = True
            video.hidden_reason = "manual"
            db.commit()

        visible_response = asgi_request(app, "GET", "/api/research/videos")
        hidden_response = asgi_request(app, "GET", "/api/research/videos", params={"visibility": "hidden"})
        detail_response = asgi_request(app, "GET", f"/api/research/videos/{seeded.video_id}")

        with session_factory() as db:
            checklist = list_video_operation_checklist(db, page=1, page_size=50)

        assert visible_response.status_code == 200
        assert all(item["id"] != seeded.video_id for item in visible_response.json())
        assert any(item["id"] == seeded.video_id for item in hidden_response.json())
        assert detail_response.status_code == 200
        assert detail_response.json()["id"] == seeded.video_id
        assert any(item.video.id == seeded.video_id for item in checklist.items)
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_hide_trimmed_sources_only_hides_root_sources_with_ready_direct_derivatives(tmp_path) -> None:
    engine, session_factory = create_phase_session_factory(tmp_path)
    seeded = seed_phase_data(session_factory)
    try:
        with session_factory() as db:
            source = db.get(ResearchVideo, seeded.video_id)
            assert source is not None
            source.origin_type = "uploaded"
            ready_child = ResearchVideo(
                name="ready child",
                original_filename="ready-child.mp4",
                file_path="/tmp/ready-child.mp4",
                status="ready",
                origin_type="trimmed",
                source_video_id=source.id,
                frame_count=10,
            )
            failed_source = ResearchVideo(
                name="failed source",
                original_filename="failed-source.mp4",
                file_path="/tmp/failed-source.mp4",
                status="ready",
                origin_type="uploaded",
                frame_count=10,
            )
            intermediate = ResearchVideo(
                name="intermediate trimmed",
                original_filename="intermediate.mp4",
                file_path="/tmp/intermediate.mp4",
                status="ready",
                origin_type="trimmed",
                source_video_id=source.id,
                frame_count=10,
            )
            db.add_all([ready_child, failed_source, intermediate])
            db.flush()
            failed_child = ResearchVideo(
                name="failed child",
                original_filename="failed-child.mp4",
                file_path="/tmp/failed-child.mp4",
                status="failed",
                origin_type="trimmed",
                source_video_id=failed_source.id,
                frame_count=10,
            )
            intermediate_child = ResearchVideo(
                name="intermediate child",
                original_filename="intermediate-child.mp4",
                file_path="/tmp/intermediate-child.mp4",
                status="ready",
                origin_type="trimmed",
                source_video_id=intermediate.id,
                frame_count=10,
            )
            db.add_all([failed_child, intermediate_child])
            db.commit()
            source_id = source.id
            failed_source_id = failed_source.id
            intermediate_id = intermediate.id

            preview = preview_hide_trimmed_source_videos(db)
            result = hide_trimmed_source_videos(db)
            db.expire_all()
            source_after = db.get(ResearchVideo, source_id)
            failed_source_after = db.get(ResearchVideo, failed_source_id)
            intermediate_after = db.get(ResearchVideo, intermediate_id)

        assert preview.eligible_count == 1
        assert result.affected_count == 1
        assert source_after is not None and source_after.hidden_from_video_list is True
        assert source_after.hidden_reason == "trimmed_source"
        assert failed_source_after is not None and failed_source_after.hidden_from_video_list is False
        assert intermediate_after is not None and intermediate_after.hidden_from_video_list is False
    finally:
        engine.dispose()


def test_restore_trimmed_sources_only_restores_trimmed_source_reason(tmp_path) -> None:
    engine, session_factory = create_phase_session_factory(tmp_path)
    seeded = seed_phase_data(session_factory)
    try:
        with session_factory() as db:
            video = db.get(ResearchVideo, seeded.video_id)
            assert video is not None
            manual = ResearchVideo(
                name="manual hidden",
                original_filename="manual-hidden.mp4",
                file_path="/tmp/manual-hidden.mp4",
                status="ready",
                origin_type="uploaded",
                frame_count=10,
                hidden_from_video_list=True,
                hidden_reason="manual",
            )
            video.hidden_from_video_list = True
            video.hidden_reason = "trimmed_source"
            db.add(manual)
            db.commit()
            video_id = video.id
            db.flush()
            manual_id = manual.id

            result = restore_trimmed_source_videos(db)
            db.expire_all()
            restored = db.get(ResearchVideo, video_id)
            still_hidden = db.get(ResearchVideo, manual_id)

        assert result.affected_count == 1
        assert restored is not None and restored.hidden_from_video_list is False
        assert restored.hidden_reason is None
        assert still_hidden is not None and still_hidden.hidden_from_video_list is True
        assert still_hidden.hidden_reason == "manual"
    finally:
        engine.dispose()
