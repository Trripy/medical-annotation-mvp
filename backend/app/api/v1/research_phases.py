from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.research_phase import (
    CloseActivePhaseSegmentRequest,
    CreateResearchPhaseAnnotationSetRequest,
    CreateResearchPhaseAnnotationSetResponse,
    CreateResearchPhaseSegmentRequest,
    MergeResearchPhaseSegmentsRequest,
    ReopenResearchPhaseAnnotationSetRequest,
    ResearchPhaseAnnotationSetDetail,
    ResearchPhaseAnnotationSetSummary,
    ResearchPhaseMutationResponse,
    ResearchPhaseProtocolDetail,
    ResearchPhaseProtocolSummary,
    ResearchPhaseStatusMutationResponse,
    ResearchPhaseValidationResponse,
    SplitResearchPhaseSegmentRequest,
    SubmitResearchPhaseAnnotationSetRequest,
    TransitionResearchPhaseRequest,
    UpdateResearchPhaseSegmentRequest,
)
from app.services.research_phase_export_service import (
    build_phase_json_export,
    iter_phase_framewise_csv,
    iter_phase_segment_csv,
    serialize_phase_json_export,
)
from app.services.research_phase_service import (
    close_active_phase_segment,
    create_phase_segment,
    delete_phase_segment,
    get_or_create_phase_annotation_set,
    get_phase_annotation_set,
    get_phase_protocol,
    list_phase_protocols,
    list_video_phase_annotation_sets,
    merge_phase_segments,
    reopen_phase_annotation_set,
    split_phase_segment,
    submit_phase_annotation_set,
    transition_phase,
    update_phase_segment,
    validate_phase_annotation_set,
)

router = APIRouter()


@router.get("/phase-protocols", response_model=list[ResearchPhaseProtocolSummary])
async def list_protocols(
    status: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> list[ResearchPhaseProtocolSummary]:
    return list_phase_protocols(db, status_filter=status, include_archived=include_archived)


@router.get("/phase-protocols/{protocol_id}", response_model=ResearchPhaseProtocolDetail)
async def read_protocol(protocol_id: int, db: Session = Depends(get_db)) -> ResearchPhaseProtocolDetail:
    return get_phase_protocol(db, protocol_id)


@router.get("/videos/{video_id}/phase-annotation-sets", response_model=list[ResearchPhaseAnnotationSetSummary])
async def list_phase_annotation_sets(
    video_id: int,
    db: Session = Depends(get_db),
) -> list[ResearchPhaseAnnotationSetSummary]:
    return list_video_phase_annotation_sets(db, video_id)


@router.post("/videos/{video_id}/phase-annotation-sets", response_model=CreateResearchPhaseAnnotationSetResponse)
async def create_or_get_phase_annotation_set_route(
    video_id: int,
    payload: CreateResearchPhaseAnnotationSetRequest,
    db: Session = Depends(get_db),
) -> CreateResearchPhaseAnnotationSetResponse:
    return get_or_create_phase_annotation_set(
        db,
        video_id=video_id,
        protocol_id=payload.protocol_id,
        username=payload.username,
    )


@router.get("/phase-annotation-sets/{annotation_set_id}", response_model=ResearchPhaseAnnotationSetDetail)
async def read_phase_annotation_set(
    annotation_set_id: int,
    db: Session = Depends(get_db),
) -> ResearchPhaseAnnotationSetDetail:
    return get_phase_annotation_set(db, annotation_set_id)


@router.get(
    "/phase-annotation-sets/{annotation_set_id}/validate",
    response_model=ResearchPhaseValidationResponse,
)
async def validate_phase_annotation_set_route(
    annotation_set_id: int,
    db: Session = Depends(get_db),
) -> ResearchPhaseValidationResponse:
    return validate_phase_annotation_set(db, annotation_set_id)


@router.post(
    "/phase-annotation-sets/{annotation_set_id}/submit",
    response_model=ResearchPhaseStatusMutationResponse,
)
async def submit_phase_annotation_set_route(
    annotation_set_id: int,
    payload: SubmitResearchPhaseAnnotationSetRequest,
    db: Session = Depends(get_db),
) -> ResearchPhaseStatusMutationResponse:
    return submit_phase_annotation_set(db, annotation_set_id, payload)


@router.post(
    "/phase-annotation-sets/{annotation_set_id}/reopen",
    response_model=ResearchPhaseStatusMutationResponse,
)
async def reopen_phase_annotation_set_route(
    annotation_set_id: int,
    payload: ReopenResearchPhaseAnnotationSetRequest,
    db: Session = Depends(get_db),
) -> ResearchPhaseStatusMutationResponse:
    return reopen_phase_annotation_set(db, annotation_set_id, payload)


@router.get("/phase-annotation-sets/{annotation_set_id}/export/json")
async def export_phase_annotation_set_json(
    annotation_set_id: int,
    db: Session = Depends(get_db),
) -> Response:
    export_result = build_phase_json_export(db, annotation_set_id)
    return Response(
        content=serialize_phase_json_export(export_result.payload),
        media_type="application/json",
        headers=export_result.headers,
    )


@router.get("/phase-annotation-sets/{annotation_set_id}/export/segments")
async def export_phase_annotation_set_segments_csv(
    annotation_set_id: int,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    export_result = iter_phase_segment_csv(db, annotation_set_id)
    return StreamingResponse(
        export_result.iterator,
        media_type="text/csv; charset=utf-8",
        headers=export_result.headers,
    )


@router.get("/phase-annotation-sets/{annotation_set_id}/export/framewise")
async def export_phase_annotation_set_framewise_csv(
    annotation_set_id: int,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    export_result = iter_phase_framewise_csv(db, annotation_set_id)
    return StreamingResponse(
        export_result.iterator,
        media_type="text/csv; charset=utf-8",
        headers=export_result.headers,
    )


@router.post(
    "/phase-annotation-sets/{annotation_set_id}/segments",
    response_model=ResearchPhaseMutationResponse,
)
async def create_phase_segment_route(
    annotation_set_id: int,
    payload: CreateResearchPhaseSegmentRequest,
    db: Session = Depends(get_db),
) -> ResearchPhaseMutationResponse:
    return create_phase_segment(db, annotation_set_id, payload)


@router.post(
    "/phase-annotation-sets/{annotation_set_id}/transition",
    response_model=ResearchPhaseMutationResponse,
)
async def transition_phase_route(
    annotation_set_id: int,
    payload: TransitionResearchPhaseRequest,
    db: Session = Depends(get_db),
) -> ResearchPhaseMutationResponse:
    return transition_phase(db, annotation_set_id, payload)


@router.post(
    "/phase-annotation-sets/{annotation_set_id}/close-active",
    response_model=ResearchPhaseMutationResponse,
)
async def close_active_phase_segment_route(
    annotation_set_id: int,
    payload: CloseActivePhaseSegmentRequest,
    db: Session = Depends(get_db),
) -> ResearchPhaseMutationResponse:
    return close_active_phase_segment(db, annotation_set_id, payload)


@router.patch("/phase-segments/{segment_id}", response_model=ResearchPhaseMutationResponse)
async def update_phase_segment_route(
    segment_id: int,
    payload: UpdateResearchPhaseSegmentRequest,
    db: Session = Depends(get_db),
) -> ResearchPhaseMutationResponse:
    return update_phase_segment(db, segment_id, payload)


@router.delete("/phase-segments/{segment_id}", response_model=ResearchPhaseMutationResponse)
async def delete_phase_segment_route(
    segment_id: int,
    expected_revision: int = Query(..., ge=1),
    db: Session = Depends(get_db),
) -> ResearchPhaseMutationResponse:
    return delete_phase_segment(db, segment_id, expected_revision)


@router.post("/phase-segments/{segment_id}/split", response_model=ResearchPhaseMutationResponse)
async def split_phase_segment_route(
    segment_id: int,
    payload: SplitResearchPhaseSegmentRequest,
    db: Session = Depends(get_db),
) -> ResearchPhaseMutationResponse:
    return split_phase_segment(db, segment_id, payload)


@router.post(
    "/phase-annotation-sets/{annotation_set_id}/merge",
    response_model=ResearchPhaseMutationResponse,
)
async def merge_phase_segments_route(
    annotation_set_id: int,
    payload: MergeResearchPhaseSegmentsRequest,
    db: Session = Depends(get_db),
) -> ResearchPhaseMutationResponse:
    return merge_phase_segments(db, annotation_set_id, payload)
