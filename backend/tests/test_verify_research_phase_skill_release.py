from __future__ import annotations

import sqlalchemy as sa

from app.db.base import Base
from app.models import ResearchPhaseLabel, ResearchPhaseProtocol, User
from scripts.verify_research_phase_skill_release import run
from tests._research_skill_test_utils import create_skill_session_factory, seed_skill_data


def test_release_verifier_passes_on_temporary_database(tmp_path) -> None:
    engine, session_factory = create_skill_session_factory(tmp_path)
    try:
        seed_skill_data(session_factory)
        with session_factory() as db:
            protocol = db.query(ResearchPhaseProtocol).filter_by(is_default=True).one()
            next_order = len(protocol.labels)
            for index in range(9):
                db.add(
                    ResearchPhaseLabel(
                        protocol=protocol,
                        key=f"default_extra_{index}",
                        name=f"Default Extra {index}",
                        color="#64748b",
                        display_order=next_order + index,
                        is_active=True,
                    )
                )
            db.execute(sa.text("create table alembic_version (version_num varchar(32) not null primary key)"))
            db.execute(sa.text("insert into alembic_version (version_num) values ('20260722_0015')"))
            db.commit()

        assert run(f"sqlite:///{tmp_path / 'skill.db'}") == 0
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_release_verifier_fails_when_skill_tables_are_missing(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'missing.db'}")
    try:
        User.__table__.create(engine)
        with engine.begin() as conn:
            conn.execute(sa.text("create table alembic_version (version_num varchar(32) not null primary key)"))
            conn.execute(sa.text("insert into alembic_version (version_num) values ('20260722_0015')"))

        assert run(f"sqlite:///{tmp_path / 'missing.db'}") == 1
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
