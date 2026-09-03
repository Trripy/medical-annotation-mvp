from __future__ import annotations

from fastapi import FastAPI

from app.api.v1 import research
from app.db.base import Base
from app.db.session import get_db
from app.models import ResearchVideo
from tests._asgi_test_utils import asgi_request
from tests._research_phase_test_utils import create_phase_session_factory, seed_phase_data


def _notes_app(session_factory):
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


def test_video_notes_update_preserves_other_video_fields(tmp_path) -> None:
    engine, session_factory = create_phase_session_factory(tmp_path)
    seeded = seed_phase_data(session_factory)
    app = _notes_app(session_factory)
    try:
        with session_factory() as db:
            video = db.get(ResearchVideo, seeded.video_id)
            assert video is not None
            video.hidden_from_video_list = True
            video.hidden_reason = "manual"
            video.source_video_id = None
            original_name = video.name
            original_status = video.status
            original_frame_count = video.frame_count
            db.commit()

        response = asgi_request(
            app,
            "PATCH",
            f"/api/research/videos/{seeded.video_id}/notes",
            json_body={"notes": "中文备注\n第二行"},
        )

        with session_factory() as db:
            video = db.get(ResearchVideo, seeded.video_id)
            assert video is not None

        assert response.status_code == 200
        assert response.json()["notes"] == "中文备注\n第二行"
        assert video.notes == "中文备注\n第二行"
        assert video.name == original_name
        assert video.status == original_status
        assert video.frame_count == original_frame_count
        assert video.hidden_from_video_list is True
        assert video.hidden_reason == "manual"
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_video_notes_normalize_blank_and_reject_too_long(tmp_path) -> None:
    engine, session_factory = create_phase_session_factory(tmp_path)
    seeded = seed_phase_data(session_factory)
    app = _notes_app(session_factory)
    try:
        blank_response = asgi_request(
            app,
            "PATCH",
            f"/api/research/videos/{seeded.video_id}/notes",
            json_body={"notes": "   \n\t"},
        )
        too_long_response = asgi_request(
            app,
            "PATCH",
            f"/api/research/videos/{seeded.video_id}/notes",
            json_body={"notes": "x" * 5001},
        )

        with session_factory() as db:
            video = db.get(ResearchVideo, seeded.video_id)
            assert video is not None

        assert blank_response.status_code == 200
        assert blank_response.json()["notes"] is None
        assert video.notes is None
        assert too_long_response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(engine)
        engine.dispose()
