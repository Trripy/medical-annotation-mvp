from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import re

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app import models  # noqa: F401
from app.core.config import settings
from app.db.base import Base


BACKEND_DIR = Path(__file__).resolve().parents[1]
PHASE_TABLES = {
    "research_phase_protocols",
    "research_phase_labels",
    "research_phase_annotation_sets",
    "research_phase_segments",
}
BASELINE_REVISION = "20260630_0013"
HEAD_REVISION = "20260722_0014"


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


def create_pre_phase_schema(database_url: str) -> None:
    engine = create_engine(database_url)
    tables = [
        table
        for name, table in Base.metadata.tables.items()
        if not name.startswith("research_phase_") and not name.startswith("research_skill_")
    ]
    Base.metadata.create_all(engine, tables=tables)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.exec_driver_sql(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            (BASELINE_REVISION,),
        )
    engine.dispose()


def run_upgrade(database_url: str, target_revision: str = "head") -> None:
    config = build_alembic_config(database_url)
    with override_database_url(database_url):
        command.upgrade(config, target_revision)


def run_downgrade(database_url: str, target_revision: str) -> None:
    config = build_alembic_config(database_url)
    with override_database_url(database_url):
        command.downgrade(config, target_revision)


def read_version(database_url: str) -> str:
    engine = create_engine(database_url)
    with engine.connect() as conn:
        version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    engine.dispose()
    return version


def read_protocol_and_labels(database_url: str):
    engine = create_engine(database_url)
    with engine.connect() as conn:
        protocol = conn.execute(
            sa.text(
                """
                SELECT id, name, version, description, status, is_default, created_by_id
                FROM research_phase_protocols
                """
            )
        ).mappings().all()
        labels = conn.execute(
            sa.text(
                """
                SELECT key, name, color, display_order, shortcut, is_active
                FROM research_phase_labels
                ORDER BY display_order
                """
            )
        ).mappings().all()
    engine.dispose()
    return protocol, labels


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


def test_research_phase_migration_upgrade_adds_default_protocol_and_labels(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'phase_upgrade.db'}"
    create_pre_phase_schema(database_url)

    before_research_videos = table_columns(database_url, "research_videos")
    before_annotations = table_columns(database_url, "annotations")

    run_upgrade(database_url, HEAD_REVISION)

    engine = create_engine(database_url)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    engine.dispose()
    assert PHASE_TABLES.issubset(table_names)
    assert read_version(database_url) == HEAD_REVISION

    protocol_rows, label_rows = read_protocol_and_labels(database_url)
    assert len(protocol_rows) == 1
    protocol = protocol_rows[0]
    assert protocol["name"] == "Cataract Surgery Phases"
    assert protocol["version"] == 1
    assert protocol["description"] == "Default cataract surgery phase protocol."
    assert protocol["status"] == "active"
    assert bool(protocol["is_default"]) is True
    assert protocol["created_by_id"] is None

    assert len(label_rows) == 13
    assert [label["display_order"] for label in label_rows] == list(range(13))
    assert len({label["key"] for label in label_rows}) == 13
    assert len({label["name"] for label in label_rows}) == 13
    assert len({label["color"] for label in label_rows}) == 13
    assert all(re.fullmatch(r"#[0-9a-fA-F]{6}", label["color"]) for label in label_rows)

    expected_labels = [
        ("idle", "Idle", "#64748b"),
        ("incision", "Incision", "#ff7a1a"),
        ("viscoelastic", "Viscoelastic Injection", "#1f9fe5"),
        ("capsulorhexis", "Capsulorhexis", "#22c55e"),
        ("hydrodissection", "Hydrodissection", "#8b5cf6"),
        ("phacoemulsification", "Phacoemulsification", "#ef4444"),
        ("irrigation_aspiration", "Irrigation / Aspiration", "#eab308"),
        ("capsule_polishing", "Capsule Polishing", "#14b8a6"),
        ("lens_implantation", "Lens Implantation", "#ec4899"),
        ("lens_positioning", "Lens Positioning", "#6366f1"),
        ("viscoelastic_suction", "Viscoelastic Suction", "#84cc16"),
        ("anterior_chamber_flushing", "Anterior Chamber Flushing", "#06b6d4"),
        ("tonifying_antibiotics", "Tonifying / Antibiotics", "#a16207"),
    ]
    assert [(row["key"], row["name"], row["color"]) for row in label_rows] == expected_labels

    after_research_videos = table_columns(database_url, "research_videos")
    after_annotations = table_columns(database_url, "annotations")
    assert after_research_videos == before_research_videos
    assert after_annotations == before_annotations


def test_research_phase_migration_downgrade_removes_phase_tables_and_keeps_old_tables(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'phase_downgrade.db'}"
    create_pre_phase_schema(database_url)
    before_research_videos = table_columns(database_url, "research_videos")
    before_annotations = table_columns(database_url, "annotations")
    run_upgrade(database_url, HEAD_REVISION)
    run_downgrade(database_url, BASELINE_REVISION)

    engine = create_engine(database_url)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    engine.dispose()
    assert PHASE_TABLES.isdisjoint(table_names)
    assert "research_videos" in table_names
    assert "annotations" in table_names
    assert read_version(database_url) == BASELINE_REVISION

    after_research_videos = table_columns(database_url, "research_videos")
    after_annotations = table_columns(database_url, "annotations")
    assert after_research_videos == before_research_videos
    assert after_annotations == before_annotations
