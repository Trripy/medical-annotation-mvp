from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app import models  # noqa: F401
from app.core.config import settings
from app.db.base import Base

BACKEND_DIR = Path(__file__).resolve().parents[1]
PHASE_HEAD_REVISION = "20260722_0014"
SKILL_HEAD_REVISION = "20260722_0015"
SKILL_TABLES = {
    "research_skill_rubrics",
    "research_skill_criteria",
    "research_skill_criterion_phase_labels",
    "research_skill_assessments",
    "research_skill_scores",
    "research_skill_evidence",
}
PHASE_TABLES = {
    "research_phase_protocols",
    "research_phase_labels",
    "research_phase_annotation_sets",
    "research_phase_segments",
}


@contextmanager
def override_database_url(database_url: str):
    original = settings.__dict__.get("database_url", None)
    had_original = "database_url" in settings.__dict__
    settings.database_url = database_url
    try:
        yield
    finally:
        if had_original:
            settings.database_url = original
        else:
            settings.__dict__.pop("database_url", None)


def build_alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("prepend_sys_path", str(BACKEND_DIR))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def create_pre_skill_schema(database_url: str) -> None:
    engine = create_engine(database_url)
    tables = [
        table
        for name, table in Base.metadata.tables.items()
        if not name.startswith("research_skill_")
    ]
    Base.metadata.create_all(engine, tables=tables)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.exec_driver_sql("INSERT INTO alembic_version (version_num) VALUES (?)", (PHASE_HEAD_REVISION,))
    engine.dispose()


def read_version(database_url: str) -> str:
    engine = create_engine(database_url)
    with engine.connect() as conn:
        version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    engine.dispose()
    return version


def table_columns(database_url: str, table_name: str) -> list[tuple[str, str, bool]]:
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        return [
            (column["name"], str(column["type"]), column["nullable"])
            for column in inspector.get_columns(table_name)
        ]
    finally:
        engine.dispose()


def test_research_skill_migration_upgrade_and_downgrade_only_affect_skill_tables(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'skill_migration.db'}"
    create_pre_skill_schema(database_url)
    before_research_videos = table_columns(database_url, "research_videos")
    before_annotations = table_columns(database_url, "annotations")
    before_users = table_columns(database_url, "users")

    config = build_alembic_config(database_url)
    with override_database_url(database_url):
        command.upgrade(config, SKILL_HEAD_REVISION)

    engine = create_engine(database_url)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    with engine.connect() as conn:
        rubric_count = conn.execute(sa.text("SELECT COUNT(*) FROM research_skill_rubrics")).scalar_one()
    engine.dispose()

    assert SKILL_TABLES.issubset(table_names)
    assert PHASE_TABLES.issubset(table_names)
    assert read_version(database_url) == SKILL_HEAD_REVISION
    assert rubric_count == 0
    assert table_columns(database_url, "research_videos") == before_research_videos
    assert table_columns(database_url, "annotations") == before_annotations
    assert table_columns(database_url, "users") == before_users

    with override_database_url(database_url):
        command.downgrade(config, PHASE_HEAD_REVISION)

    engine = create_engine(database_url)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    engine.dispose()
    assert SKILL_TABLES.isdisjoint(table_names)
    assert PHASE_TABLES.issubset(table_names)
    assert read_version(database_url) == PHASE_HEAD_REVISION
    assert table_columns(database_url, "research_videos") == before_research_videos
    assert table_columns(database_url, "annotations") == before_annotations
    assert table_columns(database_url, "users") == before_users
