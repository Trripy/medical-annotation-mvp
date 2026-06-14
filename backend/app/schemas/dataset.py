from app.schemas.task import UploadedImageRead

from pydantic import BaseModel


class DatasetUploadResponse(BaseModel):
    project_id: int
    task_id: int
    job_id: int
    labels: list[str]
    images: list[UploadedImageRead]
