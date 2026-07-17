from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Sam2PredictRequest(BaseModel):
    image_id: int
    research_video_id: int | None = None
    research_frame_index: int | None = None
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


class Sam2RefinePolygonRequest(BaseModel):
    image_id: int
    research_video_id: int | None = None
    research_frame_index: int | None = None
    annotation_id: int | str | None = None
    points: list[list[float]] = Field(min_length=3)
    model_name: Literal[
        "sam2_hiera_tiny",
        "sam2_hiera_small",
        "sam2_hiera_base_plus",
        "sam2_hiera_large",
    ] = "sam2_hiera_large"
    multimask_output: bool = True
    candidate: Literal["best", "0", "1", "2"] = "best"
    polygon_epsilon: float = Field(default=0.002, ge=0.0, le=0.1)
    min_mask_area: float = Field(default=100, ge=0.0)
    mask_threshold: float = Field(default=0.0, ge=-5.0, le=5.0)
    max_hole_area: float = Field(default=0.0, ge=0.0)

    @field_validator("points")
    @classmethod
    def validate_points(cls, value: list[list[float]]) -> list[list[float]]:
        for point in value:
            if len(point) != 2:
                raise ValueError("Each polygon point must be [x, y]")
        return value


class Sam2RefinePolygonResponse(BaseModel):
    image_id: int
    annotation_id: int | str | None = None
    score: float
    points: list[list[float]]
    area: float
    source: Literal["refine_polygon"] = "refine_polygon"
    model_name: str
    candidate: str
    polygon_epsilon: float
    mask_threshold: float
    max_hole_area: float
    num_contours: int


class Sam2TrackVideoRequest(BaseModel):
    job_id: int
    start_image_id: int
    start_frame_index: int | None = None
    annotation_id: int | str | None = None
    label_id: int
    points: list[list[float]] = Field(min_length=3)
    direction: Literal["forward", "backward", "both"] = "forward"
    end_frame_index: int | None = Field(default=None, ge=0)
    backward_end_frame_index: int | None = Field(default=None, ge=0)
    forward_end_frame_index: int | None = Field(default=None, ge=0)
    review_interval: int = Field(default=10, ge=1, le=1000)
    existing_annotation_policy: Literal["skip_same_label", "replace_same_label", "append"] = "skip_same_label"
    model_name: Literal[
        "sam2_hiera_tiny",
        "sam2_hiera_small",
        "sam2_hiera_base_plus",
        "sam2_hiera_large",
    ] = "sam2_hiera_large"
    polygon_epsilon: float = Field(default=0.002, ge=0.0, le=0.1)
    min_mask_area: float = Field(default=100, ge=0.0)
    mask_threshold: float = Field(default=0.0, ge=-5.0, le=5.0)
    max_hole_area: float = Field(default=0.0, ge=0.0)

    @field_validator("points")
    @classmethod
    def validate_track_points(cls, value: list[list[float]]) -> list[list[float]]:
        for point in value:
            if len(point) != 2:
                raise ValueError("Each polygon point must be [x, y]")
        return value

    @model_validator(mode="after")
    def validate_tracking_range(self) -> "Sam2TrackVideoRequest":
        start_frame_index = self.start_frame_index
        if self.direction == "forward":
            if self.end_frame_index is None:
                raise ValueError("end_frame_index is required for forward tracking")
            if start_frame_index is not None and self.end_frame_index < start_frame_index:
                raise ValueError("Forward tracking end_frame_index must be greater than or equal to start_frame_index")
            return self

        if self.direction == "backward":
            if self.end_frame_index is None:
                raise ValueError("end_frame_index is required for backward tracking")
            if start_frame_index is not None and self.end_frame_index > start_frame_index:
                raise ValueError("Backward tracking end_frame_index must be less than or equal to start_frame_index")
            return self

        if self.backward_end_frame_index is None or self.forward_end_frame_index is None:
            raise ValueError("backward_end_frame_index and forward_end_frame_index are required for bidirectional tracking")
        if start_frame_index is not None:
            if self.backward_end_frame_index > start_frame_index:
                raise ValueError("Bidirectional backward_end_frame_index must be less than or equal to start_frame_index")
            if self.forward_end_frame_index < start_frame_index:
                raise ValueError("Bidirectional forward_end_frame_index must be greater than or equal to start_frame_index")
        return self


class Sam2TrackVideoFrameResult(BaseModel):
    image_id: int
    frame_index: int
    filename: str
    points: list[list[float]] | None = None
    score: float | None = None
    area: float | None = None
    status: Literal["source", "tracked", "failed"]
    propagation_direction: Literal["source", "forward", "backward"]
    detail: str | None = None


class Sam2TrackVideoResponse(BaseModel):
    job_id: int
    source_annotation_id: int | str | None = None
    start_frame_index: int
    end_frame_index: int
    backward_end_frame_index: int | None = None
    forward_end_frame_index: int | None = None
    direction: Literal["forward", "backward", "both"]
    model_name: str
    results: list[Sam2TrackVideoFrameResult]
    review_frames: list[int]
    warnings: list[str] = Field(default_factory=list)
