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
    ResearchVideo,
    User,
)


@dataclass(frozen=True)
class PhaseSeedData:
    reader_user_id: int
    reviewer_user_id: int
    video_id: int
    active_default_protocol_id: int
    active_alpha_v2_protocol_id: int
    active_alpha_v1_protocol_id: int
    draft_protocol_id: int
    archived_protocol_id: int
    active_default_label_ids: dict[str, int]
    set_reader_id: int
    set_reviewer_id: int


def create_phase_session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'phase.db'}",
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


def seed_phase_data(session_factory) -> PhaseSeedData:
    with session_factory() as db:
        reader = User(username="reader", email="reader@example.com", full_name="Reader")
        reviewer = User(username="reviewer", email="reviewer@example.com", full_name="Reviewer")
        video = ResearchVideo(
            name="Phase Test Video",
            original_filename="phase-test.mp4",
            file_path="/tmp/phase-test.mp4",
            thumbnail_path="/tmp/phase-test.jpg",
            width=640,
            height=360,
            fps=25.0,
            frame_count=400,
            duration_ms=16_000,
            status="ready",
            created_by=reader,
        )

        active_default = ResearchPhaseProtocol(
            name="Default Cataract",
            version=1,
            description="Default active protocol.",
            status="active",
            is_default=True,
            created_by=reader,
        )
        active_alpha_v2 = ResearchPhaseProtocol(
            name="Alpha Protocol",
            version=2,
            description="Alpha active v2.",
            status="active",
            is_default=False,
            created_by=reader,
        )
        active_alpha_v1 = ResearchPhaseProtocol(
            name="Alpha Protocol",
            version=1,
            description="Alpha active v1.",
            status="active",
            is_default=False,
            created_by=reader,
        )
        draft_protocol = ResearchPhaseProtocol(
            name="Beta Draft",
            version=1,
            description="Draft protocol.",
            status="draft",
            is_default=False,
            created_by=reader,
        )
        archived_protocol = ResearchPhaseProtocol(
            name="Gamma Archived",
            version=1,
            description="Archived protocol.",
            status="archived",
            is_default=False,
            created_by=reader,
        )

        active_default.labels = [
            ResearchPhaseLabel(
                key="idle",
                name="Idle",
                color="#64748b",
                display_order=0,
                is_active=True,
            ),
            ResearchPhaseLabel(
                key="viscoelastic",
                name="Viscoelastic Injection",
                color="#1f9fe5",
                display_order=1,
                is_active=True,
            ),
            ResearchPhaseLabel(
                key="incision",
                name="Incision",
                color="#ff7a1a",
                display_order=1,
                is_active=True,
            ),
        ]
        active_alpha_v2.labels = [
            ResearchPhaseLabel(
                key="alpha_v2_phase",
                name="Alpha V2 Phase",
                color="#22c55e",
                display_order=0,
                is_active=True,
            )
        ]
        active_alpha_v1.labels = [
            ResearchPhaseLabel(
                key="alpha_v1_phase",
                name="Alpha V1 Phase",
                color="#8b5cf6",
                display_order=0,
                is_active=True,
            )
        ]
        draft_protocol.labels = [
            ResearchPhaseLabel(
                key="draft_phase",
                name="Draft Phase",
                color="#eab308",
                display_order=0,
                is_active=True,
            )
        ]
        archived_protocol.labels = [
            ResearchPhaseLabel(
                key="archived_phase",
                name="Archived Phase",
                color="#14b8a6",
                display_order=0,
                is_active=True,
            )
        ]

        set_reader = ResearchPhaseAnnotationSet(
            video=video,
            protocol=active_default,
            annotator=reader,
            status="draft",
            revision=1,
        )
        set_reader.segments = [
            ResearchPhaseSegment(
                phase_label=active_default.labels[1],
                start_frame=120,
                end_frame_exclusive=None,
                source="manual",
                confidence=0.9,
            ),
            ResearchPhaseSegment(
                phase_label=active_default.labels[0],
                start_frame=10,
                end_frame_exclusive=60,
                source="manual",
                confidence=0.95,
            ),
        ]

        set_reviewer = ResearchPhaseAnnotationSet(
            video=video,
            protocol=active_default,
            annotator=reviewer,
            status="submitted",
            revision=2,
        )
        set_reviewer.segments = [
            ResearchPhaseSegment(
                phase_label=active_default.labels[2],
                start_frame=200,
                end_frame_exclusive=260,
                source="manual",
                confidence=0.8,
            )
        ]

        db.add_all([reader, reviewer, video, active_default, active_alpha_v2, active_alpha_v1, draft_protocol, archived_protocol, set_reader, set_reviewer])
        db.commit()
        db.refresh(video)
        db.refresh(active_default)
        db.refresh(active_alpha_v2)
        db.refresh(active_alpha_v1)
        db.refresh(draft_protocol)
        db.refresh(archived_protocol)
        db.refresh(set_reader)
        db.refresh(set_reviewer)

        return PhaseSeedData(
            reader_user_id=reader.id,
            reviewer_user_id=reviewer.id,
            video_id=video.id,
            active_default_protocol_id=active_default.id,
            active_alpha_v2_protocol_id=active_alpha_v2.id,
            active_alpha_v1_protocol_id=active_alpha_v1.id,
            draft_protocol_id=draft_protocol.id,
            archived_protocol_id=archived_protocol.id,
            active_default_label_ids={
                "idle": active_default.labels[0].id,
                "viscoelastic": active_default.labels[1].id,
                "incision": active_default.labels[2].id,
            },
            set_reader_id=set_reader.id,
            set_reviewer_id=set_reviewer.id,
        )
