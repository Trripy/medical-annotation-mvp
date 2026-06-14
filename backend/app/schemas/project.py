from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class ProjectRead(BaseModel):
    id: int
    name: str
    job_count: int = 0
    frame_count: int = 0
    thumbnail_url: str | None = None

    model_config = {"from_attributes": True}
