from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from PIL import Image as PILImage


class InvalidImageError(ValueError):
    pass


def save_uploaded_image(
    upload: UploadFile,
    *,
    data_root: Path,
    thumbnail_size: tuple[int, int] = (256, 256),
) -> tuple[str, str, int, int]:
    images_dir = data_root / "images"
    thumbnails_dir = data_root / "thumbnails"
    images_dir.mkdir(parents=True, exist_ok=True)
    thumbnails_dir.mkdir(parents=True, exist_ok=True)

    original_name = Path(upload.filename or "image").name
    suffix = Path(original_name).suffix.lower() or ".png"
    stored_name = f"{uuid4().hex}{suffix}"
    image_path = images_dir / stored_name
    thumbnail_path = thumbnails_dir / stored_name

    upload.file.seek(0)
    try:
        with PILImage.open(upload.file) as image:
            image.verify()
    except Exception as exc:
        raise InvalidImageError(f"{original_name} is not a valid image") from exc

    upload.file.seek(0)
    with PILImage.open(upload.file) as image:
        width, height = image.size
        image.save(image_path)

        thumbnail = image.copy()
        thumbnail.thumbnail(thumbnail_size)
        thumbnail.save(thumbnail_path)

    return str(image_path), str(thumbnail_path), width, height
