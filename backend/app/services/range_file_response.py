from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator
import asyncio

from fastapi import HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse

from app.services.download_filenames import build_inline_content_disposition

DEFAULT_RANGE_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


class RangeNotSatisfiableError(ValueError):
    pass


def parse_range_header(range_header: str | None, file_size: int) -> ByteRange | None:
    if range_header is None:
        return None

    if file_size <= 0:
        raise RangeNotSatisfiableError("Range requests are not valid for empty files")

    header = range_header.strip()
    if not header:
        raise RangeNotSatisfiableError("Range header is empty")

    unit, separator, raw_value = header.partition("=")
    if separator != "=" or unit.strip().lower() != "bytes":
        raise RangeNotSatisfiableError("Only byte ranges are supported")

    value = raw_value.strip()
    if not value or "," in value:
        raise RangeNotSatisfiableError("Only a single byte range is supported")

    raw_start, dash, raw_end = value.partition("-")
    if dash != "-":
        raise RangeNotSatisfiableError("Range header is malformed")

    start_text = raw_start.strip()
    end_text = raw_end.strip()

    if start_text:
        if not start_text.isdigit():
            raise RangeNotSatisfiableError("Range start must be a non-negative integer")

        start = int(start_text)
        if start >= file_size:
            raise RangeNotSatisfiableError("Range start exceeds file size")

        if end_text:
            if not end_text.isdigit():
                raise RangeNotSatisfiableError("Range end must be a non-negative integer")
            end = int(end_text)
            if end < start:
                raise RangeNotSatisfiableError("Range end precedes range start")
            end = min(end, file_size - 1)
        else:
            end = file_size - 1

        return ByteRange(start=start, end=end)

    if not end_text or not end_text.isdigit():
        raise RangeNotSatisfiableError("Suffix byte range is malformed")

    suffix_length = int(end_text)
    if suffix_length <= 0:
        raise RangeNotSatisfiableError("Suffix byte range must be positive")

    length = min(suffix_length, file_size)
    return ByteRange(start=file_size - length, end=file_size - 1)


async def iter_file_range(
    file_path: Path,
    start: int,
    length: int,
    chunk_size: int = DEFAULT_RANGE_CHUNK_SIZE,
) -> AsyncIterator[bytes]:
    remaining = length
    if remaining <= 0:
        return

    with file_path.open("rb") as file_obj:
        file_obj.seek(start)
        while remaining > 0:
            chunk = file_obj.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
            if remaining > 0:
                await asyncio.sleep(0)


def create_range_file_response(
    *,
    request: Request,
    file_path: Path,
    media_type: str,
    filename: str | None = None,
    chunk_size: int = DEFAULT_RANGE_CHUNK_SIZE,
) -> Response:
    if not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    file_size = file_path.stat().st_size
    safe_filename = filename or file_path.name
    suffix = Path(safe_filename).suffix
    disposition = build_inline_content_disposition(
        safe_filename,
        f"inline{suffix}" if suffix else "inline",
    )
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": disposition,
    }

    try:
        byte_range = parse_range_header(request.headers.get("range"), file_size)
    except RangeNotSatisfiableError as exc:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail="Requested range is not satisfiable",
            headers={
                **headers,
                "Content-Range": f"bytes */{file_size}",
            },
        ) from exc

    if byte_range is None:
        full_headers = {
            **headers,
            "Content-Length": str(file_size),
        }
        if request.method == "HEAD":
            return Response(status_code=status.HTTP_200_OK, media_type=media_type, headers=full_headers)
        return StreamingResponse(
            iter_file_range(file_path, start=0, length=file_size, chunk_size=chunk_size),
            status_code=status.HTTP_200_OK,
            media_type=media_type,
            headers=full_headers,
        )

    range_headers = {
        **headers,
        "Content-Range": f"bytes {byte_range.start}-{byte_range.end}/{file_size}",
        "Content-Length": str(byte_range.length),
    }
    if request.method == "HEAD":
        return Response(status_code=status.HTTP_206_PARTIAL_CONTENT, media_type=media_type, headers=range_headers)
    return StreamingResponse(
        iter_file_range(file_path, start=byte_range.start, length=byte_range.length, chunk_size=chunk_size),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=media_type,
        headers=range_headers,
    )
