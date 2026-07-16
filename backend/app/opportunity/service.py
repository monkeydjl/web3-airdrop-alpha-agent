from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any

from app.opportunity.decision import decide
from app.opportunity.economics import calculate_economics
from app.opportunity.evidence import (
    SOURCE_GRADE_WEIGHT,
    build_inputs,
    resolve_factor,
    usable,
)
from app.opportunity.models import (
    ConfidenceSet,
    EvidenceRecord,
    OpportunityAssessment,
    OpportunityInputs,
)
from app.opportunity.probability import derive_probability_inputs, joint_probability
from app.opportunity.profile import DEFAULT_PROFILE, MODEL_VERSION
from app.opportunity.quality import calculate_domain_confidence, with_overall_confidence
from app.opportunity.repository import OpportunityRepository
from app.repository import ProjectRepository

_CONFIDENCE_FACTORS = {
    "event": {
        "event_probability",
        "official_airdrop_statement",
        "distribution_catalyst_3_6m",
    },
    "eligibility": {
        "eligibility_probability",
        "participation_open",
        "task_path_known",
        "eligibility_mechanism",
        "hard_cost_usd",
        "capital_at_risk_usd",
    },
    "reward": {
        "conditional_reward_usd",
        "official_airdrop_statement",
    },
    "cost": {
        "hard_cost_usd",
        "expected_capital_loss_usd",
        "liquidity_cost_usd",
        "total_time_hours",
        "weekly_maintenance_hours",
    },
    "risk": {
        "capital_security_risk",
        "project_failure_risk",
        "safety_blocked",
        "integrity_blocked",
        "authorization_exit_known",
    },
    "quality": {
        "project_quality",
        "official_identity",
        "project_active",
    },
}

_DIRECT_ECONOMICS_FACTORS = {
    "conditional_reward_usd",
    "hard_cost_usd",
    "capital_at_risk_usd",
    "expected_capital_loss_usd",
    "liquidity_cost_usd",
    "total_time_hours",
}


class OpportunityService:
    def __init__(
        self,
        *,
        project_repo: ProjectRepository | None = None,
        opportunity_repo: OpportunityRepository | None = None,
        profile=DEFAULT_PROFILE,
        now_factory: Callable[[], datetime] | None = None,
    ):
        self.project_repo = project_repo if project_repo is not None else ProjectRepository()
        self.opportunity_repo = opportunity_repo if opportunity_repo is not None else OpportunityRepository()
        self.profile = profile
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self._owns_opportunity_repo = opportunity_repo is None

    def evaluate(self, project_id: str, *, persist: bool = True) -> OpportunityAssessment:
        row = self.project_repo.get_by_id(project_id)
        if row is None:
            raise LookupError(project_id)
        return self.evaluate_row(row, persist=persist)

    def evaluate_row(self, row: Mapping[str, Any], *, persist: bool = True) -> OpportunityAssessment:
        now = self._now_factory()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now_factory must return a timezone-aware datetime")

        project_id = str(row["id"])
        evidence = self.opportunity_repo.list_evidence(project_id)
        inputs = build_inputs(row, evidence, self.profile, now=now)
        confidence = _build_confidence(inputs, evidence, now)
        inputs = inputs.model_copy(update={"confidence": confidence})

        event, eligibility, survival = derive_probability_inputs(inputs, evidence, self.profile, now=now)
        reward_probability = None
        if event is not None and eligibility is not None and survival is not None:
            reward_probability = joint_probability(event, eligibility, survival)

        missing_economics = {
            name
            for name, value in {
                "reward_probability": reward_probability,
                "conditional_reward_usd": inputs.conditional_reward_usd,
                "hard_cost_usd": inputs.hard_cost_usd,
                "capital_at_risk_usd": inputs.capital_at_risk_usd,
                "expected_capital_loss_usd": inputs.expected_capital_loss_usd,
                "liquidity_cost_usd": inputs.liquidity_cost_usd,
                "total_time_hours": inputs.total_time_hours,
            }.items()
            if value is None
        }
        if missing_economics:
            inputs = inputs.model_copy(
                update={"critical_unknowns": tuple(sorted(set(inputs.critical_unknowns) | missing_economics))}
            )
        if not _has_direct_economics_evidence(inputs, evidence, now):
            inputs = inputs.model_copy(
                update={
                    "critical_unknowns": tuple(sorted(set(inputs.critical_unknowns) | {"economics_direct_evidence"}))
                }
            )

        economics = None
        if not missing_economics:
            assert reward_probability is not None
            assert inputs.conditional_reward_usd is not None
            assert inputs.hard_cost_usd is not None
            assert inputs.capital_at_risk_usd is not None
            assert inputs.expected_capital_loss_usd is not None
            assert inputs.liquidity_cost_usd is not None
            assert inputs.total_time_hours is not None
            economics = calculate_economics(
                reward_probability=reward_probability,
                conditional_reward=inputs.conditional_reward_usd,
                hard_cost=inputs.hard_cost_usd,
                capital_loss=inputs.expected_capital_loss_usd,
                liquidity_cost=inputs.liquidity_cost_usd,
                total_time_hours=inputs.total_time_hours,
                capital_at_risk_base=inputs.capital_at_risk_usd.base,
            )

        decision = decide(
            inputs=inputs,
            event=event,
            eligibility=eligibility,
            survival=survival,
            reward_probability=reward_probability,
            economics=economics,
            profile=self.profile,
            now=now,
        )
        assessment = OpportunityAssessment(
            project_id=project_id,
            model_version=MODEL_VERSION,
            profile_version=self.profile.profile_id,
            event_probability=event,
            eligibility_probability=eligibility,
            survival_probability=survival,
            reward_probability=reward_probability,
            conditional_reward_usd=inputs.conditional_reward_usd,
            hard_cost_usd=inputs.hard_cost_usd,
            capital_at_risk_usd=inputs.capital_at_risk_usd,
            expected_capital_loss_usd=inputs.expected_capital_loss_usd,
            liquidity_cost_usd=inputs.liquidity_cost_usd,
            total_time_hours=inputs.total_time_hours,
            weekly_maintenance_hours=inputs.weekly_maintenance_hours,
            economics=economics,
            project_quality=inputs.project_quality,
            risks=inputs.risks,
            confidence=confidence,
            status=decision.status,
            public_label=decision.public_label,
            blocker_codes=decision.blocker_codes,
            watch_reason_codes=decision.watch_reason_codes,
            ignore_reason_codes=decision.ignore_reason_codes,
            requires_remediation=decision.requires_remediation,
            recommended_action=decision.recommended_action,
            evidence_ids=tuple(sorted(set(inputs.evidence_ids))),
            factor_snapshot=_factor_snapshot(
                inputs=inputs,
                event=event,
                eligibility=eligibility,
                survival=survival,
                confidence=confidence,
            ),
            scored_at=now,
            review_at=decision.review_at,
            expires_at=decision.expires_at,
        )
        if persist:
            return self.opportunity_repo.save_assessment(assessment)
        return assessment

    def close(self) -> None:
        if self._owns_opportunity_repo:
            self.opportunity_repo.close()

    def __enter__(self) -> "OpportunityService":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def _build_confidence(
    inputs: OpportunityInputs,
    evidence: list[EvidenceRecord],
    now: datetime,
) -> ConfidenceSet:
    accepted_ids = set(inputs.evidence_ids)
    current = [
        record
        for record in evidence
        if record.project_id == inputs.project_id
        and record.evidence_id in accepted_ids
        and record.verification_status == "verified"
        and record.observation_type in {"observed", "derived"}
        and usable(record, now)
    ]
    domain_scores = {}
    for domain, factor_keys in _CONFIDENCE_FACTORS.items():
        resolutions = [
            resolution
            for factor_key in factor_keys
            if (resolution := resolve_factor(current, factor_key, now)).record is not None
        ]
        resolved = [resolution.record for resolution in resolutions]
        if not resolved:
            domain_scores[domain] = 0.0
            continue
        source_reliability = sum(SOURCE_GRADE_WEIGHT[record.source_grade] for record in resolved) / len(resolved)
        evidence_coverage = len(resolved) / len(factor_keys)
        source_independence = len({record.independence_group for record in resolved}) / len(resolved)
        freshness_consistency = sum(
            _freshness_score(resolution.record, now) * resolution.consistency for resolution in resolutions
        ) / len(resolutions)
        domain_scores[domain] = calculate_domain_confidence(
            source_reliability=source_reliability,
            evidence_coverage=evidence_coverage,
            source_independence=source_independence,
            freshness_consistency=freshness_consistency,
        )
    return with_overall_confidence(ConfidenceSet(**domain_scores))


def _has_direct_economics_evidence(
    inputs: OpportunityInputs,
    evidence: list[EvidenceRecord],
    now: datetime,
) -> bool:
    accepted_ids = set(inputs.evidence_ids)
    direct = [
        record
        for record in evidence
        if record.project_id == inputs.project_id
        and record.evidence_id in accepted_ids
        and record.verification_status == "verified"
        and record.observation_type in {"observed", "derived"}
        and usable(record, now)
    ]
    return all(resolve_factor(direct, factor_key, now).record is not None for factor_key in _DIRECT_ECONOMICS_FACTORS)


def _factor_snapshot(
    *,
    inputs: OpportunityInputs,
    event,
    eligibility,
    survival,
    confidence: ConfidenceSet,
) -> dict[str, Any]:
    return {
        "event_probability": _json_value(event),
        "eligibility_probability": _json_value(eligibility),
        "survival_probability": _json_value(survival),
        "conditional_reward_usd": _json_value(inputs.conditional_reward_usd),
        "hard_cost_usd": _json_value(inputs.hard_cost_usd),
        "capital_at_risk_usd": _json_value(inputs.capital_at_risk_usd),
        "expected_capital_loss_usd": _json_value(inputs.expected_capital_loss_usd),
        "liquidity_cost_usd": _json_value(inputs.liquidity_cost_usd),
        "total_time_hours": _json_value(inputs.total_time_hours),
        "weekly_maintenance_hours": inputs.weekly_maintenance_hours,
        "project_quality": inputs.project_quality,
        "risks": inputs.risks.model_dump(mode="json"),
        "confidence": confidence.model_dump(mode="json"),
        "critical_unknowns": inputs.critical_unknowns,
        "official_airdrop_evidence_count_a": inputs.official_airdrop_evidence_count_a,
        "independent_airdrop_evidence_count_b": inputs.independent_airdrop_evidence_count_b,
    }


def _json_value(value):
    return value.model_dump(mode="json") if value is not None else None


def _freshness_score(record: EvidenceRecord, now: datetime) -> float:
    observed_at = record.observed_at
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    age = now.astimezone(UTC) - observed_at.astimezone(UTC)
    if age <= timedelta(days=7):
        return 1.0
    if age <= timedelta(days=30):
        return 0.8
    if age <= timedelta(days=90):
        return 0.5
    return 0.2
