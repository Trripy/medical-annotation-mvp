from __future__ import annotations

import csv
import io
import json

import pytest

from app.db.base import Base
from app.models import ResearchSkillAssessment
from app.schemas.research_skill import CreateResearchSkillEvidenceRequest, UpsertResearchSkillScoreRequest
from app.services.research_skill_export_service import (
    build_skill_json_export,
    iter_skill_csv_export,
    serialize_skill_json_export,
)
from app.services.research_skill_service import create_skill_evidence, upsert_skill_score
from tests._research_skill_test_utils import create_skill_session_factory, seed_skill_data


@pytest.fixture()
def skill_db(tmp_path):
    engine, session_factory = create_skill_session_factory(tmp_path)
    seeded = seed_skill_data(session_factory)
    try:
        with session_factory() as db:
            yield db, seeded
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def create_export_scores(db, seeded) -> int:
    response = upsert_skill_score(
        db,
        seeded.active_assessment_id,
        seeded.overall_required_criterion_id,
        UpsertResearchSkillScoreRequest(target_type="overall", value=4, comment="Line 1\nLine, 2 中文", expected_revision=1),
    )
    overall_score_id = response.created_score_ids[0]
    response = upsert_skill_score(
        db,
        seeded.active_assessment_id,
        seeded.phase_required_criterion_id,
        UpsertResearchSkillScoreRequest(
            target_type="phase_segment",
            phase_segment_id=seeded.segment_ids["incision"],
            is_na=True,
            comment="阶段 N/A",
            expected_revision=response.assessment.revision,
        ),
    )
    create_skill_evidence(
        db,
        overall_score_id,
        CreateResearchSkillEvidenceRequest(start_frame=3, comment="point evidence", expected_revision=response.assessment.revision),
    )
    create_skill_evidence(
        db,
        overall_score_id,
        CreateResearchSkillEvidenceRequest(start_frame=5, end_frame_exclusive=10, comment="interval evidence", expected_revision=response.assessment.revision + 1),
    )
    return overall_score_id


def parse_csv(csv_bytes: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig"))))


def test_skill_json_export_structure_utf8_and_no_paths(skill_db) -> None:
    db, seeded = skill_db
    create_export_scores(db, seeded)
    before = db.get(ResearchSkillAssessment, seeded.active_assessment_id)
    assert before is not None
    before_revision = before.revision

    export = build_skill_json_export(db, seeded.active_assessment_id)
    serialized = serialize_skill_json_export(export.payload)
    payload = json.loads(serialized)

    assert export.filename.endswith("_skill_assessment.json")
    assert "filename*=" in export.headers["Content-Disposition"]
    assert payload["schema_version"] == 1
    assert payload["video"]["name"] == "技能评估测试视频"
    assert payload["rubric"]["criteria"]
    assert payload["assessment"]["overall_comment"] == "Initial comment"
    assert payload["phase_annotation_set"]["segments"]
    assert len(payload["scores"]) == 2
    assert payload["validation"]["assessment_id"] == seeded.active_assessment_id
    assert "技能评估测试视频" in serialized
    assert "\\u6280" not in serialized
    assert "file_path" not in serialized
    assert "thumbnail_path" not in serialized
    assert db.get(ResearchSkillAssessment, seeded.active_assessment_id).revision == before_revision


def test_skill_csv_export_header_rows_bom_json_and_escaping(skill_db) -> None:
    db, seeded = skill_db
    create_export_scores(db, seeded)
    before_revision = db.get(ResearchSkillAssessment, seeded.active_assessment_id).revision

    export = iter_skill_csv_export(db, seeded.active_assessment_id)
    body = b"".join(export.iterator)
    rows = parse_csv(body)
    overall = next(row for row in rows if row["criterion_key"] == "global_rating")
    phase = next(row for row in rows if row["criterion_key"] == "phase_safety")

    assert body.startswith(b"\xef\xbb\xbf")
    assert "filename*=" in export.headers["Content-Disposition"]
    assert len(rows) == 2
    assert overall["video_name"] == "技能评估测试视频"
    assert overall["value"] == "4"
    assert overall["comment"] == "Line 1\nLine, 2 中文"
    evidence = json.loads(overall["evidence_json"])
    assert [item["start_frame"] for item in evidence] == [3, 5]
    assert evidence[0]["end_frame_exclusive"] is None
    assert evidence[1]["end_frame_exclusive"] == 10
    assert phase["is_na"] == "True"
    assert phase["phase_segment_id"] == str(seeded.segment_ids["incision"])
    assert phase["phase_name"] == "Incision"
    assert "file_path" not in body.decode("utf-8")
    assert db.get(ResearchSkillAssessment, seeded.active_assessment_id).revision == before_revision


def test_skill_csv_export_with_no_scores_only_header(skill_db) -> None:
    db, seeded = skill_db

    export = iter_skill_csv_export(db, seeded.active_assessment_id)
    body = b"".join(export.iterator)
    rows = list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))

    assert len(rows) == 1
    assert rows[0][0] == "video_id"


def test_skill_export_filename_sanitizes_cr_lf(skill_db) -> None:
    db, seeded = skill_db
    assessment = db.get(ResearchSkillAssessment, seeded.active_assessment_id)
    assert assessment is not None
    assessment.video.name = "危险\r\n文件名"
    db.commit()

    json_export = build_skill_json_export(db, seeded.active_assessment_id)
    csv_export = iter_skill_csv_export(db, seeded.active_assessment_id)

    assert "\r" not in json_export.filename
    assert "\n" not in json_export.filename
    assert "\r" not in csv_export.filename
    assert "\n" not in csv_export.filename
