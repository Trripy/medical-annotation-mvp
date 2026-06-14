from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    project_id: int
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class TaskRead(BaseModel):
    id: int
    project_id: int
    name: str
    description: str | None
    status: str

    model_config = {"from_attributes": True}


class UploadedImageRead(BaseModel):
    id: int
    width: int | None
    height: int | None
    frame_index: int | None
    filename: str
    file_path: str
    thumbnail_path: str

    model_config = {"from_attributes": True}


class TaskUploadResponse(BaseModel):
    task_id: int
    job_id: int
    images: list[UploadedImageRead]
