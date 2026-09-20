from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.version_info import build_version_info


router = APIRouter()


@router.get("")
def read_version(db: Session = Depends(get_db)) -> JSONResponse:
    return JSONResponse(build_version_info(db))
