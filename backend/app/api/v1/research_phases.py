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
    CreateResearchPhaseLabelMappingProfileRequest,
    DuplicateResearchPhaseLabelMappingProfileRequest,
    MergeResearchPhaseMappingClassesRequest,
    MergeResearchPhaseSegmentsRequest,
    ReopenResearchPhaseAnnotationSetRequest,
    ResearchPhaseAnnotationSetDetail,
    ResearchPhaseLabelMappingProfileDetail,
    ResearchPhaseLabelMappingProfileSummary,
    ResearchPhaseAnnotationSetSummary,
    ResearchPhaseMutationResponse,
    ResearchPhaseProtocolDetail,
    ResearchPhaseProtocolSummary,
    ResearchPhaseStatusMutationResponse,
    ResearchPhaseValidationResponse,
    SplitResearchPhaseSegmentRequest,
    SubmitResearchPhaseAnnotationSetRequest,
    TransitionResearchPhaseRequest,
    UnmergeResearchPhaseMappingTargetRequest,
    UpdateResearchPhaseLabelMappingProfileRequest,
    UpdateResearchPhaseSegmentRequest,
)
from app.services.phase_label_mapping import (
    archive_mapping_profile,
    create_mapping_profile,
    duplicate_mapping_profile,
    get_mapping_profile,
    list_mapping_profiles,
    merge_mapping_classes,
    publish_mapping_profile,
    unmerge_mapping_target,
    update_mapping_profile,
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
    mapping_profile_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Response:
    export_result = build_phase_json_export(db, annotation_set_id, mapping_profile_id=mapping_profile_id)
    return Response(
        content=serialize_phase_json_export(export_result.payload),
        media_type="application/json; charset=utf-8",
        headers=export_result.headers,
    )


@router.get(
    "/phase-protocols/{protocol_id}/label-mapping-profiles",
    response_model=list[ResearchPhaseLabelMappingProfileSummary],
)
async def list_phase_label_mapping_profiles(
    protocol_id: int,
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> list[ResearchPhaseLabelMappingProfileSummary]:
    return list_mapping_profiles(db, protocol_id, include_archived=include_archived)


@router.post(
    "/phase-protocols/{protocol_id}/label-mapping-profiles",
    response_model=ResearchPhaseLabelMappingProfileDetail,
)
async def create_phase_label_mapping_profile(
    protocol_id: int,
    payload: CreateResearchPhaseLabelMappingProfileRequest,
    db: Session = Depends(get_db),
) -> ResearchPhaseLabelMappingProfileDetail:
    return create_mapping_profile(db, protocol_id, payload)


@router.get(
    "/phase-label-mapping-profiles/{profile_id}",
    response_model=ResearchPhaseLabelMappingProfileDetail,
)
async def read_phase_label_mapping_profile(
    profile_id: int,
    db: Session = Depends(get_db),
) -> ResearchPhaseLabelMappingProfileDetail:
    return get_mapping_profile(db, profile_id)


@router.patch(
    "/phase-label-mapping-profiles/{profile_id}",
    response_model=ResearchPhaseLabelMappingProfileDetail,
)
async def update_phase_label_mapping_profile(
    profile_id: int,
    payload: UpdateResearchPhaseLabelMappingProfileRequest,
    db: Session = Depends(get_db),
) -> ResearchPhaseLabelMappingProfileDetail:
    return update_mapping_profile(db, profile_id, payload)


@router.post(
    "/phase-label-mapping-profiles/{profile_id}/merge-classes",
    response_model=ResearchPhaseLabelMappingProfileDetail,
)
async def merge_phase_label_mapping_classes(
    profile_id: int,
    payload: MergeResearchPhaseMappingClassesRequest,
    db: Session = Depends(get_db),
) -> ResearchPhaseLabelMappingProfileDetail:
    return merge_mapping_classes(db, profile_id, payload)


@router.post(
    "/phase-label-mapping-profiles/{profile_id}/unmerge-target",
    response_model=ResearchPhaseLabelMappingProfileDetail,
)
async def unmerge_phase_label_mapping_target(
    profile_id: int,
    payload: UnmergeResearchPhaseMappingTargetRequest,
    db: Session = Depends(get_db),
) -> ResearchPhaseLabelMappingProfileDetail:
    return unmerge_mapping_target(db, profile_id, payload)


@router.post(
    "/phase-label-mapping-profiles/{profile_id}/publish",
    response_model=ResearchPhaseLabelMappingProfileDetail,
)
async def publish_phase_label_mapping_profile(
    profile_id: int,
    db: Session = Depends(get_db),
) -> ResearchPhaseLabelMappingProfileDetail:
    return publish_mapping_profile(db, profile_id)


@router.post(
    "/phase-label-mapping-profiles/{profile_id}/duplicate",
    response_model=ResearchPhaseLabelMappingProfileDetail,
)
async def duplicate_phase_label_mapping_profile(
    profile_id: int,
    payload: DuplicateResearchPhaseLabelMappingProfileRequest,
    db: Session = Depends(get_db),
) -> ResearchPhaseLabelMappingProfileDetail:
    return duplicate_mapping_profile(db, profile_id, payload)


@router.post(
    "/phase-label-mapping-profiles/{profile_id}/archive",
    response_model=ResearchPhaseLabelMappingProfileDetail,
)
async def archive_phase_label_mapping_profile(
    profile_id: int,
    db: Session = Depends(get_db),
) -> ResearchPhaseLabelMappingProfileDetail:
    return archive_mapping_profile(db, profile_id)


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
