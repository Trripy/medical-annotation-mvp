from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.api.v1 import version
from app.db.session import get_db
from app.services import version_info
from tests._asgi_test_utils import asgi_request


def test_version_endpoint_reports_non_sensitive_metadata(monkeypatch, tmp_path):
    (tmp_path / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    monkeypatch.setattr(version_info, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(version_info, "_git_value", lambda *_: None)
    monkeypatch.setenv("APP_GIT_COMMIT", "build-without-git")

    engine = create_engine(f"sqlite:///{tmp_path / 'version-test.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('test_revision')"))
    session_factory = sessionmaker(bind=engine)
    test_app = FastAPI()
    test_app.include_router(version.router, prefix="/api/v1/version")

    async def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    test_app.dependency_overrides[get_db] = override_get_db
    try:
        response = asgi_request(test_app, "GET", "/api/v1/version")
    finally:
        test_app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "0.1.0"
    assert payload["git_commit"] == "build-without-git"
    assert payload["database_revision"] == "test_revision"
    assert payload["database_head"]
    assert "password" not in payload
    assert "database_url" not in payload
