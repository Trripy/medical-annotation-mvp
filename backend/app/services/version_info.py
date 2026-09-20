"""Read-only build and database metadata for the version endpoint."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent


def _read_version() -> str | None:
    try:
        value = (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _git_value(*arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip() if result.returncode == 0 else ""
    return value or None


def _database_revision(db: Session) -> str | None:
    try:
        value = db.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one_or_none()
    except SQLAlchemyError:
        return None
    return str(value) if value is not None else None


def _database_head() -> str | None:
    try:
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
        heads = ScriptDirectory.from_config(config).get_heads()
    except Exception:
        return None
    return heads[0] if len(heads) == 1 else None


CODE_DATABASE_HEAD = _database_head()


def build_version_info(db: Session) -> dict[str, str | None]:
    """Return best-effort metadata without making version availability a health dependency."""
    return {
        "version": _read_version(),
        "git_commit": _git_value("rev-parse", "HEAD") or os.getenv("APP_GIT_COMMIT") or None,
        "git_describe": _git_value("describe", "--tags", "--always", "--dirty"),
        "database_revision": _database_revision(db),
        "database_head": CODE_DATABASE_HEAD,
    }
