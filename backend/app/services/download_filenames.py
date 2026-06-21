from __future__ import annotations

import re
from urllib.parse import quote

from app.models.job import Job
from app.services.export_scope import normalize_export_scope

_ILLEGAL_FILENAME_CHARACTERS = {"/", "\\", ":", "*", "?", '"', "<", ">", "|"}
_CONTROL_CHARACTERS_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_UNDERSCORE_PATTERN = re.compile(r"_+")
_ASCII_UNSAFE_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(name: str | None, fallback: str) -> str:
    raw_name = (name or "").strip()
    if not raw_name:
        return fallback

    normalized_characters: list[str] = []
    for character in raw_name:
        if character in _ILLEGAL_FILENAME_CHARACTERS or _CONTROL_CHARACTERS_PATTERN.fullmatch(character):
            normalized_characters.append("_")
            continue
        if character.isspace():
            normalized_characters.append("_")
            continue
        normalized_characters.append(character)

    normalized = "".join(normalized_characters)
    normalized = _WHITESPACE_PATTERN.sub("_", normalized)
    normalized = _UNDERSCORE_PATTERN.sub("_", normalized).strip("_.")
    return normalized or fallback


def build_job_export_filename(
    job: Job,
    export_type: str,
    extension: str = ".zip",
    *,
    export_scope: str | None = "all",
) -> str:
    safe_job_name = sanitize_filename(job.name, fallback=f"job_{job.id}")
    scope_suffix = "_annotated_only" if normalize_export_scope(export_scope) == "annotated_only" else ""
    return f"{safe_job_name}_{export_type}{scope_suffix}{extension}"


def build_attachment_content_disposition(filename: str, ascii_fallback: str) -> str:
    ascii_filename = _ascii_filename(filename, ascii_fallback)
    encoded_filename = quote(filename, safe="")
    return f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded_filename}'


def _ascii_filename(filename: str, fallback: str) -> str:
    stem, dot, extension = filename.rpartition(".")
    ascii_stem = (stem or filename).encode("ascii", "ignore").decode("ascii")
    ascii_stem = _ASCII_UNSAFE_PATTERN.sub("_", ascii_stem)
    ascii_stem = _UNDERSCORE_PATTERN.sub("_", ascii_stem).strip("_")

    if not ascii_stem:
        return fallback

    if dot:
        safe_extension = _ASCII_UNSAFE_PATTERN.sub("_", extension).strip("_.")
        return f"{ascii_stem}.{safe_extension}" if safe_extension else ascii_stem

    return ascii_stem
