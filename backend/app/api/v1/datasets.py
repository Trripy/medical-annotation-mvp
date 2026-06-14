from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models import Image, Job, Label, Project, Task, User
from app.schemas.dataset import DatasetUploadResponse
from app.services.image_storage import InvalidImageError, save_uploaded_image

router = APIRouter()


@router.post("", response_model=DatasetUploadResponse, status_code=status.HTTP_201_CREATED)
def create_dataset(
    project_name: str = Form(...),
    task_name: str = Form(...),
    labels: str = Form("lesion,organ"),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> DatasetUploadResponse:
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one image is required")

    label_names = _parse_labels(labels)
    if not label_names:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one label is required")

    owner = _get_or_create_default_user(db)
    project = Project(name=project_name, owner=owner)
    task = Task(project=project, name=task_name, status="pending")
    job = Job(project=project, task=task, name=task_name, status="annotation")
    job.labels = [
        Label(job=job, name=name, color=_label_color(index), shape_type="polygon", sort_order=index)
        for index, name in enumerate(label_names)
    ]

    db.add(job)
    db.flush()

    data_root = Path(settings.local_storage_root) / "data"
    images: list[Image] = []

    try:
        for frame_index, upload in enumerate(files):
            file_path, thumbnail_path, width, height = save_uploaded_image(upload, data_root=data_root)
            image = Image(
                project=project,
                task=task,
                job=job,
                filename=Path(upload.filename or Path(file_path).name).name,
                file_path=file_path,
                thumbnail_path=thumbnail_path,
                width=width,
                height=height,
                frame_index=frame_index,
            )
            db.add(image)
            images.append(image)
    except InvalidImageError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.commit()
    db.refresh(project)
    db.refresh(task)
    db.refresh(job)
    for image in images:
        db.refresh(image)

    return DatasetUploadResponse(
        project_id=project.id,
        task_id=task.id,
        job_id=job.id,
        labels=label_names,
        images=images,
    )


def _get_or_create_default_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.email == "demo@local"))
    if user is not None:
        return user

    user = User(username="demo", email="demo@local", full_name="Demo User")
    db.add(user)
    db.flush()
    return user


def _parse_labels(labels: str) -> list[str]:
    seen: set[str] = set()
    parsed: list[str] = []
    for raw_label in labels.split(","):
        label = raw_label.strip()
        if label and label.lower() not in seen:
            seen.add(label.lower())
            parsed.append(label)
    return parsed


def _label_color(index: int) -> str:
    colors = ["#22c55e", "#0ea5e9", "#f97316", "#e11d48", "#a855f7", "#14b8a6"]
    return colors[index % len(colors)]
