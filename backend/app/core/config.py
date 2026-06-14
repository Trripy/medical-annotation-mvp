from functools import cached_property

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Medical Annotation MVP"
    api_v1_prefix: str = "/api/v1"

    postgres_db: str = "med_annotate"
    postgres_user: str = "med_annotate"
    postgres_password: str = "med_annotate"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    backend_cors_origins: str = Field(default="*")
    local_storage_root: str = Field(default="./storage")
    sam2_repo_root: str = Field(default="../sam2")
    sam2_checkpoint: str = Field(default="../sam2/checkpoints/sam2.1_hiera_large.pt")
    sam2_model_cfg: str = Field(default="configs/sam2.1/sam2.1_hiera_l.yaml")
    sam2_device: str = Field(default="auto")
    sam2_load_on_startup: bool = Field(default=True)
    sam2_polygon_epsilon_ratio: float = Field(default=0.002)
    sam2_min_mask_area: float = Field(default=100)
    sam2_mask_threshold: float = Field(default=0.0)
    sam2_max_hole_area: float = Field(default=0.0)
    sam2_max_sprinkle_area: float = Field(default=0.0)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @cached_property
    def database_url(self) -> str:
        return (
            "postgresql+psycopg2://"
            f"{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @cached_property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]


settings = Settings()
