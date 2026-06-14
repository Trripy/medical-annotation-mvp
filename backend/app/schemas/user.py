from typing import Literal

from pydantic import BaseModel, Field, field_validator


ToolName = Literal["cursor", "rectangle", "polygon", "sam2"]
SamAcceptNextTool = Literal["keep_current", "default_tool", "cursor", "rectangle", "polygon", "sam2"]
Sam2ModelName = Literal["sam2_hiera_tiny", "sam2_hiera_small", "sam2_hiera_base_plus", "sam2_hiera_large"]
Sam2Candidate = Literal["best", "0", "1", "2"]
SUPPORTED_SHORTCUTS = {"shift", "alt", "ctrl", "space", *"abcdefghijklmnopqrstuvwxyz", *"0123456789"}


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=255)


class UserLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)


class UserRead(BaseModel):
    id: int
    username: str

    model_config = {"from_attributes": True}


class UserLoginResponse(BaseModel):
    username: str


class UserSettingsBase(BaseModel):
    edge_snap_threshold: int = Field(default=5, ge=0, le=100)
    default_tool: ToolName = "sam2"
    add_polygon_vertex_shortcut: str = "shift"
    delete_polygon_vertex_shortcut: str = "alt"
    pan_modifier_shortcut: str = "ctrl"
    polygon_confirm_point_shortcut: str = "space"
    sam_result_edge_snap_enabled: bool = False
    sam_result_edge_snap_threshold: int = Field(default=5, ge=0, le=100)
    sam_accept_next_tool: SamAcceptNextTool = "keep_current"
    remember_last_frame_per_job: bool = True
    keep_view_transform_on_frame_switch: bool = True
    sam2_default_model: Sam2ModelName = "sam2_hiera_large"
    sam2_default_multimask_output: bool = True
    sam2_default_show_prompt_points: bool = True
    sam2_default_candidate: Sam2Candidate = "best"
    sam2_default_polygon_epsilon: float = Field(default=0.002, ge=0.0005, le=0.02)
    sam2_default_mask_threshold: float = Field(default=0.0, ge=-5.0, le=5.0)
    sam2_default_min_mask_area: int = Field(default=100, ge=0, le=100000)
    sam2_default_max_hole_area: int = Field(default=0, ge=0, le=100000)

    @field_validator(
        "add_polygon_vertex_shortcut",
        "delete_polygon_vertex_shortcut",
        "pan_modifier_shortcut",
        "polygon_confirm_point_shortcut",
    )
    @classmethod
    def validate_shortcut(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_SHORTCUTS:
            raise ValueError("Shortcut must be Shift, Alt, Ctrl, Space, A-Z, or 0-9")
        return normalized


class UserSettingsUpdate(UserSettingsBase):
    username: str = Field(min_length=1, max_length=255)


class UserSettingsRead(UserSettingsBase):
    username: str
