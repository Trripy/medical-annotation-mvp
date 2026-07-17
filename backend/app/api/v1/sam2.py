import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models import Image, Job, Task
from app.models.research import ResearchVideo, ResearchVideoFrame
from app.schemas.sam2 import (
    Sam2PredictRequest,
    Sam2PredictResponse,
    Sam2RefinePolygonRequest,
    Sam2RefinePolygonResponse,
    Sam2TrackVideoRequest,
    Sam2TrackVideoResponse,
)
from app.services.sam2_service import (
    Sam2PredictionError,
    Sam2UnavailableError,
    get_sam2_service,
)
from app.services.sam2_video_service import (
    Sam2VideoFrame,
    get_sam2_video_service,
)

router = APIRouter()


@router.post("/predict", response_model=Sam2PredictResponse)
def predict_sam2_mask(payload: Sam2PredictRequest, db: Session = Depends(get_db)) -> Sam2PredictResponse:
    image, image_path = _resolve_sam2_image_context(payload, db)

    service = get_sam2_service()
    try:
        result = service.predict(
            image_path=image_path,
            model_name=payload.model_name,
            point_coords=payload.point_coords,
            point_labels=payload.point_labels,
            box=payload.box,
            multimask_output=payload.multimask_output,
            candidate=payload.candidate,
            polygon_epsilon=payload.polygon_epsilon,
            min_mask_area=payload.min_mask_area,
            mask_threshold=payload.mask_threshold,
            max_hole_area=payload.max_hole_area,
        )
    except Sam2UnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Sam2PredictionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return Sam2PredictResponse(
        image_id=image.id,
        score=result.score,
        points=result.points,
        model_name=result.model_name,
        candidate=result.candidate,
        polygon_epsilon=result.polygon_epsilon,
        mask_threshold=result.mask_threshold,
        max_hole_area=result.max_hole_area,
        num_contours=result.num_contours,
        mask_area=result.mask_area,
    )


@router.post("/refine-polygon", response_model=Sam2RefinePolygonResponse)
def refine_sam2_polygon(
    payload: Sam2RefinePolygonRequest,
    db: Session = Depends(get_db),
) -> Sam2RefinePolygonResponse:
    image, image_path = _resolve_sam2_image_context(payload, db)

    service = get_sam2_service()
    try:
        result = service.refine_polygon(
            image_path=image_path,
            model_name=payload.model_name,
            polygon_points=payload.points,
            multimask_output=payload.multimask_output,
            candidate=payload.candidate,
            polygon_epsilon=payload.polygon_epsilon,
            min_mask_area=payload.min_mask_area,
            mask_threshold=payload.mask_threshold,
            max_hole_area=payload.max_hole_area,
        )
    except Sam2UnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Sam2PredictionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return Sam2RefinePolygonResponse(
        image_id=image.id,
        annotation_id=payload.annotation_id,
        score=result.score,
        points=result.points,
        area=result.mask_area,
        source="refine_polygon",
        model_name=result.model_name,
        candidate=result.candidate,
        polygon_epsilon=result.polygon_epsilon,
        mask_threshold=result.mask_threshold,
        max_hole_area=result.max_hole_area,
        num_contours=result.num_contours,
    )


@router.post("/track-video", response_model=Sam2TrackVideoResponse)
def track_sam2_video(
    payload: Sam2TrackVideoRequest,
    db: Session = Depends(get_db),
) -> Sam2TrackVideoResponse:
    job = db.scalar(
        select(Job)
        .where(Job.id == payload.job_id)
        .options(
            selectinload(Job.images),
            selectinload(Job.labels),
            selectinload(Job.task).selectinload(Task.images),
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    ordered_images = _ordered_job_images(job)
    if not ordered_images:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Job has no images")

    image_by_id = {image.id: image for image in ordered_images}
    start_image = image_by_id.get(payload.start_image_id)
    if start_image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Start image not found in job")

    label_ids = {label.id for label in job.labels}
    if payload.label_id not in label_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Label does not belong to job")

    frames = [
        Sam2VideoFrame(
            image_id=image.id,
            frame_index=image.frame_index if image.frame_index is not None else index,
            filename=image.filename,
            file_path=image.file_path,
            width=image.width or 0,
            height=image.height or 0,
        )
        for index, image in enumerate(ordered_images)
    ]

    service = get_sam2_video_service()
    try:
        result = service.track_video(
            frames=frames,
            start_image_id=payload.start_image_id,
            start_frame_index=payload.start_frame_index,
            polygon_points=payload.points,
            direction=payload.direction,
            end_frame_index=payload.end_frame_index,
            backward_end_frame_index=payload.backward_end_frame_index,
            forward_end_frame_index=payload.forward_end_frame_index,
            review_interval=payload.review_interval,
            model_name=payload.model_name,
            polygon_epsilon=payload.polygon_epsilon,
            min_mask_area=payload.min_mask_area,
            mask_threshold=payload.mask_threshold,
            max_hole_area=payload.max_hole_area,
        )
    except Sam2UnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Sam2PredictionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return Sam2TrackVideoResponse(
        job_id=payload.job_id,
        source_annotation_id=payload.annotation_id,
        start_frame_index=result.start_frame_index,
        end_frame_index=result.end_frame_index,
        backward_end_frame_index=result.backward_end_frame_index,
        forward_end_frame_index=result.forward_end_frame_index,
        direction=result.direction,
        model_name=result.model_name,
        results=[
            {
                "image_id": frame.image_id,
                "frame_index": frame.frame_index,
                "filename": frame.filename,
                "points": frame.points,
                "score": frame.score,
                "area": frame.area,
                "status": frame.status,
                "propagation_direction": frame.propagation_direction,
                "detail": frame.detail,
            }
            for frame in result.results
        ],
        review_frames=result.review_frames,
        warnings=result.warnings,
    )


def _ordered_job_images(job: Job) -> list[Image]:
    images = list(job.images or [])
    if not images and job.task is not None:
        images = list(job.task.images or [])
    return sorted(
        images,
        key=lambda image: (
            image.frame_index is None,
            image.frame_index if image.frame_index is not None else 0,
            _natural_key(image.filename),
            image.id,
        ),
    )


def _natural_key(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def _resolve_sam2_image_context(payload: Sam2PredictRequest | Sam2RefinePolygonRequest, db: Session) -> tuple[Image, str]:
    if payload.research_video_id is not None:
        if payload.research_frame_index is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="research_frame_index is required for research videos")

        frame = db.scalar(
            select(ResearchVideoFrame)
            .join(ResearchVideo)
            .where(
                ResearchVideo.id == payload.research_video_id,
                ResearchVideoFrame.frame_index == payload.research_frame_index,
            )
        )
        if frame is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research video frame not found")

        research_image = Image(
            id=frame.id,
            filename=frame.filename,
            file_path=frame.file_path,
            thumbnail_path=frame.file_path,
            width=frame.width,
            height=frame.height,
            frame_index=frame.frame_index,
        )
        return research_image, frame.file_path

    image = db.get(Image, payload.image_id)
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    return image, image.file_path
