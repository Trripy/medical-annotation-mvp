from __future__ import annotations

import csv
import io

import pytest
from sqlalchemy import select

from app.models import ResearchPhaseAnnotationSet, ResearchPhaseSegment, ResearchVideo, User
from app.services.download_filenames import build_attachment_content_disposition, sanitize_filename
from app.services.research_phase_export_service import (
    build_phase_json_export,
    iter_phase_framewise_csv,
    iter_phase_segment_csv,
    serialize_phase_json_export,
)
from tests._research_phase_test_utils import create_phase_session_factory, seed_phase_data


@pytest.fixture()
def phase_export_context(tmp_path):
    engine, session_factory = create_phase_session_factory(tmp_path)
    seeded = seed_phase_data(session_factory)
    try:
        yield session_factory, seeded
    finally:
        engine.dispose()


def create_annotation_set(
    session_factory,
    seeded,
    *,
    username: str,
    status: str = "draft",
    revision: int = 1,
) -> int:
    with session_factory() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            user = User(username=username, email=f"{username}@example.com", full_name=username.title())
            db.add(user)
            db.flush()

        annotation_set = ResearchPhaseAnnotationSet(
            video_id=seeded.video_id,
            protocol_id=seeded.active_default_protocol_id,
            annotator_id=user.id,
            status=status,
            revision=revision,
        )
        db.add(annotation_set)
        db.commit()
        db.refresh(annotation_set)
        return annotation_set.id


def add_segment(
    session_factory,
    *,
    annotation_set_id: int,
    phase_label_id: int,
    start_frame: int,
    end_frame_exclusive: int | None,
    source: str = "manual",
    confidence: float | None = None,
    notes: str | None = None,
) -> int:
    with session_factory() as db:
        segment = ResearchPhaseSegment(
            annotation_set_id=annotation_set_id,
            phase_label_id=phase_label_id,
            start_frame=start_frame,
            end_frame_exclusive=end_frame_exclusive,
            source=source,
            confidence=confidence,
            notes=notes,
        )
        db.add(segment)
        db.commit()
        db.refresh(segment)
        return segment.id


def update_video(session_factory, video_id: int, **changes) -> None:
    with session_factory() as db:
        video = db.get(ResearchVideo, video_id)
        assert video is not None
        for key, value in changes.items():
            setattr(video, key, value)
        db.commit()


def get_annotation_set_snapshot(session_factory, annotation_set_id: int) -> tuple[str, int, list[tuple[int, int | None, int]]]:
    with session_factory() as db:
        annotation_set = db.get(ResearchPhaseAnnotationSet, annotation_set_id)
        assert annotation_set is not None
        segments = db.scalars(
            select(ResearchPhaseSegment)
            .where(ResearchPhaseSegment.annotation_set_id == annotation_set_id)
            .order_by(ResearchPhaseSegment.start_frame, ResearchPhaseSegment.id)
        ).all()
        return (
            annotation_set.status,
            annotation_set.revision,
            [(segment.start_frame, segment.end_frame_exclusive, segment.phase_label_id) for segment in segments],
        )


def consume_bytes(iterator) -> bytes:
    return b"".join(iterator)


def parse_csv_rows(csv_bytes: bytes) -> list[list[str]]:
    text = csv_bytes.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


def test_build_phase_json_export_returns_expected_structure_without_paths(phase_export_context) -> None:
    session_factory, seeded = phase_export_context
    update_video(session_factory, seeded.video_id, name="张玉柱 手术")

    with session_factory() as db:
        export_result = build_phase_json_export(db, seeded.set_reader_id)

    payload = export_result.payload
    json_text = serialize_phase_json_export(payload).decode("utf-8")
    assert payload["schema_version"] == 1
    assert payload["video"]["id"] == seeded.video_id
    assert payload["annotation_set"]["id"] == seeded.set_reader_id
    assert payload["protocol"]["labels"][0]["key"] == "idle"
    assert [segment["start_frame"] for segment in payload["segments"]] == [10, 120]
    assert payload["segments"][1]["end_frame_exclusive"] is None
    assert payload["segments"][1]["end_time_ms"] is None
    assert payload["segments"][1]["duration_frames"] is None
    assert payload["validation"]["annotation_set_id"] == seeded.set_reader_id
    assert "张玉柱 手术" in json_text
    assert "\\u5f20" not in json_text
    assert "file_path" not in json_text
    assert "thumbnail_path" not in json_text
    expected_filename = f"{sanitize_filename('张玉柱 手术', fallback=f'video_{seeded.video_id}')}_phases.json"
    assert export_result.filename == expected_filename
    assert export_result.headers["Content-Disposition"] == build_attachment_content_disposition(
        expected_filename,
        f"video_{seeded.video_id}_phases.json",
    )


def test_segment_csv_export_uses_expected_columns_and_escapes_notes(phase_export_context) -> None:
    session_factory, seeded = phase_export_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="segment_csv")
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=0,
        end_frame_exclusive=10,
        notes='line1,"quoted"\nline2,comma',
    )
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["viscoelastic"],
        start_frame=10,
        end_frame_exclusive=None,
    )

    with session_factory() as db:
        export_result = iter_phase_segment_csv(db, annotation_set_id)
        csv_bytes = consume_bytes(export_result.iterator)

    assert csv_bytes.startswith(b"\xef\xbb\xbf")
    rows = parse_csv_rows(csv_bytes)
    assert rows[0] == [
        "video_id",
        "video_name",
        "original_filename",
        "annotation_set_id",
        "annotation_status",
        "revision",
        "protocol_id",
        "protocol_name",
        "protocol_version",
        "annotator_id",
        "annotator_username",
        "segment_id",
        "phase_label_id",
        "phase_key",
        "phase_name",
        "start_frame",
        "end_frame_exclusive",
        "start_time_ms",
        "end_time_ms",
        "duration_frames",
        "duration_ms",
        "source",
        "confidence",
        "notes",
    ]
    assert rows[1][13:17] == ["incision", "Incision", "0", "10"]
    assert rows[1][23] == 'line1,"quoted"\nline2,comma'
    assert rows[2][13:17] == ["viscoelastic", "Viscoelastic Injection", "10", ""]
    assert rows[2][18:21] == ["", "", ""]


def test_framewise_csv_export_respects_boundaries_gaps_open_segments_and_validation_headers(
    phase_export_context,
) -> None:
    session_factory, seeded = phase_export_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="framewise_basic")
    update_video(session_factory, seeded.video_id, frame_count=6, fps=2.0)
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=1,
        end_frame_exclusive=3,
    )
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["viscoelastic"],
        start_frame=4,
        end_frame_exclusive=None,
    )

    with session_factory() as db:
        export_result = iter_phase_framewise_csv(db, annotation_set_id)
        csv_bytes = consume_bytes(export_result.iterator)

    rows = parse_csv_rows(csv_bytes)
    assert len(rows) == 7
    assert rows[1] == ["0", "0", "unlabeled", "Unlabeled", "", "", "draft"]
    assert rows[2] == ["1", "500", "incision", "Incision", str(seeded.active_default_label_ids["incision"]), rows[2][5], "draft"]
    assert rows[3][0:4] == ["2", "1000", "incision", "Incision"]
    assert rows[4] == ["3", "1500", "unlabeled", "Unlabeled", "", "", "draft"]
    assert rows[5][0:4] == ["4", "2000", "viscoelastic", "Viscoelastic Injection"]
    assert rows[6][0:4] == ["5", "2500", "viscoelastic", "Viscoelastic Injection"]
    assert export_result.headers["X-Phase-Validation-Errors"] == "1"
    assert export_result.headers["X-Phase-Validation-Warnings"] == "3"


def test_framewise_csv_export_uses_first_matching_segment_for_overlaps(phase_export_context) -> None:
    session_factory, seeded = phase_export_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="framewise_overlap")
    update_video(session_factory, seeded.video_id, frame_count=6, fps=2.0)
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=0,
        end_frame_exclusive=5,
    )
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["incision"],
        start_frame=2,
        end_frame_exclusive=4,
    )

    with session_factory() as db:
        export_result = iter_phase_framewise_csv(db, annotation_set_id)
        rows = parse_csv_rows(consume_bytes(export_result.iterator))

    assert rows[3][2] == "idle"
    assert rows[4][2] == "idle"
    assert export_result.headers["X-Phase-Validation-Errors"] == "1"


def test_framewise_csv_export_leaves_timestamp_blank_when_fps_invalid(phase_export_context) -> None:
    session_factory, seeded = phase_export_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="framewise_no_fps")
    update_video(session_factory, seeded.video_id, frame_count=3, fps=None)
    add_segment(
        session_factory,
        annotation_set_id=annotation_set_id,
        phase_label_id=seeded.active_default_label_ids["idle"],
        start_frame=0,
        end_frame_exclusive=3,
    )

    with session_factory() as db:
        export_result = iter_phase_framewise_csv(db, annotation_set_id)
        rows = parse_csv_rows(consume_bytes(export_result.iterator))

    assert rows[1][1] == ""
    assert rows[2][1] == ""
    assert rows[3][1] == ""


def test_framewise_generator_is_lazy_and_session_independent_for_large_videos(phase_export_context) -> None:
    session_factory, seeded = phase_export_context
    annotation_set_id = create_annotation_set(session_factory, seeded, username="framewise_large")
    update_video(session_factory, seeded.video_id, frame_count=50_000, fps=25.0)
    for index in range(0, 50_000, 2500):
        end_frame = min(index + 1800, 50_000)
        add_segment(
            session_factory,
            annotation_set_id=annotation_set_id,
            phase_label_id=seeded.active_default_label_ids["incision" if (index // 2500) % 2 else "idle"],
            start_frame=index,
            end_frame_exclusive=end_frame,
        )

    with session_factory() as db:
        export_result = iter_phase_framewise_csv(db, annotation_set_id)
        iterator = export_result.iterator

    line_count = 0
    chunk_count = 0
    trailing = ""
    for chunk in iterator:
        chunk_count += 1
        text = trailing + chunk.decode("utf-8")
        parts = text.split("\n")
        trailing = parts.pop()
        line_count += len(parts)
    if trailing:
        line_count += 1

    assert line_count == 50_001
    assert chunk_count > 2


def test_export_headers_use_sanitized_utf8_filenames(phase_export_context) -> None:
    session_factory, seeded = phase_export_context
    update_video(session_factory, seeded.video_id, name="张玉柱\r\n 手术/Case")

    with session_factory() as db:
        json_export = build_phase_json_export(db, seeded.set_reader_id)
        csv_export = iter_phase_segment_csv(db, seeded.set_reader_id)

    safe_name = sanitize_filename("张玉柱\r\n 手术/Case", fallback=f"video_{seeded.video_id}")
    expected_json_filename = f"{safe_name}_phases.json"
    expected_csv_filename = f"{safe_name}_phase_segments.csv"
    assert json_export.headers["Content-Disposition"] == build_attachment_content_disposition(
        expected_json_filename,
        f"video_{seeded.video_id}_phases.json",
    )
    assert csv_export.headers["Content-Disposition"] == build_attachment_content_disposition(
        expected_csv_filename,
        f"video_{seeded.video_id}_phase_segments.csv",
    )


def test_exports_do_not_modify_state_or_call_commit_flush(phase_export_context, monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory, seeded = phase_export_context
    before_snapshot = get_annotation_set_snapshot(session_factory, seeded.set_reader_id)

    with session_factory() as db:
        def fail_commit() -> None:
            raise AssertionError("export should not call commit")

        def fail_flush() -> None:
            raise AssertionError("export should not call flush")

        monkeypatch.setattr(db, "commit", fail_commit)
        monkeypatch.setattr(db, "flush", fail_flush)
        json_export = build_phase_json_export(db, seeded.set_reader_id)
        segment_csv = iter_phase_segment_csv(db, seeded.set_reader_id)
        framewise_csv = iter_phase_framewise_csv(db, seeded.set_reader_id)
        assert json_export.payload["annotation_set"]["id"] == seeded.set_reader_id
        assert consume_bytes(segment_csv.iterator).startswith(b"\xef\xbb\xbf")
        assert consume_bytes(framewise_csv.iterator).startswith(b"\xef\xbb\xbf")

    after_snapshot = get_annotation_set_snapshot(session_factory, seeded.set_reader_id)
    assert before_snapshot == after_snapshot
