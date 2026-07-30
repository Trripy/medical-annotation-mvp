from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.models import ResearchPhaseAnnotationSet, ResearchPhaseSegment, ResearchVideo, User
from app.services.research_video_checklist import list_default_phase_export_selections, list_video_operation_checklist
from tests._research_phase_test_utils import create_phase_session_factory, seed_phase_data


def test_checklist_reports_trim_derivatives_phase_status_and_omits_paths(tmp_path) -> None:
    engine, session_factory = create_phase_session_factory(tmp_path)
    seeded = seed_phase_data(session_factory)
    try:
        with session_factory() as db:
            source = db.get(ResearchVideo, seeded.video_id)
            assert source is not None
            source.name = "source video.mp4"
            trimmed = ResearchVideo(
                name="source video_trimmed.mp4",
                original_filename="trimmed.mp4",
                file_path="/tmp/should-not-leak.mp4",
                width=640,
                height=360,
                fps=25.0,
                frame_count=200,
                duration_ms=8000,
                status="ready",
                origin_type="trimmed",
                source_video_id=source.id,
                trim_start_frame=10,
                trim_end_frame_exclusive=210,
            )
            db.add(trimmed)
            db.flush()
            child = ResearchVideo(
                name="source video_trimmed_again.mp4",
                original_filename="again.mp4",
                file_path="/tmp/should-not-leak-again.mp4",
                width=640,
                height=360,
                fps=25.0,
                frame_count=100,
                duration_ms=4000,
                status="ready",
                origin_type="trimmed",
                source_video_id=trimmed.id,
                trim_start_frame=20,
                trim_end_frame_exclusive=120,
            )
            db.add(child)
            db.commit()

            checklist = list_video_operation_checklist(db, page=1, page_size=50)

        by_name = {item.video.display_name: item for item in checklist.items}
        assert by_name["source video.mp4"].trim.derived_video_count == 1
        assert by_name["source video_trimmed.mp4"].trim.is_trimmed is True
        assert by_name["source video_trimmed.mp4"].trim.source_video_display_name == "source video.mp4"
        assert by_name["source video_trimmed.mp4"].trim.derived_video_count == 1
        assert by_name["source video.mp4"].phase.draft_count == 1
        assert by_name["source video.mp4"].phase.submitted_count == 1
        assert by_name["source video.mp4"].phase.annotation_set_count == 2
        assert checklist.stats.trimmed_videos == 2
        assert checklist.stats.source_with_derivatives == 2
        assert "file_path" not in checklist.model_dump_json()
        assert "/tmp/" not in checklist.model_dump_json()
    finally:
        engine.dispose()


def test_checklist_filters_phase_and_trim_status(tmp_path) -> None:
    engine, session_factory = create_phase_session_factory(tmp_path)
    seeded = seed_phase_data(session_factory)
    try:
        with session_factory() as db:
            source = db.get(ResearchVideo, seeded.video_id)
            assert source is not None
            trimmed = ResearchVideo(
                name="trimmed",
                original_filename="trimmed.mp4",
                file_path="/tmp/trimmed.mp4",
                fps=25.0,
                frame_count=10,
                duration_ms=400,
                status="ready",
                origin_type="trimmed",
                source_video_id=source.id,
                trim_start_frame=0,
                trim_end_frame_exclusive=10,
            )
            db.add(trimmed)
            db.commit()

            trimmed_items = list_video_operation_checklist(db, page=1, page_size=50, trim_status="trimmed")
            submitted_items = list_video_operation_checklist(db, page=1, page_size=50, phase_status="draft_and_submitted")
            protocol_items = list_video_operation_checklist(db, page=1, page_size=50, protocol_id=seeded.active_default_protocol_id)

        assert [item.video.display_name for item in trimmed_items.items] == ["trimmed"]
        assert any(item.phase.submitted_count > 0 for item in submitted_items.items)
        assert protocol_items.total == 1
    finally:
        engine.dispose()


def test_checklist_phase_metrics_use_segments_without_frame_rows(tmp_path) -> None:
    engine, session_factory = create_phase_session_factory(tmp_path)
    seeded = seed_phase_data(session_factory)
    try:
        with session_factory() as db:
            annotation_set = db.scalar(select(ResearchPhaseAnnotationSet).where(ResearchPhaseAnnotationSet.id == seeded.set_reader_id))
            assert annotation_set is not None
            db.query(ResearchPhaseSegment).filter(ResearchPhaseSegment.annotation_set_id == annotation_set.id).delete()
            db.add_all([
                ResearchPhaseSegment(annotation_set_id=annotation_set.id, phase_label_id=seeded.active_default_label_ids["idle"], start_frame=0, end_frame_exclusive=100),
                ResearchPhaseSegment(annotation_set_id=annotation_set.id, phase_label_id=seeded.active_default_label_ids["viscoelastic"], start_frame=100, end_frame_exclusive=200),
            ])
            db.commit()
            checklist = list_video_operation_checklist(db, page=1, page_size=50)

        item = next(candidate for candidate in checklist.items if candidate.video.id == seeded.video_id)
        draft_set = next(annotation_set for annotation_set in item.phase.sets if annotation_set.annotation_set_id == seeded.set_reader_id)
        assert draft_set.segment_count == 2
        assert draft_set.coverage_percent == 50.0
        assert draft_set.error_count == 0
        assert "research_video_frames" not in checklist.model_dump_json()
    finally:
        engine.dispose()


def test_default_phase_selections_pick_latest_submitted_and_skip_drafts(tmp_path) -> None:
    engine, session_factory = create_phase_session_factory(tmp_path)
    seeded = seed_phase_data(session_factory)
    try:
        with session_factory() as db:
            video = ResearchVideo(
                name="default selection submitted.mp4",
                original_filename="default selection submitted.mp4",
                file_path="/tmp/default-selection-submitted.mp4",
                fps=25.0,
                frame_count=100,
                duration_ms=4000,
                status="ready",
            )
            draft_only_video = ResearchVideo(
                name="default selection draft only.mp4",
                original_filename="default selection draft only.mp4",
                file_path="/tmp/default-selection-draft-only.mp4",
                fps=25.0,
                frame_count=100,
                duration_ms=4000,
                status="ready",
            )
            db.add_all([video, draft_only_video])
            db.flush()
            users = [
                User(username=f"default_select_{index}", email=f"default_select_{index}@example.com")
                for index in range(5)
            ]
            db.add_all(users)
            db.flush()
            old_submitted = ResearchPhaseAnnotationSet(
                video_id=video.id,
                protocol_id=seeded.active_default_protocol_id,
                annotator_id=users[0].id,
                status="submitted",
                revision=10,
                submitted_at=datetime(2026, 7, 29, 10, tzinfo=timezone.utc),
            )
            newer_submitted_lower_version = ResearchPhaseAnnotationSet(
                video_id=video.id,
                protocol_id=seeded.active_default_protocol_id,
                annotator_id=users[1].id,
                status="submitted",
                revision=2,
                submitted_at=datetime(2026, 7, 30, 10, tzinfo=timezone.utc),
            )
            newer_submitted_higher_version = ResearchPhaseAnnotationSet(
                video_id=video.id,
                protocol_id=seeded.active_default_protocol_id,
                annotator_id=users[2].id,
                status="submitted",
                revision=3,
                submitted_at=datetime(2026, 7, 30, 10, tzinfo=timezone.utc),
            )
            draft = ResearchPhaseAnnotationSet(
                video_id=video.id,
                protocol_id=seeded.active_default_protocol_id,
                annotator_id=users[3].id,
                status="draft",
                revision=99,
            )
            draft_only = ResearchPhaseAnnotationSet(
                video_id=draft_only_video.id,
                protocol_id=seeded.active_default_protocol_id,
                annotator_id=users[4].id,
                status="draft",
                revision=1,
            )
            db.add_all([old_submitted, newer_submitted_lower_version, newer_submitted_higher_version, draft, draft_only])
            db.commit()
            video_id = video.id
            draft_only_video_id = draft_only_video.id
            expected_annotation_set_id = newer_submitted_higher_version.id

            selections = list_default_phase_export_selections(db, search="default selection")

        by_video = {selection.video_id: selection for selection in selections}
        assert by_video[video_id].annotation_set_id == expected_annotation_set_id
        assert by_video[video_id].status == "submitted"
        assert draft_only_video_id not in by_video
        assert all(selection.status == "submitted" for selection in selections)
    finally:
        engine.dispose()
