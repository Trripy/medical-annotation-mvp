from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable

import sqlalchemy as sa

from app.core.config import settings


PHASE_TABLES = [
    "research_phase_protocols",
    "research_phase_labels",
    "research_phase_annotation_sets",
    "research_phase_segments",
]
SKILL_TABLES = [
    "research_skill_rubrics",
    "research_skill_criteria",
    "research_skill_criterion_phase_labels",
    "research_skill_assessments",
    "research_skill_scores",
    "research_skill_evidence",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only Phase/Skill release verification.")
    parser.add_argument("--database-url", default=None, help="Database URL to verify. The URL is never printed.")
    return parser.parse_args()


def print_line(message: str) -> None:
    print(message, flush=True)


def table_exists(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def count_rows(conn: sa.Connection, inspector: sa.Inspector, table_name: str) -> int | None:
    if not table_exists(inspector, table_name):
        return None
    return int(conn.execute(sa.text(f"select count(*) from {table_name}")).scalar_one())


def alembic_revisions(conn: sa.Connection, inspector: sa.Inspector) -> list[str]:
    if not table_exists(inspector, "alembic_version"):
        return []
    return [str(row[0]) for row in conn.execute(sa.text("select version_num from alembic_version order by version_num"))]


def count_orphans(conn: sa.Connection, inspector: sa.Inspector, child: str, child_column: str, parent: str, parent_column: str = "id") -> int:
    if not table_exists(inspector, child) or not table_exists(inspector, parent):
        return 0
    sql = sa.text(
        f"select count(*) from {child} c "
        f"left join {parent} p on c.{child_column} = p.{parent_column} "
        f"where c.{child_column} is not null and p.{parent_column} is null"
    )
    return int(conn.execute(sql).scalar_one())


def orphan_checks(conn: sa.Connection, inspector: sa.Inspector) -> list[tuple[str, int]]:
    checks = [
        ("phase_sets.video", count_orphans(conn, inspector, "research_phase_annotation_sets", "video_id", "research_videos")),
        ("phase_sets.protocol", count_orphans(conn, inspector, "research_phase_annotation_sets", "protocol_id", "research_phase_protocols")),
        ("phase_sets.annotator", count_orphans(conn, inspector, "research_phase_annotation_sets", "annotator_id", "users")),
        ("phase_segments.set", count_orphans(conn, inspector, "research_phase_segments", "annotation_set_id", "research_phase_annotation_sets")),
        ("phase_segments.label", count_orphans(conn, inspector, "research_phase_segments", "phase_label_id", "research_phase_labels")),
        ("skill_rubrics.phase_protocol", count_orphans(conn, inspector, "research_skill_rubrics", "phase_protocol_id", "research_phase_protocols")),
        ("skill_criteria.rubric", count_orphans(conn, inspector, "research_skill_criteria", "rubric_id", "research_skill_rubrics")),
        ("skill_criterion_phase_labels.criterion", count_orphans(conn, inspector, "research_skill_criterion_phase_labels", "criterion_id", "research_skill_criteria")),
        ("skill_criterion_phase_labels.phase_label", count_orphans(conn, inspector, "research_skill_criterion_phase_labels", "phase_label_id", "research_phase_labels")),
        ("skill_assessments.video", count_orphans(conn, inspector, "research_skill_assessments", "video_id", "research_videos")),
        ("skill_assessments.rubric", count_orphans(conn, inspector, "research_skill_assessments", "rubric_id", "research_skill_rubrics")),
        ("skill_assessments.rater", count_orphans(conn, inspector, "research_skill_assessments", "rater_id", "users")),
        ("skill_assessments.phase_set", count_orphans(conn, inspector, "research_skill_assessments", "phase_annotation_set_id", "research_phase_annotation_sets")),
        ("skill_scores.assessment", count_orphans(conn, inspector, "research_skill_scores", "assessment_id", "research_skill_assessments")),
        ("skill_scores.criterion", count_orphans(conn, inspector, "research_skill_scores", "criterion_id", "research_skill_criteria")),
        ("skill_scores.phase_segment", count_orphans(conn, inspector, "research_skill_scores", "phase_segment_id", "research_phase_segments")),
        ("skill_evidence.score", count_orphans(conn, inspector, "research_skill_evidence", "skill_score_id", "research_skill_scores")),
    ]
    return checks


def missing_tables(inspector: sa.Inspector, tables: Iterable[str]) -> list[str]:
    return [table for table in tables if not table_exists(inspector, table)]


def run(database_url: str) -> int:
    engine = sa.create_engine(database_url)
    failures: list[str] = []
    try:
        with engine.connect() as conn:
            inspector = sa.inspect(conn)
            print_line(f"dialect={engine.dialect.name}")
            revisions = alembic_revisions(conn, inspector)
            print_line(f"alembic_revisions={','.join(revisions) if revisions else '<none>'}")
            if revisions != ["20260722_0015"]:
                failures.append("alembic revision is not 20260722_0015")

            missing_phase = missing_tables(inspector, PHASE_TABLES)
            missing_skill = missing_tables(inspector, SKILL_TABLES)
            print_line(f"phase_tables_present={len(PHASE_TABLES) - len(missing_phase)}/4")
            print_line(f"skill_tables_present={len(SKILL_TABLES) - len(missing_skill)}/6")
            if missing_phase:
                failures.append(f"missing phase tables: {', '.join(missing_phase)}")
            if missing_skill:
                failures.append(f"missing skill tables: {', '.join(missing_skill)}")

            phase_protocol_count = count_rows(conn, inspector, "research_phase_protocols")
            phase_label_count = count_rows(conn, inspector, "research_phase_labels")
            skill_rubric_count = count_rows(conn, inspector, "research_skill_rubrics")
            phase_set_count = count_rows(conn, inspector, "research_phase_annotation_sets")
            skill_assessment_count = count_rows(conn, inspector, "research_skill_assessments")
            print_line(f"phase_protocol_count={phase_protocol_count}")
            print_line(f"phase_label_count={phase_label_count}")
            print_line(f"skill_rubric_count={skill_rubric_count}")
            print_line(f"phase_annotation_set_count={phase_set_count}")
            print_line(f"skill_assessment_count={skill_assessment_count}")
            if phase_protocol_count is not None and phase_protocol_count < 1:
                failures.append("default phase protocol is missing")
            if phase_label_count is not None and phase_label_count != 13:
                failures.append("default phase label count is not 13")

            for label, count in orphan_checks(conn, inspector):
                print_line(f"orphan_{label}={count}")
                if count:
                    failures.append(f"orphan rows detected: {label}={count}")
    finally:
        engine.dispose()

    if failures:
        for failure in failures:
            print_line(f"FAIL: {failure}")
        return 1
    print_line("release_verification=passed")
    return 0


def main() -> int:
    args = parse_args()
    return run(args.database_url or settings.database_url)


if __name__ == "__main__":
    sys.exit(main())
