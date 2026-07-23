from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.research_skill import (
    ActivateResearchSkillRubricResponse,
    ArchiveResearchSkillRubricResponse,
    CloneResearchSkillRubricRequest,
    CreateResearchSkillAssessmentRequest,
    CreateResearchSkillAssessmentResponse,
    CreateResearchSkillCriterionRequest,
    CreateResearchSkillEvidenceRequest,
    CreateResearchSkillRubricRequest,
    ReopenResearchSkillAssessmentRequest,
    ResearchSkillAssessmentDetail,
    ResearchSkillAssessmentSummary,
    ResearchSkillCriterionResponse,
    ResearchSkillMutationResponse,
    ResearchSkillRubricDetail,
    ResearchSkillRubricSummary,
    ResearchSkillStatusMutationResponse,
    ResearchSkillValidationResponse,
    SubmitResearchSkillAssessmentRequest,
    UpdateResearchSkillAssessmentRequest,
    UpdateResearchSkillCriterionRequest,
    UpdateResearchSkillEvidenceRequest,
    UpdateResearchSkillRubricRequest,
    UpsertResearchSkillScoreRequest,
)
from app.services.research_skill_export_service import (
    build_skill_json_export,
    iter_skill_csv_export,
    serialize_skill_json_export,
)
from app.services.research_skill_service import (
    activate_skill_rubric,
    archive_skill_rubric,
    clone_skill_rubric,
    create_skill_criterion,
    create_skill_evidence,
    create_skill_rubric,
    delete_skill_evidence,
    delete_skill_score,
    get_or_create_skill_assessment,
    get_skill_assessment,
    get_skill_rubric,
    list_skill_rubrics,
    list_video_skill_assessments,
    reopen_skill_assessment,
    submit_skill_assessment,
    update_skill_assessment,
    update_skill_criterion,
    update_skill_evidence,
    update_skill_rubric,
    upsert_skill_score,
)
from app.services.research_skill_validation_service import validate_skill_assessment

router = APIRouter()


@router.get("/skill-rubrics", response_model=list[ResearchSkillRubricSummary])
async def list_skill_rubrics_route(
    status: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> list[ResearchSkillRubricSummary]:
    return list_skill_rubrics(db, status_filter=status, include_archived=include_archived)


@router.get("/skill-rubrics/{rubric_id}", response_model=ResearchSkillRubricDetail)
async def read_skill_rubric(rubric_id: int, db: Session = Depends(get_db)) -> ResearchSkillRubricDetail:
    return get_skill_rubric(db, rubric_id)


@router.post(
    "/skill-rubrics",
    response_model=ResearchSkillRubricDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_skill_rubric_route(
    payload: CreateResearchSkillRubricRequest,
    db: Session = Depends(get_db),
) -> ResearchSkillRubricDetail:
    return create_skill_rubric(db, payload)


@router.patch("/skill-rubrics/{rubric_id}", response_model=ResearchSkillRubricDetail)
async def update_skill_rubric_route(
    rubric_id: int,
    payload: UpdateResearchSkillRubricRequest,
    db: Session = Depends(get_db),
) -> ResearchSkillRubricDetail:
    return update_skill_rubric(db, rubric_id, payload)


@router.post("/skill-rubrics/{rubric_id}/clone", response_model=ResearchSkillRubricDetail)
async def clone_skill_rubric_route(
    rubric_id: int,
    payload: CloneResearchSkillRubricRequest,
    db: Session = Depends(get_db),
) -> ResearchSkillRubricDetail:
    return clone_skill_rubric(db, rubric_id, payload)


@router.post("/skill-rubrics/{rubric_id}/activate", response_model=ActivateResearchSkillRubricResponse)
async def activate_skill_rubric_route(
    rubric_id: int,
    db: Session = Depends(get_db),
) -> ActivateResearchSkillRubricResponse:
    return activate_skill_rubric(db, rubric_id)


@router.post("/skill-rubrics/{rubric_id}/archive", response_model=ArchiveResearchSkillRubricResponse)
async def archive_skill_rubric_route(
    rubric_id: int,
    db: Session = Depends(get_db),
) -> ArchiveResearchSkillRubricResponse:
    return archive_skill_rubric(db, rubric_id)


@router.post(
    "/skill-rubrics/{rubric_id}/criteria",
    response_model=ResearchSkillCriterionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_skill_criterion_route(
    rubric_id: int,
    payload: CreateResearchSkillCriterionRequest,
    db: Session = Depends(get_db),
) -> ResearchSkillCriterionResponse:
    return create_skill_criterion(db, rubric_id, payload)


@router.patch("/skill-criteria/{criterion_id}", response_model=ResearchSkillCriterionResponse)
async def update_skill_criterion_route(
    criterion_id: int,
    payload: UpdateResearchSkillCriterionRequest,
    db: Session = Depends(get_db),
) -> ResearchSkillCriterionResponse:
    return update_skill_criterion(db, criterion_id, payload)


@router.get("/videos/{video_id}/skill-assessments", response_model=list[ResearchSkillAssessmentSummary])
async def list_video_skill_assessments_route(
    video_id: int,
    db: Session = Depends(get_db),
) -> list[ResearchSkillAssessmentSummary]:
    return list_video_skill_assessments(db, video_id)


@router.post("/videos/{video_id}/skill-assessments", response_model=CreateResearchSkillAssessmentResponse)
async def create_or_get_skill_assessment_route(
    video_id: int,
    payload: CreateResearchSkillAssessmentRequest,
    db: Session = Depends(get_db),
) -> CreateResearchSkillAssessmentResponse:
    return get_or_create_skill_assessment(db, video_id, payload)


@router.get("/skill-assessments/{assessment_id}", response_model=ResearchSkillAssessmentDetail)
async def read_skill_assessment(
    assessment_id: int,
    db: Session = Depends(get_db),
) -> ResearchSkillAssessmentDetail:
    return get_skill_assessment(db, assessment_id)


@router.patch("/skill-assessments/{assessment_id}", response_model=ResearchSkillMutationResponse)
async def update_skill_assessment_route(
    assessment_id: int,
    payload: UpdateResearchSkillAssessmentRequest,
    db: Session = Depends(get_db),
) -> ResearchSkillMutationResponse:
    return update_skill_assessment(db, assessment_id, payload)


@router.put(
    "/skill-assessments/{assessment_id}/scores/{criterion_id}",
    response_model=ResearchSkillMutationResponse,
)
async def upsert_skill_score_route(
    assessment_id: int,
    criterion_id: int,
    payload: UpsertResearchSkillScoreRequest,
    db: Session = Depends(get_db),
) -> ResearchSkillMutationResponse:
    return upsert_skill_score(db, assessment_id, criterion_id, payload)


@router.delete("/skill-scores/{score_id}", response_model=ResearchSkillMutationResponse)
async def delete_skill_score_route(
    score_id: int,
    expected_revision: int = Query(..., ge=1),
    db: Session = Depends(get_db),
) -> ResearchSkillMutationResponse:
    return delete_skill_score(db, score_id, expected_revision)


@router.post(
    "/skill-scores/{score_id}/evidence",
    response_model=ResearchSkillMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_skill_evidence_route(
    score_id: int,
    payload: CreateResearchSkillEvidenceRequest,
    db: Session = Depends(get_db),
) -> ResearchSkillMutationResponse:
    return create_skill_evidence(db, score_id, payload)


@router.patch("/skill-evidence/{evidence_id}", response_model=ResearchSkillMutationResponse)
async def update_skill_evidence_route(
    evidence_id: int,
    payload: UpdateResearchSkillEvidenceRequest,
    db: Session = Depends(get_db),
) -> ResearchSkillMutationResponse:
    return update_skill_evidence(db, evidence_id, payload)


@router.delete("/skill-evidence/{evidence_id}", response_model=ResearchSkillMutationResponse)
async def delete_skill_evidence_route(
    evidence_id: int,
    expected_revision: int = Query(..., ge=1),
    db: Session = Depends(get_db),
) -> ResearchSkillMutationResponse:
    return delete_skill_evidence(db, evidence_id, expected_revision)


@router.get("/skill-assessments/{assessment_id}/validate", response_model=ResearchSkillValidationResponse)
async def validate_skill_assessment_route(
    assessment_id: int,
    db: Session = Depends(get_db),
) -> ResearchSkillValidationResponse:
    return validate_skill_assessment(db, assessment_id)


@router.post(
    "/skill-assessments/{assessment_id}/submit",
    response_model=ResearchSkillStatusMutationResponse,
)
async def submit_skill_assessment_route(
    assessment_id: int,
    payload: SubmitResearchSkillAssessmentRequest,
    db: Session = Depends(get_db),
) -> ResearchSkillStatusMutationResponse:
    return submit_skill_assessment(db, assessment_id, payload)


@router.post(
    "/skill-assessments/{assessment_id}/reopen",
    response_model=ResearchSkillStatusMutationResponse,
)
async def reopen_skill_assessment_route(
    assessment_id: int,
    payload: ReopenResearchSkillAssessmentRequest,
    db: Session = Depends(get_db),
) -> ResearchSkillStatusMutationResponse:
    return reopen_skill_assessment(db, assessment_id, payload)


@router.get("/skill-assessments/{assessment_id}/export/json")
async def export_skill_assessment_json(
    assessment_id: int,
    db: Session = Depends(get_db),
) -> Response:
    export_result = build_skill_json_export(db, assessment_id)
    return Response(
        content=serialize_skill_json_export(export_result.payload),
        media_type="application/json",
        headers=export_result.headers,
    )


@router.get("/skill-assessments/{assessment_id}/export/csv")
async def export_skill_assessment_csv(
    assessment_id: int,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    export_result = iter_skill_csv_export(db, assessment_id)
    return StreamingResponse(
        export_result.iterator,
        media_type="text/csv; charset=utf-8",
        headers=export_result.headers,
    )
