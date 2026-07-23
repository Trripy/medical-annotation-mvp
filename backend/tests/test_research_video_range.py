from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import research as research_api
from app.core.config import settings
from app.db.base import Base
from app.models.research import ResearchVideo
from app.services.range_file_response import ByteRange, parse_range_header


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
        yield SessionLocal, tmp_path
    finally:
        settings.local_storage_root = original_local_storage_root
        Base.metadata.drop_all(engine)
        engine.dispose()


def _create_research_video(
    session_factory: sessionmaker,
    file_path: Path,
    *,
    original_filename: str = "测试视频.mp4",
) -> ResearchVideo:
    with session_factory() as db:
        video = ResearchVideo(
            name="Range Test",
            original_filename=original_filename,
            file_path=str(file_path),
            status="ready",
        )
        db.add(video)
        db.commit()
        db.refresh(video)
        return video


def _write_research_video_file(storage_root: Path, relative_path: str, content: bytes) -> Path:
    file_path = storage_root / "research" / "videos" / relative_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content)
    return file_path


def _make_request(method: str, *, range_header: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if range_header is not None:
        headers.append((b"range", range_header.encode("ascii")))

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": "/api/research/videos/1/file",
            "raw_path": b"/api/research/videos/1/file",
            "query_string": b"",
            "headers": headers,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
    )


async def _collect_response(response, method: str) -> tuple[int, dict[str, str], bytes]:
    messages: list[dict] = []
    disconnect_event = asyncio.Event()
    request_sent = False

    async def receive() -> dict:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnect_event.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": "/api/research/videos/1/file",
        "raw_path": b"/api/research/videos/1/file",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    await response(scope, receive, send)

    start_message = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in start_message["headers"]
    }
    return start_message["status"], headers, body


def test_parse_range_header_supports_expected_single_ranges() -> None:
    assert parse_range_header("bytes=2-5", 10) == ByteRange(start=2, end=5)
    assert parse_range_header("bytes=6-", 10) == ByteRange(start=6, end=9)
    assert parse_range_header("bytes=-4", 10) == ByteRange(start=6, end=9)
    assert parse_range_header("bytes=-100", 10) == ByteRange(start=0, end=9)
    assert parse_range_header(None, 10) is None


@pytest.mark.parametrize(
    ("range_header", "file_size"),
    [
        ("items=1-2", 10),
        ("bytes=abc-def", 10),
        ("bytes=", 10),
        ("bytes=0-1,4-5", 10),
        ("bytes=10-20", 10),
        ("bytes=8-3", 10),
        ("bytes=-0", 10),
        ("bytes=0-1", 0),
    ],
)
def test_parse_range_header_rejects_invalid_ranges(range_header: str, file_size: int) -> None:
    with pytest.raises(ValueError):
        parse_range_header(range_header, file_size)


def test_research_video_file_without_range_returns_full_file(research_db_context) -> None:
    session_factory, storage_root = research_db_context
    file_path = _write_research_video_file(storage_root, "raw/range-test.mp4", b"0123456789")
    video = _create_research_video(session_factory, file_path)

    with session_factory() as db:
        response = research_api.get_research_video_file(_make_request("GET"), video.id, db)
    status_code, headers, body = asyncio.run(_collect_response(response, method="GET"))

    assert status_code == 200
    assert body == b"0123456789"
    assert headers["accept-ranges"] == "bytes"
    assert headers["content-length"] == "10"
    assert "content-range" not in headers
    assert headers["content-disposition"].startswith("inline;")
    assert "filename*=UTF-8''" in headers["content-disposition"]


@pytest.mark.parametrize(
    ("range_header", "expected_body", "expected_content_range", "expected_length"),
    [
        ("bytes=2-5", b"2345", "bytes 2-5/10", "4"),
        ("bytes=6-", b"6789", "bytes 6-9/10", "4"),
        ("bytes=-4", b"6789", "bytes 6-9/10", "4"),
        ("bytes=7-100", b"789", "bytes 7-9/10", "3"),
        ("bytes=-100", b"0123456789", "bytes 0-9/10", "10"),
    ],
)
def test_research_video_file_range_requests_return_partial_content(
    research_db_context,
    range_header: str,
    expected_body: bytes,
    expected_content_range: str,
    expected_length: str,
) -> None:
    session_factory, storage_root = research_db_context
    file_path = _write_research_video_file(storage_root, "raw/range-test.mp4", b"0123456789")
    video = _create_research_video(session_factory, file_path)

    with session_factory() as db:
        response = research_api.get_research_video_file(_make_request("GET", range_header=range_header), video.id, db)
    status_code, headers, body = asyncio.run(_collect_response(response, method="GET"))

    assert status_code == 206
    assert body == expected_body
    assert headers["accept-ranges"] == "bytes"
    assert headers["content-range"] == expected_content_range
    assert headers["content-length"] == expected_length


@pytest.mark.parametrize(
    "range_header",
    [
        "items=1-2",
        "bytes=abc-def",
        "bytes=",
        "bytes=0-1,4-5",
        "bytes=10-20",
        "bytes=8-3",
    ],
)
def test_research_video_file_invalid_ranges_return_416(research_db_context, range_header: str) -> None:
    session_factory, storage_root = research_db_context
    file_path = _write_research_video_file(storage_root, "raw/range-test.mp4", b"0123456789")
    video = _create_research_video(session_factory, file_path)

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            research_api.get_research_video_file(_make_request("GET", range_header=range_header), video.id, db)

    assert exc_info.value.status_code == 416
    assert exc_info.value.headers is not None
    assert exc_info.value.headers["Accept-Ranges"] == "bytes"
    assert exc_info.value.headers["Content-Range"] == "bytes */10"


def test_research_video_file_head_requests_return_headers_without_body(research_db_context) -> None:
    session_factory, storage_root = research_db_context
    file_path = _write_research_video_file(storage_root, "raw/range-test.mp4", b"0123456789")
    video = _create_research_video(session_factory, file_path)

    with session_factory() as db:
        full_response = research_api.head_research_video_file(_make_request("HEAD"), video.id, db)
    full_status, full_headers, full_body = asyncio.run(_collect_response(full_response, method="HEAD"))

    with session_factory() as db:
        partial_response = research_api.head_research_video_file(
            _make_request("HEAD", range_header="bytes=2-5"),
            video.id,
            db,
        )
    partial_status, partial_headers, partial_body = asyncio.run(_collect_response(partial_response, method="HEAD"))

    assert full_status == 200
    assert full_body == b""
    assert full_headers["content-length"] == "10"
    assert full_headers["accept-ranges"] == "bytes"
    assert "content-range" not in full_headers

    assert partial_status == 206
    assert partial_body == b""
    assert partial_headers["content-length"] == "4"
    assert partial_headers["content-range"] == "bytes 2-5/10"
    assert partial_headers["accept-ranges"] == "bytes"


def test_research_video_file_range_supports_large_offsets(research_db_context) -> None:
    session_factory, storage_root = research_db_context
    file_path = storage_root / "research" / "videos" / "raw" / "sparse-large.mp4"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    large_size = 5 * 1024**3
    with file_path.open("wb") as file_obj:
        file_obj.seek(large_size - 1)
        file_obj.write(b"Z")

    video = _create_research_video(session_factory, file_path, original_filename="large.mp4")
    start = large_size - 10
    end = large_size - 1

    with session_factory() as db:
        response = research_api.get_research_video_file(
            _make_request("GET", range_header=f"bytes={start}-{end}"),
            video.id,
            db,
        )
    status_code, headers, body = asyncio.run(_collect_response(response, method="GET"))

    assert status_code == 206
    assert len(body) == 10
    assert body[-1:] == b"Z"
    assert headers["content-length"] == "10"
    assert headers["content-range"] == f"bytes {start}-{end}/{large_size}"
