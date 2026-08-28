import logging
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Literal, Self

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from app.opportunity.evidence import FACTOR_SCHEMAS, SUPPORTED_FACTOR_KEYS
from app.opportunity.models import EvidenceRecord, validate_source_url
from app.opportunity.profile import DEFAULT_PROFILE
from app.opportunity.repository import OpportunityRepository
from app.opportunity.service import OpportunityService
from app.opportunity.workflow_service import OpportunityWorkflowService
from app.repository import ProjectRepository

router = APIRouter()
logger = logging.getLogger(__name__)
_OPAQUE_SNAPSHOT_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")


class EvidenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    factor_key: str = Field(min_length=1, max_length=100)
    value: Any
    value_type: Literal["bool", "number", "string", "range", "json"]
    observation_type: Literal["observed", "derived", "estimated", "assumed"]
    source_url: HttpUrl
    source_type: str = Field(min_length=1, max_length=50)
    source_grade: Literal["A", "B", "C", "D", "U"]
    observed_at: datetime
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    verification_status: Literal["verified", "partially_verified", "unverified", "conflicted", "invalidated"] = (
        "unverified"
    )
    independence_group: str = Field(min_length=1, max_length=100)
    raw_snapshot_ref: str | None = None
    supersedes_evidence_id: str | None = None

    @field_validator("source_url")
    @classmethod
    def safe_source_url(cls, value: HttpUrl) -> HttpUrl | str:
        return validate_source_url(value)

    @field_validator("raw_snapshot_ref")
    @classmethod
    def safe_snapshot_ref(cls, value: str | None) -> str | None:
        if value is not None and _OPAQUE_SNAPSHOT_REF.fullmatch(value) is None:
            raise ValueError("raw_snapshot_ref must be a safe opaque identifier")
        return value

    @model_validator(mode="after")
    def valid_factor_value(self) -> Self:
        if self.factor_key not in SUPPORTED_FACTOR_KEYS:
            raise ValueError(f"unsupported opportunity factor: {self.factor_key}")
        record = EvidenceRecord(**self.model_dump())
        schema = FACTOR_SCHEMAS[self.factor_key]
        if self.value_type != schema.value_type:
            raise ValueError(f"{self.factor_key} requires value_type {schema.value_type}")
        try:
            schema.normalize(record)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        return self


def get_project_repository() -> ProjectRepository:
    return ProjectRepository()


def get_opportunity_repository() -> Iterator[OpportunityRepository]:
    with OpportunityRepository() as repository:
        yield repository


def get_opportunity_service() -> Iterator[OpportunityService]:
    with OpportunityService() as service:
        yield service


def get_current_time() -> datetime:
    return datetime.now(UTC)


def get_opportunity_workflow_service() -> Iterator[OpportunityWorkflowService]:
    service = OpportunityWorkflowService()
    try:
        yield service
    finally:
        service.close()


def _require_project(project_id: str, repository: ProjectRepository) -> None:
    if repository.get_by_id(project_id) is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "PROJECT_NOT_FOUND", "message": "Project not found"},
        )


@router.post(
    "/projects/{project_id}/opportunity/evidence",
    status_code=status.HTTP_201_CREATED,
)
def add_evidence(
    project_id: str,
    payload: EvidenceCreate,
    project_repository: ProjectRepository = Depends(get_project_repository),
    opportunity_repository: OpportunityRepository = Depends(get_opportunity_repository),
) -> dict[str, Any]:
    _require_project(project_id, project_repository)
    record = EvidenceRecord(project_id=project_id, **payload.model_dump())
    try:
        stored = opportunity_repository.add_evidence(record)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "data": stored.model_dump(mode="json")}


@router.get("/projects/{project_id}/opportunity/evidence")
def list_evidence(
    project_id: str,
    project_repository: ProjectRepository = Depends(get_project_repository),
    opportunity_repository: OpportunityRepository = Depends(get_opportunity_repository),
) -> dict[str, Any]:
    _require_project(project_id, project_repository)
    evidence = opportunity_repository.list_evidence(project_id, include_invalid=True)
    return {
        "ok": True,
        "data": {"evidence": [record.model_dump(mode="json") for record in evidence]},
    }


@router.post("/projects/{project_id}/opportunity/evaluate")
def evaluate(
    project_id: str,
    service: OpportunityService = Depends(get_opportunity_service),
) -> dict[str, Any]:
    try:
        assessment = service.evaluate(project_id, persist=True)
    except LookupError:
        raise HTTPException(
            status_code=404,
            detail={"code": "PROJECT_NOT_FOUND", "message": "Project not found"},
        ) from None
    return {"ok": True, "data": assessment.model_dump(mode="json")}


@router.get("/projects/{project_id}/opportunity")
def get_assessment(
    project_id: str,
    project_repository: ProjectRepository = Depends(get_project_repository),
    opportunity_repository: OpportunityRepository = Depends(get_opportunity_repository),
    now: datetime = Depends(get_current_time),
) -> dict[str, Any]:
    _require_project(project_id, project_repository)
    assessment = opportunity_repository.latest_assessment(project_id, DEFAULT_PROFILE.profile_id)
    stale = assessment is not None and now >= assessment.expires_at
    review_due = assessment is not None and now >= assessment.review_at
    return {
        "ok": True,
        "data": {
            "assessment": (assessment.model_dump(mode="json") if assessment is not None else None),
            "stale": stale,
            "review_due": review_due,
        },
    }


@router.get("/projects/{project_id}/opportunity/workflow")
def get_opportunity_workflow(
    project_id: str,
    service: OpportunityWorkflowService = Depends(get_opportunity_workflow_service),
    now: datetime = Depends(get_current_time),
) -> dict[str, Any]:
    try:
        projection = service.get_project_workflow(project_id, now)
    except LookupError:
        raise HTTPException(
            status_code=404,
            detail={"code": "PROJECT_NOT_FOUND", "message": "Project not found"},
        ) from None
    except Exception as exc:
        # 记录异常类型与堆栈（exc_info 不进入 getMessage，故不泄露持久化明文），
        # 但绝不把 str(exc) 拼进消息——它可能带有 assessment_json 等敏感原文。
        logger.error(
            "opportunity.workflow.projection_error project_id=%s error_type=%s",
            project_id,
            type(exc).__name__,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "code": "OPPORTUNITY_WORKFLOW_PROJECTION_ERROR",
                "message": "Failed to build opportunity workflow projection",
            },
        ) from None

    data = projection.model_dump(mode="json")
    opportunity = data.get("opportunity") or {}
    workflow = data.get("workflow") or {}
    next_action = workflow.get("next_action") or {}
    logger.info(
        "opportunity.workflow.projected project_id=%s assessment_id=%s state=%s cta_key=%s",
        project_id,
        opportunity.get("assessment_id"),
        workflow.get("state"),
        next_action.get("key"),
    )
    return {"ok": True, "data": data}
