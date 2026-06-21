import re
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models import Annotation, Image, Job, Label, Project, Task, User
from app.schemas.job import JobRead
from app.schemas.project import ProjectCreate, ProjectRead
from app.services.export_scope import get_annotated_image_counts

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db)) -> list[ProjectRead]:
    projects = db.scalars(
        select(Project)
        .options(
            selectinload(Project.jobs).selectinload(Job.project),
            selectinload(Project.jobs).selectinload(Job.images),
            selectinload(Project.jobs).selectinload(Job.task).selectinload(Task.images),
        )
        .order_by(Project.name.asc(), Project.id.asc())
    ).all()

    result = [_project_to_read(project) for project in projects]

    unassigned_jobs = _load_unassigned_jobs(db)
    if unassigned_jobs:
        result.append(_synthetic_unassigned_project(unassigned_jobs))

    return result


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    owner = _get_or_create_default_user(db)
    project = Project(name=payload.name.strip(), owner=owner)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, db: Session = Depends(get_db)) -> None:
    if project_id == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete virtual project")

    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    task_ids = list(db.scalars(select(Task.id).where(Task.project_id == project_id)).all())
    job_conditions = [Job.project_id == project_id]
    if task_ids:
        job_conditions.append(Job.task_id.in_(task_ids))
    job_ids = list(db.scalars(select(Job.id).where(or_(*job_conditions))).all())

    images = list(db.scalars(select(Image).where(Image.project_id == project_id)).all())
    image_ids = [image.id for image in images]
    file_paths = _image_file_paths(images)

    label_conditions = [Label.project_id == project_id]
    if job_ids:
        label_conditions.append(Label.job_id.in_(job_ids))
    label_ids = list(db.scalars(select(Label.id).where(or_(*label_conditions))).all())

    annotation_conditions = []
    if image_ids:
        annotation_conditions.append(Annotation.image_id.in_(image_ids))
    if job_ids:
        annotation_conditions.append(Annotation.job_id.in_(job_ids))
    if label_ids:
        annotation_conditions.append(Annotation.label_id.in_(label_ids))
    if annotation_conditions:
        db.execute(delete(Annotation).where(or_(*annotation_conditions)))

    if image_ids:
        db.execute(delete(Image).where(Image.id.in_(image_ids)))
    if label_ids:
        db.execute(delete(Label).where(Label.id.in_(label_ids)))
    if job_ids:
        db.execute(delete(Job).where(Job.id.in_(job_ids)))
    if task_ids:
        db.execute(delete(Task).where(Task.id.in_(task_ids)))
    db.execute(delete(Project).where(Project.id == project_id))
    db.commit()

    _delete_files(file_paths)


@router.get("/{project_id}/jobs", response_model=list[JobRead])
def list_project_jobs(project_id: int, db: Session = Depends(get_db)) -> list[JobRead]:
    if project_id == 0:
        jobs = _load_unassigned_jobs(db)
        annotated_counts = get_annotated_image_counts(db, [job.id for job in jobs])
        return [_job_to_read(job, annotated_counts.get(job.id, 0)) for job in jobs]

    project = db.scalar(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.jobs).selectinload(Job.project),
            selectinload(Project.jobs).selectinload(Job.images),
            selectinload(Project.jobs).selectinload(Job.task).selectinload(Task.images),
        )
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    jobs = sorted(project.jobs, key=lambda job: job.id, reverse=True)
    annotated_counts = get_annotated_image_counts(db, [job.id for job in jobs])
    return [_job_to_read(job, annotated_counts.get(job.id, 0)) for job in jobs]


def _get_or_create_default_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.email == "demo@local"))
    if user is not None:
        if not user.username:
            user.username = "demo"
        return user

    user = User(username="demo", email="demo@local", full_name="Demo User")
    db.add(user)
    db.flush()
    return user


def _load_unassigned_jobs(db: Session) -> list[Job]:
    return list(
        db.scalars(
            select(Job)
            .where(Job.project_id.is_(None))
            .options(
                selectinload(Job.project),
                selectinload(Job.images),
                selectinload(Job.task).selectinload(Task.images),
            )
            .order_by(Job.id.desc())
        ).all()
    )


def _project_to_read(project: Project) -> ProjectRead:
    jobs = sorted(project.jobs, key=lambda job: job.id, reverse=True)
    return ProjectRead(
        id=project.id,
        name=project.name,
        job_count=len(jobs),
        frame_count=sum(len(_job_images(job)) for job in jobs),
        thumbnail_url=_first_thumbnail_url(jobs),
    )


def _synthetic_unassigned_project(jobs: list[Job]) -> ProjectRead:
    return ProjectRead(
        id=0,
        name="Unassigned Project",
        job_count=len(jobs),
        frame_count=sum(len(_job_images(job)) for job in jobs),
        thumbnail_url=_first_thumbnail_url(jobs),
    )


def _job_to_read(job: Job, annotated_images_count: int = 0) -> JobRead:
    images = _job_images(job)
    return JobRead(
        id=job.id,
        project_id=job.project_id,
        project_name=job.project.name if job.project else "Unassigned Project",
        name=job.name,
        status=job.status,
        task_id=job.task_id,
        frames=len(images),
        annotated_images_count=annotated_images_count,
        thumbnail_url=f"/api/images/{images[0].id}/thumbnail" if images else None,
    )


def _first_thumbnail_url(jobs: list[Job]) -> str | None:
    for job in jobs:
        images = _job_images(job)
        if images:
            return f"/api/images/{images[0].id}/thumbnail"
    return None


def _ordered_images(images: list[Image]) -> list[Image]:
    return sorted(
        images,
        key=lambda image: (
            image.frame_index is None,
            image.frame_index if image.frame_index is not None else 0,
            _natural_key(image.filename),
            image.id,
        ),
    )


def _natural_key(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def _job_images(job: Job) -> list[Image]:
    if job.images:
        return _ordered_images(job.images)
    if job.task is not None:
        return _ordered_images(job.task.images)
    return []


def _image_file_paths(images: list[Image]) -> list[str]:
    paths: list[str] = []
    for image in images:
        paths.extend([image.file_path, image.thumbnail_path])
    return paths


def _delete_files(paths: list[str]) -> None:
    for path in paths:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to delete image file %s: %s", path, exc)
