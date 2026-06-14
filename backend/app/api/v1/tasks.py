from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models import Image, Job, Label, Project, Task
from app.schemas.task import TaskCreate, TaskRead, TaskUploadResponse
from app.services.image_storage import InvalidImageError, save_uploaded_image
from app.services.labelme_export import build_labelme_zip

router = APIRouter()


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)) -> Task:
    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    task = Task(
        project_id=payload.project_id,
        name=payload.name,
        description=payload.description,
        status="pending",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.post("/{task_id}/data", response_model=TaskUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_task_data(
    task_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> TaskUploadResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one image is required")

    data_root = Path(settings.local_storage_root) / "data"
    images: list[Image] = []
    max_frame_index = db.scalar(select(func.max(Image.frame_index)).where(Image.task_id == task.id))
    existing_image_count = db.scalar(select(func.count(Image.id)).where(Image.task_id == task.id)) or 0
    start_frame_index = max_frame_index + 1 if max_frame_index is not None else existing_image_count

    job = Job(project_id=task.project_id, task_id=task.id, name=task.name, status="pending")
    project_labels = db.scalars(select(Label).where(Label.project_id == task.project_id)).all()
    job.labels = [
        Label(
            job=job,
            name=label.name,
            color=label.color,
            shape_type=getattr(label, "shape_type", "polygon"),
            sort_order=index,
        )
        for index, label in enumerate(project_labels)
    ]
    db.add(job)
    db.flush()

    try:
        for offset, upload in enumerate(files):
            file_path, thumbnail_path, width, height = save_uploaded_image(upload, data_root=data_root)
            image = Image(
                project_id=task.project_id,
                task_id=task.id,
                job_id=job.id,
                filename=Path(upload.filename or Path(file_path).name).name,
                file_path=file_path,
                thumbnail_path=thumbnail_path,
                width=width,
                height=height,
                frame_index=start_frame_index + offset,
            )
            db.add(image)
            images.append(image)
    except InvalidImageError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.commit()
    db.refresh(job)

    for image in images:
        db.refresh(image)

    return TaskUploadResponse(task_id=task.id, job_id=job.id, images=images)


@router.post("/{task_id}/export")
def export_task(
    task_id: int,
    export_format: str = Query(default="labelme", alias="format"),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    if export_format != "labelme":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported export format")

    archive = build_labelme_zip(task, db)
    filename = f"task-{task.id}-labelme.zip"
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
