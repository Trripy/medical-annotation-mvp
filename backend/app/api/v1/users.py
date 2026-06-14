from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models import User, UserSettings
from app.schemas.user import (
    UserCreate,
    UserLoginRequest,
    UserLoginResponse,
    UserRead,
    UserSettingsRead,
    UserSettingsUpdate,
)

router = APIRouter()

# TODO: Replace username-based settings API with authenticated user context before production.


@router.get("", response_model=list[UserRead])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.username.asc(), User.id.asc())).all())


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    username = _normalize_username(payload.username)
    existing_user = db.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if existing_user is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    user = User(username=username)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, db: Session = Depends(get_db)) -> None:
    user = db.scalar(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.projects))
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.projects:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a user that owns projects.",
        )

    db.delete(user)
    db.commit()


@router.post("/login", response_model=UserLoginResponse)
def login_user(payload: UserLoginRequest, db: Session = Depends(get_db)) -> UserLoginResponse:
    username = _normalize_username(payload.username)
    user = db.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. Please ask admin to add this username.",
        )

    return UserLoginResponse(username=user.username)


@router.get("/me/settings", response_model=UserSettingsRead)
def get_my_settings(username: str, db: Session = Depends(get_db)) -> UserSettingsRead:
    user = _get_user_by_username(username, db)
    settings = _get_or_create_settings(user, db)
    db.commit()
    db.refresh(settings)
    return _settings_to_read(user, settings)


@router.put("/me/settings", response_model=UserSettingsRead)
def update_my_settings(payload: UserSettingsUpdate, db: Session = Depends(get_db)) -> UserSettingsRead:
    user = _get_user_by_username(payload.username, db)
    settings = _get_or_create_settings(user, db)
    settings.edge_snap_threshold = payload.edge_snap_threshold
    settings.default_tool = payload.default_tool
    settings.add_polygon_vertex_shortcut = payload.add_polygon_vertex_shortcut
    settings.delete_polygon_vertex_shortcut = payload.delete_polygon_vertex_shortcut
    settings.pan_modifier_shortcut = payload.pan_modifier_shortcut
    settings.polygon_confirm_point_shortcut = payload.polygon_confirm_point_shortcut
    settings.sam_result_edge_snap_enabled = payload.sam_result_edge_snap_enabled
    settings.sam_result_edge_snap_threshold = payload.sam_result_edge_snap_threshold
    settings.sam_accept_next_tool = payload.sam_accept_next_tool
    settings.remember_last_frame_per_job = payload.remember_last_frame_per_job
    settings.keep_view_transform_on_frame_switch = payload.keep_view_transform_on_frame_switch
    settings.sam2_default_model = payload.sam2_default_model
    settings.sam2_default_multimask_output = payload.sam2_default_multimask_output
    settings.sam2_default_show_prompt_points = payload.sam2_default_show_prompt_points
    settings.sam2_default_candidate = payload.sam2_default_candidate
    settings.sam2_default_polygon_epsilon = payload.sam2_default_polygon_epsilon
    settings.sam2_default_mask_threshold = payload.sam2_default_mask_threshold
    settings.sam2_default_min_mask_area = payload.sam2_default_min_mask_area
    settings.sam2_default_max_hole_area = payload.sam2_default_max_hole_area
    db.commit()
    db.refresh(settings)
    return _settings_to_read(user, settings)


def _normalize_username(username: str) -> str:
    normalized = username.strip()
    if not normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username is required")
    return normalized


def _get_user_by_username(username: str, db: Session) -> User:
    normalized_username = _normalize_username(username)
    user = db.scalar(select(User).where(func.lower(User.username) == normalized_username.lower()))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. Please ask admin to add this username.",
        )
    return user


def _get_or_create_settings(user: User, db: Session) -> UserSettings:
    settings = db.scalar(select(UserSettings).where(UserSettings.user_id == user.id))
    if settings is not None:
        return settings

    settings = UserSettings(user_id=user.id)
    db.add(settings)
    db.flush()
    return settings


def _settings_to_read(user: User, settings: UserSettings) -> UserSettingsRead:
    return UserSettingsRead(
        username=user.username,
        edge_snap_threshold=settings.edge_snap_threshold,
        default_tool=settings.default_tool,  # type: ignore[arg-type]
        add_polygon_vertex_shortcut=settings.add_polygon_vertex_shortcut,  # type: ignore[arg-type]
        delete_polygon_vertex_shortcut=settings.delete_polygon_vertex_shortcut,  # type: ignore[arg-type]
        pan_modifier_shortcut=settings.pan_modifier_shortcut,  # type: ignore[arg-type]
        polygon_confirm_point_shortcut=settings.polygon_confirm_point_shortcut,
        sam_result_edge_snap_enabled=settings.sam_result_edge_snap_enabled,
        sam_result_edge_snap_threshold=settings.sam_result_edge_snap_threshold,
        sam_accept_next_tool=settings.sam_accept_next_tool,  # type: ignore[arg-type]
        remember_last_frame_per_job=settings.remember_last_frame_per_job,
        keep_view_transform_on_frame_switch=settings.keep_view_transform_on_frame_switch,
        sam2_default_model=settings.sam2_default_model,  # type: ignore[arg-type]
        sam2_default_multimask_output=settings.sam2_default_multimask_output,
        sam2_default_show_prompt_points=settings.sam2_default_show_prompt_points,
        sam2_default_candidate=settings.sam2_default_candidate,  # type: ignore[arg-type]
        sam2_default_polygon_epsilon=settings.sam2_default_polygon_epsilon,
        sam2_default_mask_threshold=settings.sam2_default_mask_threshold,
        sam2_default_min_mask_area=settings.sam2_default_min_mask_area,
        sam2_default_max_hole_area=settings.sam2_default_max_hole_area,
    )
