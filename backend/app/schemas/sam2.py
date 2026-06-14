from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Sam2PredictRequest(BaseModel):
    image_id: int
    model_name: Literal[
        "sam2_hiera_tiny",
        "sam2_hiera_small",
        "sam2_hiera_base_plus",
        "sam2_hiera_large",
    ] = "sam2_hiera_large"
    point_coords: list[list[float]] = Field(default_factory=list)
    point_labels: list[int] = Field(default_factory=list)
    box: list[float] | None = None
    multimask_output: bool = True
    candidate: Literal["best", "0", "1", "2"] = "best"
    polygon_epsilon: float = Field(default=0.002, ge=0.0, le=0.1)
    min_mask_area: float = Field(default=100, ge=0.0)
    mask_threshold: float = Field(default=0.0, ge=-5.0, le=5.0)
    max_hole_area: float = Field(default=0.0, ge=0.0)

    @field_validator("point_coords")
    @classmethod
    def validate_point_coords(cls, value: list[list[float]]) -> list[list[float]]:
        for point in value:
            if len(point) != 2:
                raise ValueError("Each point coordinate must be [x, y]")
        return value

    @field_validator("point_labels")
    @classmethod
    def validate_point_labels(cls, value: list[int]) -> list[int]:
        invalid = [label for label in value if label not in (0, 1)]
        if invalid:
            raise ValueError("Point labels must be 0 or 1")
        return value

    @field_validator("box")
    @classmethod
    def validate_box(cls, value: list[float] | None) -> list[float] | None:
        if value is not None and len(value) != 4:
            raise ValueError("Box must be [x1, y1, x2, y2]")
        return value


class Sam2PredictResponse(BaseModel):
    image_id: int
    score: float
    points: list[list[float]]
    model_name: str
    candidate: str
    polygon_epsilon: float
    mask_threshold: float
    max_hole_area: float
    num_contours: int
    mask_area: float
