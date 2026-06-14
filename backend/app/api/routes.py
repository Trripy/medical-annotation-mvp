from fastapi import APIRouter

from app.api.v1 import datasets, health, images, jobs, projects, sam2, tasks, users

api_router = APIRouter()
api_router.include_router(datasets.router, prefix="/datasets", tags=["datasets"])
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(images.router, tags=["images"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(sam2.router, prefix="/sam2", tags=["sam2"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
