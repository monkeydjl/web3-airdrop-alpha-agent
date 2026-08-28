import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from math import isfinite
from typing import Any, Literal, NamedTuple, cast

from app.opportunity.models import (
    ConfidenceSet,
    EvidenceRecord,
    MoneyRange,
    OpportunityInputs,
    OpportunityProfile,
    ProbabilityRange,
    RiskLevel,
    RiskSet,
)

SOURCE_GRADE_WEIGHT = {"A": 1.0, "B": 0.8, "C": 0.5, "D": 0.2, "U": 0.0}

SUPPORTED_FACTOR_KEYS = {
    "official_identity",
    "participation_open",
    "task_path_known",
    "authorization_exit_known",
    "official_airdrop_statement",
    "official_points_future_value",
    "community_allocation",
    "distribution_catalyst_3_6m",
    "project_active",
    "opportunity_timing",
    "profile_fit",
    "multiwallet_policy",
    "eligibility_mechanism",
    "hard_cost_usd",
    "weekly_maintenance_hours",
    "total_time_hours",
    "conditional_reward_usd",
    "capital_at_risk_usd",
    "expected_capital_loss_usd",
    "liquidity_cost_usd",
    "project_quality",
    "project_failure_risk",
    "capital_security_risk",
    "eligibility_risk",
    "reward_dilution_risk",
    "liquidity_risk",
    "integrity_blocked",
    "safety_blocked",
    "event_probability",
    "eligibility_probability",
    "survival_probability",
}


class FactorSchema(NamedTuple):
    value_type: str
    normalize: Callable[[EvidenceRecord], Any]


class FactorResolution(NamedTuple):
    record: EvidenceRecord | None
    value: Any | None
    conflicted: bool
    consistency: float


CRITICAL_KEYS = {
    "official_identity",
    "participation_open",
    "task_path_known",
    "authorization_exit_known",
    "distribution_catalyst_3_6m",
    "project_active",
    "opportunity_timing",
    "profile_fit",
    "integrity_blocked",
    "safety_blocked",
    "airdrop_basis",
    "multiwallet_policy",
    "hard_cost",
    "weekly_maintenance",
    "capital_security",
    "eligibility_risk",
    "project_failure_risk",
    "reward_dilution_risk",
    "liquidity_risk",
    "conditional_reward",
    "capital_at_risk",
}

_AIRDROP_BASIS_KEYS = {
    "official_airdrop_statement",
    "official_points_future_value",
    "community_allocation",
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def usable(record: EvidenceRecord, now: datetime) -> bool:
    if record.verification_status not in {"verified", "partially_verified"}:
        return False
    current_time = _as_utc(now)
    if _as_utc(record.observed_at) > current_time:
        return False
    if record.effective_at is not None and _as_utc(record.effective_at) > current_time:
        return False
    return record.expires_at is None or current_time < _as_utc(record.expires_at)


def independent_count(records: list[EvidenceRecord], minimum_grade: str) -> int:
    floor = SOURCE_GRADE_WEIGHT[minimum_grade]
    return len(
        {
            record.independence_group
            for record in records
            if isinstance(record.evidence_id, str)
            and bool(record.evidence_id.strip())
            and SOURCE_GRADE_WEIGHT[record.source_grade] >= floor
            and record.verification_status in {"verified", "partially_verified"}
        }
    )


def _legacy_signals(project_row: Mapping[str, Any]) -> Mapping[str, Any]:
    meta = project_row.get("meta")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (TypeError, ValueError):
            return {}
    if not isinstance(meta, Mapping):
        return {}
    signals = meta.get("signals")
    return signals if isinstance(signals, Mapping) else {}


def _range_value(
    record: EvidenceRecord, model: type[ProbabilityRange] | type[MoneyRange]
) -> ProbabilityRange | MoneyRange:
    value = record.value
    if not isinstance(value, Mapping):
        raise TypeError(f"{record.factor_key} must be a range object")
    if set(value) != {"low", "base", "high"}:
        raise ValueError(f"{record.factor_key} requires exactly low, base, and high")
    if any(
        isinstance(member, bool) or not isinstance(member, (int, float)) or not isfinite(member)
        for member in value.values()
    ):
        raise TypeError(f"{record.factor_key} range members must be finite numbers")
    return model.model_validate(dict(value))


def _number_value(record: EvidenceRecord) -> float:
    if isinstance(record.value, bool) or not isinstance(record.value, (int, float)):
        raise TypeError(f"{record.factor_key} must be numeric")
    return float(record.value)


def _bool_value(record: EvidenceRecord) -> bool:
    if not isinstance(record.value, bool):
        raise TypeError(f"{record.factor_key} must be boolean")
    return record.value


def _enum_value(record: EvidenceRecord, allowed: set[str]) -> str:
    if not isinstance(record.value, str) or record.value not in allowed:
        raise ValueError(f"{record.factor_key} has an unsupported value")
    return record.value


def _quality_value(record: EvidenceRecord) -> float:
    value = _number_value(record)
    if not 0 <= value <= 100:
        raise ValueError("project_quality must be between 0 and 100")
    return value


def _non_negative_number(record: EvidenceRecord) -> float:
    value = _number_value(record)
    if value < 0:
        raise ValueError(f"{record.factor_key} must be non-negative")
    return value


def _probability_range(record: EvidenceRecord) -> ProbabilityRange:
    return cast(ProbabilityRange, _range_value(record, ProbabilityRange))


def _money_range(record: EvidenceRecord) -> MoneyRange:
    return cast(MoneyRange, _range_value(record, MoneyRange))


def _policy_value(record: EvidenceRecord) -> str:
    return _enum_value(record, {"allowed", "not_forbidden", "forbidden", "unknown"})


def _eligibility_value(record: EvidenceRecord) -> str:
    return _enum_value(
        record,
        {"deterministic", "points_based", "behavioral", "opaque"},
    )


def _risk_value(record: EvidenceRecord) -> RiskLevel:
    return RiskLevel(_enum_value(record, {level.value for level in RiskLevel}))


def _timing_value(record: EvidenceRecord) -> str:
    return _enum_value(record, {"open", "late", "closed", "unknown"})


def _profile_fit_value(record: EvidenceRecord) -> str:
    return _enum_value(
        record,
        {"fit", "single_wallet_only", "mismatch", "unknown"},
    )


FACTOR_SCHEMAS = {
    "official_identity": FactorSchema("bool", _bool_value),
    "participation_open": FactorSchema("bool", _bool_value),
    "task_path_known": FactorSchema("bool", _bool_value),
    "authorization_exit_known": FactorSchema("bool", _bool_value),
    "official_airdrop_statement": FactorSchema("bool", _bool_value),
    "official_points_future_value": FactorSchema("bool", _bool_value),
    "community_allocation": FactorSchema("bool", _bool_value),
    "distribution_catalyst_3_6m": FactorSchema("bool", _bool_value),
    "project_active": FactorSchema("bool", _bool_value),
    "opportunity_timing": FactorSchema("string", _timing_value),
    "profile_fit": FactorSchema("string", _profile_fit_value),
    "multiwallet_policy": FactorSchema("string", _policy_value),
    "eligibility_mechanism": FactorSchema("string", _eligibility_value),
    "hard_cost_usd": FactorSchema("range", _money_range),
    "weekly_maintenance_hours": FactorSchema("number", _non_negative_number),
    "total_time_hours": FactorSchema("range", _money_range),
    "conditional_reward_usd": FactorSchema("range", _money_range),
    "capital_at_risk_usd": FactorSchema("range", _money_range),
    "expected_capital_loss_usd": FactorSchema("range", _money_range),
    "liquidity_cost_usd": FactorSchema("range", _money_range),
    "project_quality": FactorSchema("number", _quality_value),
    "project_failure_risk": FactorSchema("string", _risk_value),
    "capital_security_risk": FactorSchema("string", _risk_value),
    "eligibility_risk": FactorSchema("string", _risk_value),
    "reward_dilution_risk": FactorSchema("string", _risk_value),
    "liquidity_risk": FactorSchema("string", _risk_value),
    "integrity_blocked": FactorSchema("bool", _bool_value),
    "safety_blocked": FactorSchema("bool", _bool_value),
    "event_probability": FactorSchema("range", _probability_range),
    "eligibility_probability": FactorSchema("range", _probability_range),
    "survival_probability": FactorSchema("range", _probability_range),
}


def _normalized_record(record: EvidenceRecord) -> tuple[EvidenceRecord, Any] | None:
    if not isinstance(record.evidence_id, str) or not record.evidence_id.strip():
        return None
    schema = FACTOR_SCHEMAS.get(record.factor_key)
    if schema is None or record.value_type != schema.value_type:
        return None
    if record.factor_key in {
        "participation_open",
        "task_path_known",
        "authorization_exit_known",
        "distribution_catalyst_3_6m",
        "project_active",
        "opportunity_timing",
        "profile_fit",
        "safety_blocked",
        "integrity_blocked",
    } and record.observation_type not in {"observed", "derived"}:
        return None
    try:
        return record, schema.normalize(record)
    except (OverflowError, TypeError, ValueError):
        return None


def resolve_factor(
    records: list[EvidenceRecord],
    factor_key: str,
    now: datetime | None = None,
) -> FactorResolution:
    current_time = now or datetime.now(UTC)
    candidates: list[tuple[EvidenceRecord, Any]] = []
    for record in records:
        if (
            record.factor_key != factor_key
            or record.verification_status != "verified"
            or not usable(record, current_time)
        ):
            continue
        normalized = _normalized_record(record)
        if normalized is not None:
            candidates.append(normalized)

    if not candidates:
        return FactorResolution(None, None, False, 0.0)

    values = {repr(value) for _, value in candidates}
    if len(values) == 1:
        record, value = min(
            candidates,
            key=lambda item: (
                -SOURCE_GRADE_WEIGHT[item[0].source_grade],
                -_as_utc(item[0].observed_at).timestamp(),
                item[0].evidence_id or "",
            ),
        )
        return FactorResolution(record, value, False, 1.0)

    best_grade = max(SOURCE_GRADE_WEIGHT[record.source_grade] for record, _ in candidates)
    top_grade = [item for item in candidates if SOURCE_GRADE_WEIGHT[item[0].source_grade] == best_grade]
    if len({repr(value) for _, value in top_grade}) != 1:
        return FactorResolution(None, None, True, 0.0)

    selected = min(
        top_grade,
        key=lambda item: (
            -_as_utc(item[0].observed_at).timestamp(),
            item[0].evidence_id or "",
        ),
    )
    selected_value = selected[1]
    contradictions = [item for item in candidates if item[1] != selected_value]
    if any(
        SOURCE_GRADE_WEIGHT[record.source_grade] >= best_grade
        or _as_utc(record.observed_at) >= _as_utc(selected[0].observed_at)
        for record, _ in contradictions
    ):
        return FactorResolution(None, None, True, 0.0)
    return FactorResolution(
        selected[0],
        selected_value,
        False,
        0.5 if contradictions else 1.0,
    )


def _resolve_blocker(
    records: list[EvidenceRecord],
    factor_key: str,
    now: datetime,
) -> FactorResolution:
    candidates = []
    records = _without_validly_superseded_blockers(records, now)
    for record in records:
        if record.factor_key != factor_key or record.verification_status != "verified" or not usable(record, now):
            continue
        normalized = _normalized_record(record)
        if normalized is not None:
            candidates.append(normalized)
    true_candidates = [item for item in candidates if item[1] is True]
    selected_candidates = true_candidates or candidates
    if not selected_candidates:
        return FactorResolution(None, None, False, 0.0)
    record, value = min(
        selected_candidates,
        key=lambda item: (
            -SOURCE_GRADE_WEIGHT[item[0].source_grade],
            -_as_utc(item[0].observed_at).timestamp(),
            item[0].evidence_id or "",
        ),
    )
    return FactorResolution(record, value, False, 1.0)


def _without_validly_superseded_blockers(records: list[EvidenceRecord], now: datetime) -> list[EvidenceRecord]:
    by_id = {
        record.evidence_id: record for record in records if isinstance(record.evidence_id, str) and record.evidence_id
    }
    edges: dict[str, str] = {}
    for record in records:
        target_id = record.supersedes_evidence_id
        if target_id is None:
            continue
        target = by_id.get(target_id)
        if (
            target is not None
            and record.factor_key in {"integrity_blocked", "safety_blocked"}
            and target.factor_key == record.factor_key
            and target.project_id == record.project_id
            and _as_utc(target.observed_at) <= _as_utc(record.observed_at)
            and record.evidence_id is not None
        ):
            edges[record.evidence_id] = target_id

    cyclic: set[str] = set()
    for start in edges:
        path: list[str] = []
        current = start
        while current in edges and current not in path:
            path.append(current)
            current = edges[current]
        if current in path:
            cyclic.update(path[path.index(current) :])

    valid_edges = {
        source_id: target_id
        for source_id, target_id in edges.items()
        if source_id not in cyclic and target_id not in cyclic
    }
    superseded = set(valid_edges.values())
    tips = [record for record in records if record.evidence_id not in superseded and record.evidence_id not in cyclic]
    active: list[EvidenceRecord] = []
    active.extend(
        record
        for record in records
        if record.evidence_id in cyclic
        and (normalized := _normalized_record(record)) is not None
        and normalized[1] is True
    )
    for tip in tips:
        normalized = _normalized_record(tip)
        if normalized is None or normalized[1] is not False:
            active.append(tip)
            continue
        strong_clear = (
            tip.verification_status == "verified"
            and tip.source_grade == "A"
            and tip.observation_type in {"observed", "derived"}
            and usable(tip, now)
        )
        if strong_clear or tip.evidence_id not in valid_edges:
            active.append(tip)
            continue
        ancestor_id = valid_edges[tip.evidence_id]
        while ancestor_id in valid_edges:
            ancestor = by_id[ancestor_id]
            ancestor_value = _normalized_record(ancestor)
            if ancestor_value is not None and ancestor_value[1] is True:
                active.append(ancestor)
                break
            ancestor_id = valid_edges[ancestor_id]
        else:
            final_ancestor = by_id.get(ancestor_id)
            ancestor_value = _normalized_record(final_ancestor) if final_ancestor is not None else None
            if final_ancestor is not None and ancestor_value is not None and ancestor_value[1] is True:
                active.append(final_ancestor)
    return active


def _current_airdrop_support(
    records: list[tuple[EvidenceRecord, Any]],
    conflicted_factors: set[str],
) -> list[EvidenceRecord]:
    by_source: dict[tuple[str, str], list[tuple[EvidenceRecord, Any]]] = {}
    for record, value in records:
        if record.factor_key in _AIRDROP_BASIS_KEYS and record.factor_key not in conflicted_factors:
            by_source.setdefault((record.factor_key, record.independence_group), []).append((record, value))

    support = []
    for candidates in by_source.values():
        latest_at = max(_as_utc(record.observed_at) for record, _ in candidates)
        tied = [item for item in candidates if _as_utc(item[0].observed_at) == latest_at]
        if all(value is True for _, value in tied):
            support.append(min(tied, key=lambda item: item[0].evidence_id or "")[0])
    return support


def build_inputs(
    project_row: Mapping[str, Any],
    evidence: list[EvidenceRecord],
    profile: OpportunityProfile,
    now: datetime | None = None,
) -> OpportunityInputs:
    del profile
    _legacy_signals(project_row)
    project_id = str(project_row["id"])
    current_time = now or datetime.now(UTC)
    supporting = []
    for record in evidence:
        if record.project_id != project_id:
            continue
        normalized_record = _normalized_record(record)
        if (
            normalized_record is not None
            and record.verification_status in {"verified", "partially_verified"}
            and usable(record, current_time)
        ):
            supporting.append(normalized_record)
    supporting_records = [record for record, _ in supporting]
    resolutions = {
        factor_key: resolve_factor(supporting_records, factor_key, current_time) for factor_key in SUPPORTED_FACTOR_KEYS
    }
    for blocker_key in ("integrity_blocked", "safety_blocked"):
        resolutions[blocker_key] = _resolve_blocker(
            supporting_records,
            blocker_key,
            current_time,
        )
    latest = {
        factor_key: (resolution.record, resolution.value)
        for factor_key, resolution in resolutions.items()
        if resolution.record is not None
    }
    conflicted_factors = {factor_key for factor_key, resolution in resolutions.items() if resolution.conflicted}
    normalized = {factor_key: value for factor_key, (_, value) in latest.items()}

    multiwallet_policy: Literal["allowed", "not_forbidden", "forbidden", "unknown"] = "unknown"
    if "multiwallet_policy" in normalized:
        multiwallet_policy = cast(
            Literal["allowed", "not_forbidden", "forbidden", "unknown"], normalized["multiwallet_policy"]
        )

    project_failure_risk = None
    if "project_failure_risk" in normalized:
        project_failure_risk = normalized["project_failure_risk"]
    capital_security_risk = None
    if "capital_security_risk" in normalized:
        capital_security_risk = normalized["capital_security_risk"]
    eligibility_risk = normalized.get("eligibility_risk")
    reward_dilution_risk = normalized.get("reward_dilution_risk")
    liquidity_risk = normalized.get("liquidity_risk")

    integrity_blocked = normalized.get("integrity_blocked")
    safety_blocked = normalized.get("safety_blocked")
    if normalized.get("official_identity") is False:
        safety_blocked = True

    unknowns = set(CRITICAL_KEYS)
    if "official_identity" in latest:
        unknowns.discard("official_identity")
    if "participation_open" in latest:
        unknowns.discard("participation_open")
    if "task_path_known" in latest:
        unknowns.discard("task_path_known")
    if "authorization_exit_known" in latest:
        unknowns.discard("authorization_exit_known")
    if "distribution_catalyst_3_6m" in latest:
        unknowns.discard("distribution_catalyst_3_6m")
    if "project_active" in latest:
        unknowns.discard("project_active")
    if "opportunity_timing" in latest:
        unknowns.discard("opportunity_timing")
    if "profile_fit" in latest:
        unknowns.discard("profile_fit")
    if "integrity_blocked" in latest:
        unknowns.discard("integrity_blocked")
    if "safety_blocked" in latest:
        unknowns.discard("safety_blocked")
    if "multiwallet_policy" in latest:
        unknowns.discard("multiwallet_policy")
    if "hard_cost_usd" in latest:
        unknowns.discard("hard_cost")
    if "weekly_maintenance_hours" in latest:
        unknowns.discard("weekly_maintenance")
    if "capital_security_risk" in latest:
        unknowns.discard("capital_security")
    if "eligibility_risk" in latest:
        unknowns.discard("eligibility_risk")
    if "project_failure_risk" in latest:
        unknowns.discard("project_failure_risk")
    if "reward_dilution_risk" in latest:
        unknowns.discard("reward_dilution_risk")
    if "liquidity_risk" in latest:
        unknowns.discard("liquidity_risk")
    if "conditional_reward_usd" in latest:
        unknowns.discard("conditional_reward")
    if "capital_at_risk_usd" in latest:
        unknowns.discard("capital_at_risk")

    airdrop_records = _current_airdrop_support(supporting, conflicted_factors)
    if airdrop_records:
        unknowns.discard("airdrop_basis")
    confidence = ConfidenceSet(event=0, eligibility=0, reward=0, cost=0, risk=0, quality=0, overall=0)
    risks = RiskSet(
        capital_security=capital_security_risk,
        eligibility=eligibility_risk,
        project_failure=project_failure_risk,
        reward_dilution=reward_dilution_risk,
        liquidity=liquidity_risk,
    )

    return OpportunityInputs(
        project_id=project_id,
        event_probability=normalized.get("event_probability"),
        eligibility_probability=normalized.get("eligibility_probability"),
        survival_probability=normalized.get("survival_probability"),
        conditional_reward_usd=normalized.get("conditional_reward_usd"),
        hard_cost_usd=normalized.get("hard_cost_usd"),
        capital_at_risk_usd=normalized.get("capital_at_risk_usd"),
        expected_capital_loss_usd=normalized.get("expected_capital_loss_usd"),
        liquidity_cost_usd=normalized.get("liquidity_cost_usd"),
        total_time_hours=normalized.get("total_time_hours"),
        weekly_maintenance_hours=normalized.get("weekly_maintenance_hours"),
        participation_open=normalized.get("participation_open"),
        task_path_known=normalized.get("task_path_known"),
        authorization_exit_known=normalized.get("authorization_exit_known"),
        distribution_catalyst_3_6m=normalized.get("distribution_catalyst_3_6m"),
        project_active=normalized.get("project_active"),
        opportunity_timing=cast(
            Literal["open", "late", "closed", "unknown"], normalized.get("opportunity_timing", "unknown")
        ),
        profile_fit=cast(
            Literal["fit", "single_wallet_only", "mismatch", "unknown"], normalized.get("profile_fit", "unknown")
        ),
        weekly_time_confirmed_minimum=(
            "weekly_maintenance_hours" in latest
            and latest["weekly_maintenance_hours"][0].observation_type in {"observed", "derived"}
            and SOURCE_GRADE_WEIGHT[latest["weekly_maintenance_hours"][0].source_grade] >= SOURCE_GRADE_WEIGHT["B"]
        ),
        # 与上面的时间门槛同一把尺子：成本必须是 observed/derived 且来源 >= B 才算"确知"。
        # `_derive_eligibility` 对 hard_cost_usd 也要求 >= B，这里保持一致。
        hard_cost_confirmed_minimum=(
            "hard_cost_usd" in latest
            and latest["hard_cost_usd"][0].observation_type in {"observed", "derived"}
            and SOURCE_GRADE_WEIGHT[latest["hard_cost_usd"][0].source_grade] >= SOURCE_GRADE_WEIGHT["B"]
        ),
        project_quality=normalized.get("project_quality"),
        project_failure_risk=project_failure_risk,
        capital_security_risk=capital_security_risk,
        official_multiwallet_policy=multiwallet_policy,
        official_airdrop_evidence_count_a=independent_count(airdrop_records, "A"),
        independent_airdrop_evidence_count_b=independent_count(airdrop_records, "B"),
        confidence=confidence,
        risks=risks,
        critical_unknowns=tuple(sorted(unknowns)),
        integrity_blocked=integrity_blocked,
        safety_blocked=safety_blocked,
        evidence_ids=tuple(sorted({record.evidence_id for record, _ in supporting if record.evidence_id is not None})),
    )
