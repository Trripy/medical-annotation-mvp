from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Image
from app.schemas.sam2 import Sam2PredictRequest, Sam2PredictResponse
from app.services.sam2_service import (
    Sam2PredictionError,
    Sam2UnavailableError,
    get_sam2_service,
)

router = APIRouter()


@router.post("/predict", response_model=Sam2PredictResponse)
def predict_sam2_mask(payload: Sam2PredictRequest, db: Session = Depends(get_db)) -> Sam2PredictResponse:
    image = db.get(Image, payload.image_id)
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    service = get_sam2_service()
    try:
        result = service.predict(
            image_path=image.file_path,
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
