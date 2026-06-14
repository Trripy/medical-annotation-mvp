import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Image

router = APIRouter()


@router.get("/images/{image_id}/file")
def get_image_file(image_id: int, db: Session = Depends(get_db)) -> FileResponse:
    image = _get_image_or_404(image_id, db)
    return _inline_image_response(image.file_path)


@router.head("/images/{image_id}/file")
def head_image_file(image_id: int, db: Session = Depends(get_db)) -> FileResponse:
    image = _get_image_or_404(image_id, db)
    return _inline_image_response(image.file_path)


@router.get("/images/{image_id}/thumbnail")
def get_image_thumbnail(image_id: int, db: Session = Depends(get_db)) -> FileResponse:
    image = _get_image_or_404(image_id, db)
    return _inline_image_response(image.thumbnail_path)


@router.head("/images/{image_id}/thumbnail")
def head_image_thumbnail(image_id: int, db: Session = Depends(get_db)) -> FileResponse:
    image = _get_image_or_404(image_id, db)
    return _inline_image_response(image.thumbnail_path)


def _get_image_or_404(image_id: int, db: Session) -> Image:
    image = db.get(Image, image_id)
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    return image


def _inline_image_response(path: str) -> FileResponse:
    image_path = Path(path)
    if not image_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image file not found")

    media_type, _ = mimetypes.guess_type(str(image_path))
    return FileResponse(
        image_path,
        media_type=media_type or "application/octet-stream",
        headers={"Content-Disposition": "inline"},
    )
