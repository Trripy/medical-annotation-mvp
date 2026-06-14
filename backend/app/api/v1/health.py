from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db

router = APIRouter()


@router.get("")
def health_check(db: Session = Depends(get_db)) -> dict[str, str | bool]:
    db.execute(text("SELECT 1"))
    storage_root = Path(settings.local_storage_root)
    storage_root.mkdir(parents=True, exist_ok=True)
    return {
        "status": "ok",
        "database": "ok",
        "storage_root": str(storage_root),
        "storage_ready": storage_root.exists(),
    }
