"""Pure deterministic Opportunity Action Workflow projection.

This module never touches a database, repository, LLM, or assessment evaluator.
It only maps already-persisted project/assessment/evidence/task/interaction
inputs into a stable JSON-safe projection for later service/API/UI layers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.opportunity.decision import (
    BLOCK_REASON_ACTIONS,
    IGNORE_REASON_ACTIONS,
    WATCH_REASON_ACTIONS,
)
from app.opportunity.models import (
    ConfidenceSet,
    DecisionStatus,
    EconomicsResult,
    EvidenceRecord,
    MoneyRange,
    OpportunityAssessment,
    ProbabilityRange,
    RiskSet,
)

WORKFLOW_VERSION = "opportunity-action-workflow-v1"
LEGACY_MODEL_VERSION = "score-v1.4"
OPPORTUNITY_MODEL_VERSION = "opportunity-v2.0"
OPPORTUNITY_PROFILE_VERSION = "low-cost-curated-multiwallet-v1"

ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "planned": ("active", "abandoned"),
    "active": ("done", "abandoned"),
    "done": (),
    "abandoned": (),
}

WorkflowState = Literal[
    "NEEDS_EVALUATION",
    "REVIEW_REQUIRED",
    "ACTIONABLE",
    "MONITOR",
    "INSUFFICIENT_EVIDENCE",
    "BLOCKED",
    "NOT_FIT",
]

ActionPhase = Literal["review", "evidence", "validation", "maintenance", "outcome"]

_PHASE_RANK = {
    "review": 0,
    "evidence": 1,
    "validation": 2,
    "maintenance": 3,
    "outcome": 4,
}

_CATEGORY_PHASE: dict[str, ActionPhase] = {
    "research": "evidence",
    "risk": "evidence",
    "official": "validation",
    "testnet": "validation",
    "mainnet": "validation",
    "social": "maintenance",
    "dev": "maintenance",
    "track": "outcome",
}

_OPEN_STATUSES = frozenset({"planned", "active"})
_TERMINAL_STATUSES = frozenset({"done", "abandoned"})
_GRADE_KEYS = ("A", "B", "C", "D", "U")

_OUTCOME_FIELDS = (
    "actual_hard_cost_usd",
    "actual_time_minutes",
    "eligibility_result",
    "survival_result",
    "disqualification_reason",
    "reward_received_usd",
    "claim_cost_usd",
    "outcome_observed_at",
)

_VALIDATION_SAFE_FIELDS = (
    "id",
    "project_id",
    "status",
    "created_at",
    "wallet_count",
    "opportunity_assessment_id",
    "opportunity_model_version",
    "opportunity_profile_version",
    *_OUTCOME_FIELDS,
)

_BLOCKER_SEVERITY = {
    "SAFETY_BLOCK": "critical",
    "INTEGRITY_BLOCK": "critical",
    "RULE_BLOCK": "high",
}


class LegacyDecisionProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: Literal["score-v1.4"] = LEGACY_MODEL_VERSION
    score: int | float | None = None
    label: str | None = None
    reason: tuple[str, ...] = ()
    authoritative: Literal[True] = True


class OpportunitySummaryProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    shadow: Literal[True] = True
    assessment_id: str | None = None
    model_version: Literal["opportunity-v2.0"] = OPPORTUNITY_MODEL_VERSION
    profile_version: Literal["low-cost-curated-multiwallet-v1"] = OPPORTUNITY_PROFILE_VERSION
    status: DecisionStatus
    public_label: Literal["FARM", "WATCH", "IGNORE"]
    recommended_action: str
    blocker_codes: tuple[str, ...] = ()
    watch_reason_codes: tuple[str, ...] = ()
    ignore_reason_codes: tuple[str, ...] = ()
    requires_remediation: bool = False
    confidence: ConfidenceSet
    event_probability: ProbabilityRange | None = None
    eligibility_probability: ProbabilityRange | None = None
    survival_probability: ProbabilityRange | None = None
    reward_probability: ProbabilityRange | None = None
    conditional_reward_usd: MoneyRange | None = None
    hard_cost_usd: MoneyRange | None = None
    economics: EconomicsResult | None = None
    risks: RiskSet
    scored_at: datetime
    review_at: datetime
    expires_at: datetime


class NextActionProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    label: str
    can_start_validation: bool = False


class ActionPlanItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    sequence: int
    kind: str
    phase: ActionPhase
    title: str
    description: str
    required: bool
    source: str
    priority: int = 100
    task_id: str | None = None
    external_url: str | None = None


class BlockerProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    severity: str
    message: str


class UpgradeConditionProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str


class WorkflowSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: WorkflowState
    next_action: NextActionProjection
    action_plan: tuple[ActionPlanItem, ...] = ()
    blockers: tuple[BlockerProjection, ...] = ()
    upgrade_conditions: tuple[UpgradeConditionProjection, ...] = ()


class EvidenceItemProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str | None = None
    factor_key: str
    value: Any
    value_type: str
    observation_type: str
    source_url: str
    source_type: str
    source_grade: Literal["A", "B", "C", "D", "U"]
    verification_status: str
    observed_at: datetime
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    freshness: Literal["CURRENT", "EXPIRED"]
    age_days: int = Field(ge=0)

    @field_serializer("value", when_used="json")
    def serialize_value(self, value: Any) -> Any:
        return _json_safe(value)


class EvidenceSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[EvidenceItemProjection, ...] = ()
    missing_factor_keys: tuple[str, ...] = ()
    counts_by_grade: dict[str, int]


class ValidationHistorySummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total: int = 0
    by_status: dict[str, int]


class ValidationSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    current: dict[str, Any] | None = None
    history_summary: ValidationHistorySummary
    allowed_transitions: dict[str, list[str]]
    can_start_validation: bool = False


class OpportunityWorkflowProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_version: Literal["opportunity-action-workflow-v1"] = WORKFLOW_VERSION
    project_id: str
    legacy: LegacyDecisionProjection
    opportunity: OpportunitySummaryProjection | None
    workflow: WorkflowSection
    evidence: EvidenceSection
    validation: ValidationSection
    review_at: datetime | None = None
    expires_at: datetime | None = None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def build_workflow_projection(
    *,
    project: Mapping[str, Any],
    assessment: OpportunityAssessment | None,
    evidence: Sequence[EvidenceRecord],
    participation_tasks: Sequence[Mapping[str, Any]],
    interactions: Sequence[Mapping[str, Any]],
    now: datetime,
) -> OpportunityWorkflowProjection:
    """Build a pure, deterministic, idempotent workflow projection."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    project_id = str(project.get("id") or project.get("project_id") or "")
    if not project_id:
        raise ValueError("project.id is required")

    state = _derive_state(assessment=assessment, now=now)
    missing_factor_keys = _missing_factor_keys(assessment)
    linked_interactions = _linked_interactions(assessment=assessment, interactions=interactions)
    current_validation = _select_current_validation(linked_interactions)
    next_action = _derive_next_action(
        state=state,
        assessment=assessment,
        current_validation=current_validation,
    )
    action_plan = _build_action_plan(
        state=state,
        assessment=assessment,
        missing_factor_keys=missing_factor_keys,
        participation_tasks=participation_tasks,
    )
    blockers = _build_blockers(assessment)
    upgrade_conditions = _build_upgrade_conditions(
        assessment=assessment,
        missing_factor_keys=missing_factor_keys,
    )
    evidence_section = _project_evidence(
        evidence=evidence,
        missing_factor_keys=missing_factor_keys,
        now=now,
    )
    validation = ValidationSection(
        current=current_validation,
        history_summary=_history_summary(linked_interactions),
        allowed_transitions={
            status: list(targets) for status, targets in ALLOWED_TRANSITIONS.items()
        },
        can_start_validation=state == "ACTIONABLE",
    )

    return OpportunityWorkflowProjection(
        project_id=project_id,
        legacy=_project_legacy(project),
        opportunity=_project_opportunity(assessment),
        workflow=WorkflowSection(
            state=state,
            next_action=next_action,
            action_plan=action_plan,
            blockers=blockers,
            upgrade_conditions=upgrade_conditions,
        ),
        evidence=evidence_section,
        validation=validation,
        review_at=assessment.review_at if assessment is not None else None,
        expires_at=assessment.expires_at if assessment is not None else None,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _derive_state(*, assessment: OpportunityAssessment | None, now: datetime) -> WorkflowState:
    if assessment is None:
        return "NEEDS_EVALUATION"
    current = _as_utc(now)
    if current >= _as_utc(assessment.review_at) or current >= _as_utc(assessment.expires_at):
        return "REVIEW_REQUIRED"
    return assessment.status.value  # type: ignore[return-value]


def _project_legacy(project: Mapping[str, Any]) -> LegacyDecisionProjection:
    reason = project.get("reason")
    if reason is None:
        reasons: tuple[str, ...] = ()
    elif isinstance(reason, str):
        reasons = (reason,) if reason else ()
    elif isinstance(reason, Sequence):
        reasons = tuple(str(item) for item in reason)
    else:
        reasons = (str(reason),)
    return LegacyDecisionProjection(
        score=project.get("score"),
        label=project.get("label"),
        reason=reasons,
    )


def _project_opportunity(
    assessment: OpportunityAssessment | None,
) -> OpportunitySummaryProjection | None:
    if assessment is None:
        return None
    return OpportunitySummaryProjection(
        assessment_id=assessment.assessment_id,
        model_version=assessment.model_version,
        profile_version=assessment.profile_version,
        status=assessment.status,
        public_label=assessment.public_label,
        recommended_action=assessment.recommended_action,
        blocker_codes=assessment.blocker_codes,
        watch_reason_codes=assessment.watch_reason_codes,
        ignore_reason_codes=assessment.ignore_reason_codes,
        requires_remediation=assessment.requires_remediation,
        confidence=assessment.confidence,
        event_probability=assessment.event_probability,
        eligibility_probability=assessment.eligibility_probability,
        survival_probability=assessment.survival_probability,
        reward_probability=assessment.reward_probability,
        conditional_reward_usd=assessment.conditional_reward_usd,
        hard_cost_usd=assessment.hard_cost_usd,
        economics=assessment.economics,
        risks=assessment.risks,
        scored_at=assessment.scored_at,
        review_at=assessment.review_at,
        expires_at=assessment.expires_at,
    )


def _missing_factor_keys(assessment: OpportunityAssessment | None) -> tuple[str, ...]:
    if assessment is None:
        return ()
    snapshot = assessment.factor_snapshot or {}
    raw = snapshot.get("critical_unknowns", ())
    if raw is None:
        return ()
    if isinstance(raw, str):
        values = (raw,)
    elif isinstance(raw, Sequence):
        values = tuple(str(item) for item in raw)
    else:
        values = (str(raw),)
    return tuple(sorted(values))


def _derive_next_action(
    *,
    state: WorkflowState,
    assessment: OpportunityAssessment | None,
    current_validation: Mapping[str, Any] | None,
) -> NextActionProjection:
    if state == "NEEDS_EVALUATION":
        return NextActionProjection(
            key="evaluate",
            label="运行 Opportunity 评估",
            can_start_validation=False,
        )
    if state == "REVIEW_REQUIRED":
        return NextActionProjection(
            key="re_evaluate",
            label="重新评估",
            can_start_validation=False,
        )
    if state == "ACTIONABLE":
        open_current = (
            current_validation is not None
            and str(current_validation.get("status") or "") in _OPEN_STATUSES
        )
        if open_current:
            return NextActionProjection(
                key="continue_validation",
                label="继续验证",
                can_start_validation=True,
            )
        return NextActionProjection(
            key="start_validation",
            label="开始验证",
            can_start_validation=True,
        )
    if state == "MONITOR":
        label = (
            assessment.recommended_action
            if assessment is not None and assessment.recommended_action
            else "监控升级条件并等待复评窗口。"
        )
        return NextActionProjection(key="monitor", label=label, can_start_validation=False)
    if state == "INSUFFICIENT_EVIDENCE":
        label = (
            assessment.recommended_action
            if assessment is not None and assessment.recommended_action
            else "补齐关键证据后再评估。"
        )
        return NextActionProjection(
            key="collect_evidence",
            label=label,
            can_start_validation=False,
        )
    if state == "BLOCKED":
        label = (
            assessment.recommended_action
            if assessment is not None and assessment.recommended_action
            else "在可信整改证据出现前不要交互。"
        )
        return NextActionProjection(key="remediate", label=label, can_start_validation=False)
    label = (
        assessment.recommended_action
        if assessment is not None and assessment.recommended_action
        else "当前画像下不分配时间或资金。"
    )
    return NextActionProjection(key="not_fit", label=label, can_start_validation=False)


def _safe_http_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return None


def _build_action_plan(
    *,
    state: WorkflowState,
    assessment: OpportunityAssessment | None,
    missing_factor_keys: Sequence[str],
    participation_tasks: Sequence[Mapping[str, Any]],
) -> tuple[ActionPlanItem, ...]:
    items: list[dict[str, Any]] = []

    if state in {"NEEDS_EVALUATION", "REVIEW_REQUIRED"}:
        items.append(
            {
                "id": "review-reassess" if state == "REVIEW_REQUIRED" else "review-evaluate",
                "kind": "review",
                "phase": "review",
                "title": "重新评估" if state == "REVIEW_REQUIRED" else "运行 Opportunity 评估",
                "description": (
                    "评估已到期或过期，使用现有评估入口重新生成 Shadow 评估。"
                    if state == "REVIEW_REQUIRED"
                    else "尚无 Opportunity 评估，先运行现有评估入口。"
                ),
                "required": True,
                "source": "workflow",
                "priority": 1,
                "task_id": None,
                "external_url": None,
            }
        )

    if assessment is not None and missing_factor_keys:
        for key in missing_factor_keys:
            items.append(
                {
                    "id": f"evidence-{key}",
                    "kind": "evidence_gap",
                    "phase": "evidence",
                    "title": f"补齐证据: {key}",
                    "description": f"收集并验证关键因子 {key} 的可信证据。",
                    "required": True,
                    "source": "critical_unknowns",
                    "priority": 1,
                    "task_id": None,
                    "external_url": None,
                }
            )

    if state == "ACTIONABLE":
        items.append(
            {
                "id": "validation-1-2-wallets",
                "kind": "validation",
                "phase": "validation",
                "title": "1-2 钱包小样本验证",
                "description": (
                    assessment.recommended_action
                    if assessment is not None
                    else "用 1-2 个钱包记录真实成本与时间。"
                ),
                "required": True,
                "source": "workflow",
                "priority": 1,
                "task_id": None,
                "external_url": None,
            }
        )
        items.append(
            {
                "id": "outcome-record-cost-time",
                "kind": "outcome",
                "phase": "outcome",
                "title": "记录实际成本/时间与结果",
                "description": "在验证交互中填写 outcome 字段，供后续校准使用。",
                "required": True,
                "source": "workflow",
                "priority": 2,
                "task_id": None,
                "external_url": None,
            }
        )
        items.append(
            {
                "id": "maintenance-reassess-before-expand",
                "kind": "maintenance",
                "phase": "maintenance",
                "title": "扩大样本前重新评估",
                "description": "在扩大钱包数量前基于真实成本/时间重新评估。",
                "required": False,
                "source": "workflow",
                "priority": 3,
                "task_id": None,
                "external_url": None,
            }
        )

    if assessment is not None:
        for task in participation_tasks:
            task_id = str(task.get("id") or task.get("task_id") or "").strip()
            if not task_id:
                continue
            category = str(task.get("category") or "official")
            phase = _CATEGORY_PHASE.get(category, "maintenance")
            priority_raw = task.get("priority", 100)
            try:
                priority = int(priority_raw)
            except (TypeError, ValueError):
                priority = 100
            items.append(
                {
                    "id": f"task-{task_id}",
                    "kind": "participation_task",
                    "phase": phase,
                    "title": str(task.get("title") or task_id),
                    "description": str(task.get("description") or task.get("why") or task_id),
                    "required": bool(task.get("required", False)),
                    "source": "participation_tasks",
                    "priority": priority,
                    "task_id": task_id,
                    "external_url": _safe_http_url(task.get("link") or task.get("url")),
                }
            )

    items.sort(
        key=lambda item: (
            _PHASE_RANK[item["phase"]],
            item["priority"],
            0 if item["required"] else 1,
            item["id"],
        )
    )
    return tuple(
        ActionPlanItem(
            id=item["id"],
            sequence=index,
            kind=item["kind"],
            phase=item["phase"],
            title=item["title"],
            description=item["description"],
            required=item["required"],
            source=item["source"],
            priority=item["priority"],
            task_id=item["task_id"],
            external_url=item["external_url"],
        )
        for index, item in enumerate(items, start=1)
    )


def _build_blockers(
    assessment: OpportunityAssessment | None,
) -> tuple[BlockerProjection, ...]:
    if assessment is None:
        return ()
    codes = sorted({str(code) for code in assessment.blocker_codes if code})
    blockers: list[BlockerProjection] = []
    for code in codes:
        message = BLOCK_REASON_ACTIONS.get(
            code,
            f"Blocked by {code}; do not interact until remediation evidence is verified.",
        )
        blockers.append(
            BlockerProjection(
                code=code,
                severity=_BLOCKER_SEVERITY.get(code, "high"),
                message=message,
            )
        )
    return tuple(blockers)


def _build_upgrade_conditions(
    *,
    assessment: OpportunityAssessment | None,
    missing_factor_keys: Sequence[str],
) -> tuple[UpgradeConditionProjection, ...]:
    if assessment is None:
        return ()

    conditions: dict[str, str] = {}
    for code in assessment.watch_reason_codes:
        text = WATCH_REASON_ACTIONS.get(str(code), f"Resolve watch reason {code}.")
        conditions[str(code)] = text
    for code in assessment.ignore_reason_codes:
        text = IGNORE_REASON_ACTIONS.get(str(code), f"Resolve ignore reason {code}.")
        conditions[str(code)] = text
    for key in missing_factor_keys:
        conditions[f"MISSING_{key}"] = f"Provide verified evidence for critical factor {key}."

    return tuple(
        UpgradeConditionProjection(code=code, message=conditions[code])
        for code in sorted(conditions)
    )


def _project_evidence(
    *,
    evidence: Sequence[EvidenceRecord],
    missing_factor_keys: Sequence[str],
    now: datetime,
) -> EvidenceSection:
    current = _as_utc(now)
    items: list[EvidenceItemProjection] = []
    counts = {grade: 0 for grade in _GRADE_KEYS}

    # observed_at DESC, evidence_id DESC
    ordered = sorted(
        evidence,
        key=lambda record: (
            _as_utc(record.observed_at),
            record.evidence_id or "",
        ),
        reverse=True,
    )

    for record in ordered:
        expires_at = record.expires_at
        freshness: Literal["CURRENT", "EXPIRED"] = (
            "EXPIRED"
            if expires_at is not None and current >= _as_utc(expires_at)
            else "CURRENT"
        )
        age_seconds = (current - _as_utc(record.observed_at)).total_seconds()
        age_days = max(0, int(age_seconds // 86400))
        counts[record.source_grade] = counts.get(record.source_grade, 0) + 1
        items.append(
            EvidenceItemProjection(
                evidence_id=record.evidence_id,
                factor_key=record.factor_key,
                value=_json_safe(record.value),
                value_type=record.value_type,
                observation_type=record.observation_type,
                source_url=str(record.source_url),
                source_type=record.source_type,
                source_grade=record.source_grade,
                verification_status=record.verification_status,
                observed_at=record.observed_at,
                effective_at=record.effective_at,
                expires_at=record.expires_at,
                freshness=freshness,
                age_days=age_days,
            )
        )

    for grade in _GRADE_KEYS:
        counts.setdefault(grade, 0)

    return EvidenceSection(
        items=tuple(items),
        missing_factor_keys=tuple(missing_factor_keys),
        counts_by_grade={grade: int(counts.get(grade, 0)) for grade in _GRADE_KEYS},
    )


def _parse_created_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _as_utc(value)
    if isinstance(value, str) and value:
        text = value.replace("Z", "+00:00")
        return _as_utc(datetime.fromisoformat(text))
    return datetime.min.replace(tzinfo=UTC)


def _linked_interactions(
    *,
    assessment: OpportunityAssessment | None,
    interactions: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    if assessment is None or not assessment.assessment_id:
        return []
    assessment_id = assessment.assessment_id
    return [
        item
        for item in interactions
        if str(item.get("opportunity_assessment_id") or "") == assessment_id
    ]


def _interaction_sort_key(item: Mapping[str, Any]) -> tuple[datetime, str]:
    return (_parse_created_at(item.get("created_at")), str(item.get("id") or ""))


def _project_validation_current(item: Mapping[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for field in _VALIDATION_SAFE_FIELDS:
        if field in item:
            projected[field] = item.get(field)
        elif field in _OUTCOME_FIELDS:
            projected[field] = None
    # Always expose the outcome field names even if absent on the source mapping.
    for field in _OUTCOME_FIELDS:
        projected.setdefault(field, None)
    return projected


def _select_current_validation(
    linked_interactions: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if not linked_interactions:
        return None
    open_items = [
        item for item in linked_interactions if str(item.get("status") or "") in _OPEN_STATUSES
    ]
    pool = open_items or [
        item
        for item in linked_interactions
        if str(item.get("status") or "") in _TERMINAL_STATUSES
    ]
    if not pool:
        pool = list(linked_interactions)
    selected = max(pool, key=_interaction_sort_key)
    return _project_validation_current(selected)


def _history_summary(
    linked_interactions: Sequence[Mapping[str, Any]],
) -> ValidationHistorySummary:
    by_status = {status: 0 for status in ALLOWED_TRANSITIONS}
    for item in linked_interactions:
        status = str(item.get("status") or "")
        if status in by_status:
            by_status[status] += 1
        else:
            by_status[status] = by_status.get(status, 0) + 1
    return ValidationHistorySummary(total=len(linked_interactions), by_status=by_status)
