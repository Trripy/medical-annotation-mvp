from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import (
    ResearchPhaseAnnotationSet,
    ResearchPhaseLabel,
    ResearchPhaseProtocol,
    ResearchPhaseSegment,
    ResearchSkillAssessment,
    ResearchSkillCriterion,
    ResearchSkillCriterionPhaseLabel,
    ResearchSkillRubric,
    ResearchVideo,
    User,
)


@dataclass(frozen=True)
class SkillSeedData:
    reader_user_id: int
    reviewer_user_id: int
    video_id: int
    other_video_id: int
    protocol_id: int
    other_protocol_id: int
    label_ids: dict[str, int]
    other_label_id: int
    draft_phase_set_id: int
    submitted_phase_set_id: int
    other_video_phase_set_id: int
    segment_ids: dict[str, int]
    active_rubric_id: int
    draft_rubric_id: int
    archived_rubric_id: int
    overall_required_criterion_id: int
    phase_required_criterion_id: int
    choice_criterion_id: int
    boolean_criterion_id: int
    text_criterion_id: int
    active_assessment_id: int


def create_skill_session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'skill.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)
    return engine, session_factory


def seed_skill_data(session_factory) -> SkillSeedData:
    with session_factory() as db:
        reader = User(username="reader", email="reader@example.com", full_name="Reader")
        reviewer = User(username="reviewer", email="reviewer@example.com", full_name="Reviewer")
        video = ResearchVideo(
            name="技能评估测试视频",
            original_filename="skill-test.mp4",
            file_path="/tmp/skill-test.mp4",
            thumbnail_path="/tmp/skill-test.jpg",
            width=640,
            height=360,
            fps=25.0,
            frame_count=300,
            duration_ms=12_000,
            status="ready",
            created_by=reader,
        )
        other_video = ResearchVideo(
            name="Other Video",
            original_filename="other.mp4",
            file_path="/tmp/other.mp4",
            thumbnail_path="/tmp/other.jpg",
            width=640,
            height=360,
            fps=25.0,
            frame_count=200,
            duration_ms=8_000,
            status="ready",
            created_by=reviewer,
        )
        protocol = ResearchPhaseProtocol(name="Skill Phase Protocol", version=1, status="active", is_default=True)
        protocol.labels = [
            ResearchPhaseLabel(key="idle", name="Idle", color="#64748b", display_order=0, is_active=True),
            ResearchPhaseLabel(key="incision", name="Incision", color="#ff7a1a", display_order=1, is_active=True),
            ResearchPhaseLabel(key="phaco", name="Phaco", color="#ef4444", display_order=2, is_active=True),
        ]
        other_protocol = ResearchPhaseProtocol(name="Other Skill Protocol", version=1, status="active", is_default=False)
        other_protocol.labels = [
            ResearchPhaseLabel(key="other", name="Other", color="#22c55e", display_order=0, is_active=True)
        ]
        draft_phase_set = ResearchPhaseAnnotationSet(video=video, protocol=protocol, annotator=reader, status="draft", revision=1)
        draft_phase_set.segments = [
            ResearchPhaseSegment(phase_label=protocol.labels[0], start_frame=0, end_frame_exclusive=50, source="manual"),
            ResearchPhaseSegment(phase_label=protocol.labels[1], start_frame=50, end_frame_exclusive=120, source="manual"),
            ResearchPhaseSegment(phase_label=protocol.labels[2], start_frame=120, end_frame_exclusive=200, source="manual"),
        ]
        submitted_phase_set = ResearchPhaseAnnotationSet(video=video, protocol=protocol, annotator=reviewer, status="submitted", revision=2)
        submitted_phase_set.segments = [
            ResearchPhaseSegment(phase_label=protocol.labels[1], start_frame=10, end_frame_exclusive=90, source="manual"),
        ]
        other_video_phase_set = ResearchPhaseAnnotationSet(video=other_video, protocol=protocol, annotator=reader, status="submitted", revision=1)
        other_video_phase_set.segments = [
            ResearchPhaseSegment(phase_label=protocol.labels[1], start_frame=0, end_frame_exclusive=20, source="manual"),
        ]

        active_rubric = ResearchSkillRubric(
            name="Core Cataract Skill",
            version=1,
            description="Core skill rubric.",
            status="active",
            phase_protocol=protocol,
            created_by=reader,
        )
        overall_required = ResearchSkillCriterion(
            rubric=active_rubric,
            key="global_rating",
            name="Global Rating",
            scope="overall",
            score_type="integer_scale",
            min_value=1,
            max_value=5,
            step=1,
            required=True,
            allow_na=False,
            weight=1.0,
            display_order=0,
            is_active=True,
        )
        phase_required = ResearchSkillCriterion(
            rubric=active_rubric,
            key="phase_safety",
            name="Phase Safety",
            scope="phase",
            score_type="number",
            min_value=0,
            max_value=10,
            step=0.5,
            required=True,
            allow_na=True,
            weight=2.0,
            display_order=1,
            is_active=True,
        )
        phase_required.phase_label_links = [
            ResearchSkillCriterionPhaseLabel(phase_label=protocol.labels[1]),
            ResearchSkillCriterionPhaseLabel(phase_label=protocol.labels[2]),
        ]
        choice = ResearchSkillCriterion(
            rubric=active_rubric,
            key="tissue_handling",
            name="Tissue Handling",
            scope="overall",
            score_type="single_choice",
            options_json=[{"value": "poor", "label": "Poor"}, {"value": "good", "label": "Good"}],
            required=False,
            allow_na=False,
            display_order=2,
            is_active=True,
        )
        boolean = ResearchSkillCriterion(
            rubric=active_rubric,
            key="complication",
            name="Complication",
            scope="overall",
            score_type="boolean",
            required=False,
            allow_na=False,
            display_order=3,
            is_active=True,
        )
        text = ResearchSkillCriterion(
            rubric=active_rubric,
            key="free_text",
            name="Free Text",
            scope="overall",
            score_type="text",
            required=False,
            allow_na=True,
            display_order=4,
            is_active=True,
        )
        draft_rubric = ResearchSkillRubric(name="Draft Skill", version=1, status="draft", created_by=reader)
        archived_rubric = ResearchSkillRubric(name="Archived Skill", version=1, status="archived", created_by=reader)
        active_assessment = ResearchSkillAssessment(
            video=video,
            rubric=active_rubric,
            rater=reader,
            phase_annotation_set=draft_phase_set,
            status="draft",
            revision=1,
            overall_comment="Initial comment",
        )
        db.add_all(
            [
                reader,
                reviewer,
                video,
                other_video,
                protocol,
                other_protocol,
                draft_phase_set,
                submitted_phase_set,
                other_video_phase_set,
                active_rubric,
                draft_rubric,
                archived_rubric,
                active_assessment,
            ]
        )
        db.commit()
        return SkillSeedData(
            reader_user_id=reader.id,
            reviewer_user_id=reviewer.id,
            video_id=video.id,
            other_video_id=other_video.id,
            protocol_id=protocol.id,
            other_protocol_id=other_protocol.id,
            label_ids={label.key: label.id for label in protocol.labels},
            other_label_id=other_protocol.labels[0].id,
            draft_phase_set_id=draft_phase_set.id,
            submitted_phase_set_id=submitted_phase_set.id,
            other_video_phase_set_id=other_video_phase_set.id,
            segment_ids={segment.phase_label.key: segment.id for segment in draft_phase_set.segments},
            active_rubric_id=active_rubric.id,
            draft_rubric_id=draft_rubric.id,
            archived_rubric_id=archived_rubric.id,
            overall_required_criterion_id=overall_required.id,
            phase_required_criterion_id=phase_required.id,
            choice_criterion_id=choice.id,
            boolean_criterion_id=boolean.id,
            text_criterion_id=text.id,
            active_assessment_id=active_assessment.id,
        )
