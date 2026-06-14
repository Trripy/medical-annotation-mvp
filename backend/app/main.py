import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import api_router
from app.api.v1 import datasets, images, jobs, projects, sam2, tasks, users
from app.core.config import settings
from app.services.sam2_service import get_sam2_service

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials="*" not in settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def ensure_storage_root() -> None:
    Path(settings.local_storage_root).mkdir(parents=True, exist_ok=True)
    if settings.sam2_load_on_startup:
        try:
            get_sam2_service().load()
        except Exception as exc:
            logger.exception("SAM2 startup load failed: %s", exc)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/docs"}


app.include_router(api_router, prefix=settings.api_v1_prefix)
app.include_router(datasets.router, prefix="/api/datasets", tags=["datasets"])
app.include_router(images.router, prefix="/api", tags=["images"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(sam2.router, prefix="/api/sam2", tags=["sam2"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.mount("/storage", StaticFiles(directory=settings.local_storage_root), name="storage")
