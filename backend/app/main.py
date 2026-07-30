import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from app.api.routes import api_router
from app.api.v1 import datasets, images, jobs, projects, research, research_server_video_import, sam2, tasks, users
from app.core.config import settings
from app.core.upload_limits import MAX_JOB_UPLOAD_FILES, MAX_MULTIPART_FORM_FIELDS
from app.services.sam2_service import get_sam2_service

logger = logging.getLogger(__name__)


def patch_multipart_form_limits() -> None:
    if getattr(Request, "_medical_annotation_upload_limits_patched", False):
        return

    original_get_form = Request._get_form
    original_form = Request.form

    async def _get_form_with_limits(
        self: Request,
        *,
        max_files: int | float = MAX_JOB_UPLOAD_FILES,
        max_fields: int | float = MAX_MULTIPART_FORM_FIELDS,
    ):
        return await original_get_form(self, max_files=max_files, max_fields=max_fields)

    def form_with_limits(
        self: Request,
        *,
        max_files: int | float = MAX_JOB_UPLOAD_FILES,
        max_fields: int | float = MAX_MULTIPART_FORM_FIELDS,
    ):
        return original_form(self, max_files=max_files, max_fields=max_fields)

    Request._get_form = _get_form_with_limits
    Request.form = form_with_limits
    Request._medical_annotation_upload_limits_patched = True


patch_multipart_form_limits()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials="*" not in settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Phase-Validation-Errors", "X-Phase-Validation-Warnings"],
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
app.include_router(research.router, prefix="/api/research", tags=["research"])
app.include_router(research_server_video_import.router, prefix="/api/research", tags=["research-server-video-import"])
app.include_router(sam2.router, prefix="/api/sam2", tags=["sam2"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.mount("/storage", StaticFiles(directory=settings.local_storage_root), name="storage")
