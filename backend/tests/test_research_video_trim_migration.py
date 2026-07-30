from __future__ import annotations

from pathlib import Path


MIGRATION_PATH = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20260728_0016_add_research_video_trim_provenance.py"


def test_research_video_trim_migration_is_linear_and_additive() -> None:
    source = MIGRATION_PATH.read_text()
    assert 'revision: str = "20260728_0016"' in source
    assert 'down_revision: str | None = "20260722_0015"' in source
    assert 'sa.Column("source_video_id"' in source
    assert 'sa.Column("origin_type"' in source
    assert 'sa.Column("trim_start_frame"' in source
    assert 'sa.Column("trim_end_frame_exclusive"' in source
    assert 'ondelete="SET NULL"' in source
    assert "ix_research_videos_source_video_id" in source
    assert "ix_research_videos_source_trim_processing" in source
    assert "origin_type != 'trimmed' OR (trim_start_frame IS NOT NULL AND trim_end_frame_exclusive IS NOT NULL)" in source
    assert "source_video_id IS NOT NULL" not in source


def test_research_video_trim_migration_downgrade_removes_only_added_fields() -> None:
    source = MIGRATION_PATH.read_text()
    assert 'op.drop_column("research_videos", "trim_end_frame_exclusive")' in source
    assert 'op.drop_column("research_videos", "trim_start_frame")' in source
    assert 'op.drop_column("research_videos", "origin_type")' in source
    assert 'op.drop_column("research_videos", "source_video_id")' in source
    assert "drop_table" not in source
