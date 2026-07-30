from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import research_server_video_import as server_import_api
from app.core.config import settings
from app.db.base import Base
from app.models.research import ResearchVideo
from app.services import video_import
from app.services.server_video_import import browse_directory, parse_server_import_roots, resolve_import_path, scan_folder


@pytest.fixture()
def server_import_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)

    source_root = tmp_path / "source"
    storage_root = tmp_path / "managed"
    source_root.mkdir()
    storage_root.mkdir()

    original_roots = settings.research_video_import_roots
    original_storage = settings.local_storage_root
    settings.research_video_import_roots = json.dumps({"dataset": str(source_root)})
    settings.local_storage_root = str(storage_root)

    def fake_extract(video_path: str | Path, output_dir: Path, *, thumbnail_path: Path | None = None) -> dict:
        output_dir.mkdir(parents=True, exist_ok=True)
        frame_path = output_dir / "000000.jpg"
        frame_path.write_bytes(b"frame")
        if thumbnail_path:
            thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
            thumbnail_path.write_bytes(b"thumb")
        return {
            "width": 16,
            "height": 9,
            "fps": 25.0,
            "frame_count": 1,
            "duration_ms": 40,
            "frames": [{
                "frame_index": 0,
                "timestamp_ms": 0,
                "filename": "000000.jpg",
                "file_path": str(frame_path),
                "width": 16,
                "height": 9,
            }],
            "warnings": [],
        }

    monkeypatch.setattr(video_import, "extract_video_frames", fake_extract)
    try:
        yield SessionLocal, source_root, storage_root
    finally:
        settings.research_video_import_roots = original_roots
        settings.local_storage_root = original_storage
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_roots_disabled_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    original = settings.research_video_import_roots
    settings.research_video_import_roots = ""
    try:
        payload = server_import_api.list_server_video_import_roots()
    finally:
        settings.research_video_import_roots = original

    assert payload.enabled is False
    assert payload.roots == []


def test_roots_do_not_expose_absolute_paths(server_import_context) -> None:
    _session_factory, source_root, _storage_root = server_import_context
    roots = server_import_api.list_server_video_import_roots().model_dump()

    assert roots == {"enabled": True, "roots": [{"id": "dataset", "name": "dataset"}]}
    assert str(source_root) not in json.dumps(roots)


def test_browse_root_filters_and_sorts_entries(server_import_context) -> None:
    _session_factory, source_root, _storage_root = server_import_context
    (source_root / "case10.mp4").write_bytes(b"video10")
    (source_root / "case2.MP4").write_bytes(b"video2")
    (source_root / "notes.txt").write_text("ignore")
    (source_root / ".hidden.mp4").write_bytes(b"ignore")
    (source_root / "z_folder").mkdir()
    (source_root / "a_folder").mkdir()

    payload = browse_directory("dataset", "")

    assert [item["name"] for item in payload["directories"]] == ["a_folder", "z_folder"]
    assert [item["name"] for item in payload["videos"]] == ["case2.MP4", "case10.mp4"]
    assert "notes.txt" not in json.dumps(payload)
    assert str(source_root) not in json.dumps(payload)


def test_browse_subdirectory_and_parent(server_import_context) -> None:
    _session_factory, source_root, _storage_root = server_import_context
    nested = source_root / "cataract" / "2026"
    nested.mkdir(parents=True)
    (nested / "case001.mp4").write_bytes(b"video")

    payload = browse_directory("dataset", "cataract/2026")

    assert payload["relative_path"] == "cataract/2026"
    assert payload["parent_relative_path"] == "cataract"
    assert payload["videos"][0]["relative_path"] == "cataract/2026/case001.mp4"


def test_path_escape_and_encoded_escape_are_rejected(server_import_context) -> None:
    with pytest.raises(HTTPException) as plain:
        resolve_import_path("dataset", "../outside.mp4", expected="file")
    with pytest.raises(HTTPException) as encoded:
        resolve_import_path("dataset", "%2e%2e/outside.mp4", expected="file")

    assert plain.value.status_code == 422
    assert encoded.value.status_code == 422


def test_symlink_file_and_directory_are_rejected_or_hidden(server_import_context) -> None:
    _session_factory, source_root, _storage_root = server_import_context
    outside = source_root.parent / "outside"
    outside.mkdir()
    (outside / "escape.mp4").write_bytes(b"video")
    (source_root / "linked.mp4").symlink_to(outside / "escape.mp4")
    (source_root / "linked_dir").symlink_to(outside, target_is_directory=True)

    payload = browse_directory("dataset", "")
    assert payload["videos"] == []
    assert payload["directories"] == []
    with pytest.raises(HTTPException) as exc_info:
        resolve_import_path("dataset", "linked.mp4", expected="file")
    assert exc_info.value.status_code == 422


def test_scan_folder_nonrecursive_and_recursive(server_import_context) -> None:
    _session_factory, source_root, _storage_root = server_import_context
    (source_root / "root.mp4").write_bytes(b"1234")
    (source_root / "ignore.txt").write_text("no")
    child = source_root / "child"
    child.mkdir()
    (child / "nested.webm").write_bytes(b"123456")

    flat = scan_folder("dataset", "", recursive=False)
    recursive = scan_folder("dataset", "", recursive=True)

    assert flat["video_count"] == 1
    assert flat["total_size_bytes"] == 4
    assert flat["unsupported_count"] == 1
    assert recursive["video_count"] == 2
    assert [video["relative_path"] for video in recursive["videos"]] == ["child/nested.webm", "root.mp4"]


def test_server_file_import_copies_to_managed_storage_and_preserves_source(server_import_context) -> None:
    session_factory, source_root, storage_root = server_import_context
    source = source_root / "case001.mp4"
    original_bytes = b"server-video-bytes"
    source.write_bytes(original_bytes)

    with session_factory() as db:
        response = server_import_api.import_server_video_file(
            server_import_api.ServerVideoImportFileRequest(root_id="dataset", relative_path="case001.mp4"),
            db,
        )
        video = db.get(ResearchVideo, response.id)

    assert response.original_filename == "case001.mp4"
    assert response.frame_count == 1
    assert source.read_bytes() == original_bytes
    assert video is not None
    managed_path = Path(video.file_path)
    assert managed_path.is_file()
    assert managed_path.read_bytes() == original_bytes
    assert managed_path.parent == storage_root / "research" / "videos" / "raw"
    assert str(source_root) not in response.model_dump_json()


def test_same_basename_imports_use_unique_managed_filenames(server_import_context) -> None:
    session_factory, source_root, _storage_root = server_import_context
    source = source_root / "case001.mp4"
    source.write_bytes(b"server-video-bytes")

    with session_factory() as db:
        first = server_import_api.import_server_video_file(
            server_import_api.ServerVideoImportFileRequest(root_id="dataset", relative_path="case001.mp4"),
            db,
        )
        second = server_import_api.import_server_video_file(
            server_import_api.ServerVideoImportFileRequest(root_id="dataset", relative_path="case001.mp4"),
            db,
        )
        first_video = db.get(ResearchVideo, first.id)
        second_video = db.get(ResearchVideo, second.id)

    assert first_video is not None
    assert second_video is not None
    assert first_video.file_path != second_video.file_path
    assert first.original_filename == second.original_filename == "case001.mp4"


def test_unsupported_file_is_rejected(server_import_context) -> None:
    session_factory, source_root, _storage_root = server_import_context
    (source_root / "case001.txt").write_text("not video")

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            server_import_api.import_server_video_file(
                server_import_api.ServerVideoImportFileRequest(root_id="dataset", relative_path="case001.txt"),
                db,
            )

    assert exc_info.value.status_code == 422


def test_parse_roots_rejects_unknown_root(server_import_context) -> None:
    assert "dataset" in parse_server_import_roots()
    with pytest.raises(HTTPException) as exc_info:
        resolve_import_path("archive", "", expected="directory")
    assert exc_info.value.status_code == 404
