from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from fastapi import HTTPException, status

from app.core.config import settings
from app.services.video_import import is_supported_research_video_filename

MAX_BROWSE_ENTRIES = 2000
MAX_SCAN_DEPTH = 8
MAX_SCAN_VIDEOS = 2000


@dataclass(frozen=True)
class ServerImportRoot:
    id: str
    name: str
    path: Path


def parse_server_import_roots() -> dict[str, ServerImportRoot]:
    raw = settings.research_video_import_roots.strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server video import roots are misconfigured.",
        ) from exc

    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server video import roots are misconfigured.",
        )

    roots: dict[str, ServerImportRoot] = {}
    for root_id, root_path in parsed.items():
        if not isinstance(root_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", root_id):
            continue
        if not isinstance(root_path, str) or not root_path:
            continue
        resolved = Path(root_path).expanduser().resolve(strict=False)
        if resolved.exists() and resolved.is_dir() and not resolved.is_symlink():
            roots[root_id] = ServerImportRoot(id=root_id, name=root_id, path=resolved)
    return roots


def resolve_root(root_id: str) -> ServerImportRoot:
    root = parse_server_import_roots().get(root_id)
    if root is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server import root not found.")
    return root


def resolve_import_path(root_id: str, relative_path: str | None, *, expected: str) -> Path:
    root = resolve_root(root_id)
    normalized_relative = normalize_relative_path(relative_path)
    candidate_raw = root.path / normalized_relative
    if candidate_raw.is_symlink() or any(part.is_symlink() for part in _path_ancestors(candidate_raw, root.path)):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid server import path.")

    candidate = candidate_raw.resolve(strict=False)

    try:
        candidate.relative_to(root.path)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The selected path is outside the allowed import root.",
        ) from exc

    if expected == "directory":
        if not candidate.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source directory not found.")
        if not candidate.is_dir():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The selected path is not a directory.")
    elif expected == "file":
        if not candidate.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source file not found.")
        if not candidate.is_file():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The selected path is not a video file.")
        if not is_supported_research_video_filename(candidate.name):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported video format.")
    return candidate


def normalize_relative_path(relative_path: str | None) -> Path:
    if not relative_path:
        return Path()
    decoded = unquote(relative_path).replace("\\", "/")
    path = Path(decoded)
    if path.is_absolute() or any(part in {"..", ""} for part in path.parts):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid server import path.")
    return path


def relative_to_root(path: Path, root: ServerImportRoot) -> str:
    relative = path.relative_to(root.path)
    return "" if str(relative) == "." else relative.as_posix()


def safe_parent_relative_path(relative_path: str) -> str | None:
    if not relative_path:
        return None
    parent = Path(relative_path).parent
    return "" if str(parent) == "." else parent.as_posix()


def browse_directory(root_id: str, relative_path: str | None) -> dict:
    root = resolve_root(root_id)
    directory = resolve_import_path(root_id, relative_path, expected="directory")
    directories: list[dict] = []
    videos: list[dict] = []

    try:
        entries = list(os.scandir(directory))
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Source directory is unreadable.") from exc

    for entry in entries[:MAX_BROWSE_ENTRIES]:
        if entry.name.startswith(".") or entry.is_symlink():
            continue
        try:
            if entry.is_dir(follow_symlinks=False):
                entry_path = Path(entry.path).resolve(strict=False)
                directories.append({"name": entry.name, "relative_path": relative_to_root(entry_path, root)})
            elif entry.is_file(follow_symlinks=False) and is_supported_research_video_filename(entry.name):
                stat = entry.stat(follow_symlinks=False)
                entry_path = Path(entry.path).resolve(strict=False)
                videos.append(_video_entry(root, entry_path, stat.st_size, stat.st_mtime))
        except OSError:
            continue

    return {
        "root_id": root.id,
        "relative_path": relative_to_root(directory, root),
        "parent_relative_path": safe_parent_relative_path(relative_to_root(directory, root)),
        "directories": sorted(directories, key=lambda item: _natural_key(item["name"])),
        "videos": sorted(videos, key=lambda item: _natural_key(item["name"])),
        "truncated": len(entries) > MAX_BROWSE_ENTRIES,
    }


def scan_folder(root_id: str, relative_path: str | None, *, recursive: bool) -> dict:
    root = resolve_root(root_id)
    directory = resolve_import_path(root_id, relative_path, expected="directory")
    videos: list[dict] = []
    unsupported_count = 0
    unreadable_count = 0
    truncated = False

    stack: list[tuple[Path, int]] = [(directory, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > MAX_SCAN_DEPTH:
            truncated = True
            continue
        try:
            entries = list(os.scandir(current))
        except OSError:
            unreadable_count += 1
            continue

        for entry in sorted(entries, key=lambda item: _natural_key(item.name)):
            if entry.name.startswith(".") or entry.is_symlink():
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    if recursive:
                        stack.append((Path(entry.path).resolve(strict=False), depth + 1))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                if not is_supported_research_video_filename(entry.name):
                    unsupported_count += 1
                    continue
                stat = entry.stat(follow_symlinks=False)
                videos.append(_video_entry(root, Path(entry.path).resolve(strict=False), stat.st_size, stat.st_mtime))
                if len(videos) >= MAX_SCAN_VIDEOS:
                    truncated = True
                    stack.clear()
                    break
            except OSError:
                unreadable_count += 1

    videos = sorted(videos, key=lambda item: _natural_key(item["relative_path"]))
    return {
        "root_id": root.id,
        "relative_path": relative_to_root(directory, root),
        "recursive": recursive,
        "video_count": len(videos),
        "total_size_bytes": sum(video["size_bytes"] for video in videos),
        "videos": videos,
        "unsupported_count": unsupported_count,
        "unreadable_count": unreadable_count,
        "truncated": truncated,
    }


def _video_entry(root: ServerImportRoot, path: Path, size_bytes: int, modified_timestamp: float) -> dict:
    return {
        "name": path.name,
        "relative_path": relative_to_root(path, root),
        "size_bytes": size_bytes,
        "modified_at": datetime.fromtimestamp(modified_timestamp, tz=timezone.utc).isoformat(),
        "extension": path.suffix.lower(),
    }


def _natural_key(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def _path_ancestors(path: Path, root: Path) -> list[Path]:
    ancestors: list[Path] = []
    current = path
    while current != root and current.parent != current:
        ancestors.append(current)
        current = current.parent
    return ancestors
