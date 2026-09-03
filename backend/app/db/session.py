from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    # Force UTF-8 at the client boundary. This is the normal encoding for the
    # application and also keeps local PostgreSQL instances usable on Windows
    # systems whose server encoding was initialized as SQL_ASCII.
    connect_args={"client_encoding": "UTF8"},
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
