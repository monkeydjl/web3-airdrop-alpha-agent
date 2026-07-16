import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.opportunity.models import (
    ConfidenceSet,
    DecisionResult,
    DecisionStatus,
    EconomicsResult,
    EvidenceRecord,
    MoneyRange,
    OpportunityAssessment,
    OpportunityInputs,
    OpportunityProfile,
    ProbabilityRange,
    QualityFactors,
    RiskLevel,
    RiskSet,
    SignedMoneyRange,
)
from app.opportunity.profile import DEFAULT_PROFILE, MODEL_VERSION

NOW = datetime(2026, 7, 14, tzinfo=UTC)


def confidence_data(**overrides):
    data = {
        "event": 0.8,
        "eligibility": 0.7,
        "reward": 0.6,
        "cost": 0.9,
        "risk": 0.75,
        "quality": 0.65,
    }
    data.update(overrides)
    return data


def risk_data(**overrides):
    data = {
        "capital_security": "low",
        "eligibility": "medium",
        "project_failure": "medium",
        "reward_dilution": "high",
        "liquidity": "low",
    }
    data.update(overrides)
    return data


def evidence_data(**overrides):
    data = {
        "factor_key": "official_airdrop_statement",
        "value": {"confirmed": True, "channels": ["docs", "blog"]},
        "value_type": "json",
        "observation_type": "observed",
        "source_url": "https://example.com/airdrop",
        "source_type": "official_docs",
        "source_grade": "A",
        "observed_at": NOW,
        "independence_group": "project-official",
    }
    data.update(overrides)
    return data


def assessment_data(**overrides):
    data = {
        "project_id": "project-1",
        "model_version": "opportunity-v2.0",
        "profile_version": "low-cost-curated-multiwallet-v1",
        "risks": risk_data(),
        "confidence": confidence_data(),
        "status": "MONITOR",
        "public_label": "WATCH",
        "recommended_action": "Recheck official documentation.",
        "factor_snapshot": {
            "policy": {"status": "unknown"},
            "sources": ["docs", {"grade": "A"}],
        },
        "scored_at": NOW,
        "review_at": NOW,
        "expires_at": NOW,
    }
    data.update(overrides)
    return data


def economics_data(**overrides):
    data = {
        "gross_reward": {"low": 10, "base": 20, "high": 30},
        "net_reward": {"low": -5, "base": 10, "high": 25},
        "reward_to_cost_ratio": 2,
        "decision_value": 10,
        "capital_efficiency": 5,
        "time_efficiency": 4,
    }
    data.update(overrides)
    return data


SCALAR_FLOAT_MODEL_CASES = [
    (
        "probability-range",
        lambda value: ProbabilityRange(low=value, base=value, high=value),
    ),
    ("money-range", lambda value: MoneyRange(low=value, base=value, high=value)),
    (
        "signed-money-range",
        lambda value: SignedMoneyRange(low=value, base=value, high=value),
    ),
    (
        "confidence-set",
        lambda value: ConfidenceSet(**confidence_data(event=value)),
    ),
    (
        "economics-result",
        lambda value: EconomicsResult(**economics_data(decision_value=value)),
    ),
    (
        "opportunity-profile",
        lambda value: OpportunityProfile(
            **{
                **DEFAULT_PROFILE.model_dump(),
                "hard_cost_limit_per_wallet_usd": value,
            }
        ),
    ),
    (
        "opportunity-inputs",
        lambda value: OpportunityInputs(
            project_id="project-1",
            weekly_maintenance_hours=value,
            confidence=confidence_data(),
            risks=risk_data(),
        ),
    ),
    (
        "opportunity-assessment",
        lambda value: OpportunityAssessment(**assessment_data(weekly_maintenance_hours=value)),
    ),
]


def test_probability_range_orders_values():
    value = ProbabilityRange(low=0.2, base=0.4, high=0.7)
    assert value.low == 0.2
    with pytest.raises(ValidationError):
        ProbabilityRange(low=0.6, base=0.4, high=0.8)


@pytest.mark.parametrize(
    "non_finite",
    [float("nan"), float("inf"), float("-inf")],
    ids=["nan", "positive-infinity", "negative-infinity"],
)
@pytest.mark.parametrize(
    "model_name,build_model",
    SCALAR_FLOAT_MODEL_CASES,
    ids=[case[0] for case in SCALAR_FLOAT_MODEL_CASES],
)
def test_task_1_models_reject_non_finite_scalar_floats(model_name, build_model, non_finite):
    with pytest.raises(ValidationError, match="finite"):
        build_model(non_finite)


@pytest.mark.parametrize("field,value", [("low", -0.1), ("base", 1.1), ("high", 2)])
def test_probability_range_enforces_probability_bounds(field, value):
    data = {"low": 0.2, "base": 0.4, "high": 0.7, field: value}
    with pytest.raises(ValidationError):
        ProbabilityRange(**data)


def test_money_range_rejects_negative_rewards():
    with pytest.raises(ValidationError):
        MoneyRange(low=-1, base=20, high=30)


def test_money_range_requires_ordered_values():
    with pytest.raises(ValidationError):
        MoneyRange(low=10, base=5, high=20)


def test_signed_money_range_supports_negative_values():
    value = SignedMoneyRange(low=-20, base=-5, high=10)
    assert value.low == -20
    assert value.high == 10


def test_signed_money_range_requires_ordered_values():
    with pytest.raises(ValidationError):
        SignedMoneyRange(low=-5, base=-10, high=10)


def test_valid_evidence_record_constructs():
    record = EvidenceRecord(**evidence_data())
    assert record.source_grade == "A"
    assert record.independence_group == "project-official"
    assert record.supersedes_evidence_id is None


@pytest.mark.parametrize(
    "source_url",
    [
        "https://project.example/rules#section",
        "https://user@project.example/rules",
        "https://project.example/rules?access-token=value",
        "https://project.example/rules?refresh_token=value",
        "https://project.example/rules?API.KEY=value",
        "https://project.example/rules?authorization=value",
        "https://project.example/rules?jwt=value",
        "https://project.example/rules?session=value",
        "https://project.example/rules?credential=value",
        "https://project.example/rules?password=value",
        "https://project.example/rules?sig=value",
    ],
)
def test_evidence_model_rejects_unsafe_source_urls(source_url):
    with pytest.raises(ValidationError):
        EvidenceRecord(**evidence_data(source_url=source_url))


@pytest.mark.parametrize(
    "query_key",
    [
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "security_token",
        "session_token",
        "auth_token",
        "api_key",
        "x-api-key",
        "client_secret",
        "api_secret",
        "app_secret",
        "access_key",
        "access_key_id",
        "aws_access_key_id",
        "private_key",
        "credential",
        "credentials",
        "X-Amz-Credential",
        "signature",
        "X-Amz-Signature",
        "password",
        "passwd",
        "authorization",
        "auth",
        "jwt",
        "session",
        "session_id",
        "sig",
        "key",
        "secret",
    ],
)
def test_evidence_model_rejects_exact_normalized_credential_keys(query_key):
    with pytest.raises(ValidationError):
        EvidenceRecord(**evidence_data(source_url=f"https://project.example/rules?{query_key}=value"))


@pytest.mark.parametrize(
    "query_key",
    [
        "model_token_count",
        "token_count",
        "tokenization",
        "credential_type",
        "authorization_endpoint",
        "session_duration",
        "secretary",
        "monkey",
        "hockey",
        "market",
        "utm_source",
        "ref",
        "page",
    ],
)
def test_evidence_model_allows_benign_query_keys(query_key):
    record = EvidenceRecord(**evidence_data(source_url=f"https://project.example/rules?{query_key}=value"))

    assert str(record.source_url).startswith("https://project.example/rules?")


@pytest.mark.parametrize(
    "field",
    [
        "value_type",
        "observation_type",
        "source_url",
        "source_type",
        "source_grade",
        "observed_at",
        "independence_group",
    ],
)
def test_evidence_requires_each_provenance_field(field):
    data = evidence_data()
    del data[field]
    with pytest.raises(ValidationError):
        EvidenceRecord(**data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("value_type", "binary"),
        ("observation_type", "predicted"),
        ("source_grade", "E"),
        ("verification_status", "pending"),
        ("source_url", "not-a-url"),
        ("factor_key", ""),
        ("source_type", ""),
        ("independence_group", ""),
    ],
)
def test_evidence_enforces_bounds_and_literals(field, value):
    with pytest.raises(ValidationError):
        EvidenceRecord(**evidence_data(**{field: value}))


def test_evidence_value_is_deeply_immutable_and_detached_from_input():
    input_value = {"claims": [{"confirmed": True}]}
    record = EvidenceRecord(**evidence_data(value=input_value))

    input_value["claims"][0]["confirmed"] = False
    assert record.value["claims"][0]["confirmed"] is True
    with pytest.raises(TypeError):
        record.value["claims"][0]["confirmed"] = False
    with pytest.raises((AttributeError, TypeError)):
        record.value["claims"].append("new")


def test_evidence_json_serialization_preserves_object_and_list_shapes():
    record = EvidenceRecord(**evidence_data())

    dumped = record.model_dump(mode="json")["value"]
    encoded = json.loads(record.model_dump_json())["value"]

    assert dumped == {"confirmed": True, "channels": ["docs", "blog"]}
    assert encoded == dumped
    assert isinstance(dumped, dict)
    assert isinstance(dumped["channels"], list)


@pytest.mark.parametrize(
    "non_finite",
    [float("nan"), float("inf"), float("-inf")],
    ids=["nan", "positive-infinity", "negative-infinity"],
)
def test_evidence_rejects_nested_non_finite_json_numbers(non_finite):
    with pytest.raises(ValidationError, match="finite"):
        EvidenceRecord(**evidence_data(value={"nested": [{"number": non_finite}]}))


def test_default_profile_is_exact():
    assert MODEL_VERSION == "opportunity-v2.0"
    assert DEFAULT_PROFILE.profile_id == "low-cost-curated-multiwallet-v1"
    assert DEFAULT_PROFILE.wallet_count_min == 3
    assert DEFAULT_PROFILE.wallet_count_max == 10
    assert DEFAULT_PROFILE.hard_cost_limit_per_wallet_usd == 10
    assert DEFAULT_PROFILE.weekly_time_limit_hours == 2
    assert DEFAULT_PROFILE.horizon_months == (3, 6)
    assert DEFAULT_PROFILE.strategy == "compliant_curated_multiwallet"
    assert DEFAULT_PROFILE.loss_preference == "conservative"


@pytest.mark.parametrize(
    "overrides",
    [
        {"wallet_count_min": 0},
        {"wallet_count_min": 11, "wallet_count_max": 10},
        {"hard_cost_limit_per_wallet_usd": -1},
        {"weekly_time_limit_hours": 0},
        {"horizon_months": (1, 12)},
        {"strategy": "spray_and_pray"},
        {"loss_preference": "aggressive"},
    ],
)
def test_profile_rejects_invalid_limits_and_literals(overrides):
    data = DEFAULT_PROFILE.model_dump()
    data.update(overrides)
    with pytest.raises(ValidationError):
        OpportunityProfile(**data)


def test_all_enum_values_are_stable():
    assert [status.value for status in DecisionStatus] == [
        "ACTIONABLE",
        "MONITOR",
        "INSUFFICIENT_EVIDENCE",
        "NOT_FIT",
        "BLOCKED",
    ]
    assert [level.value for level in RiskLevel] == [
        "low",
        "medium",
        "high",
        "critical",
    ]


def test_confidence_quality_and_economics_bounds():
    with pytest.raises(ValidationError):
        ConfidenceSet(**confidence_data(event=1.1))
    with pytest.raises(ValidationError):
        QualityFactors(product_demand=101)
    with pytest.raises(ValidationError):
        EconomicsResult(
            gross_reward=MoneyRange(low=1, base=2, high=3),
            net_reward=SignedMoneyRange(low=-2, base=0, high=2),
            reward_to_cost_ratio=-0.1,
            decision_value=1,
            capital_efficiency=1,
            time_efficiency=1,
        )


def test_opportunity_inputs_constructs_with_explicit_contracts():
    inputs = OpportunityInputs(
        project_id="project-1",
        event_probability=ProbabilityRange(low=0.2, base=0.5, high=0.8),
        hard_cost_usd=MoneyRange(low=1, base=2, high=3),
        capital_at_risk_usd=MoneyRange(low=4, base=5, high=6),
        weekly_maintenance_hours=1.5,
        participation_open=True,
        task_path_known=True,
        authorization_exit_known=True,
        distribution_catalyst_3_6m=True,
        project_active=True,
        opportunity_timing="open",
        profile_fit="fit",
        weekly_time_confirmed_minimum=True,
        official_multiwallet_policy="allowed",
        confidence=ConfidenceSet(**confidence_data()),
        risks=RiskSet(**risk_data()),
        evidence_ids=("evidence-1",),
    )

    assert inputs.project_id == "project-1"
    assert inputs.event_probability.base == 0.5
    assert inputs.capital_at_risk_usd.base == 5
    assert inputs.opportunity_timing == "open"
    assert inputs.profile_fit == "fit"
    assert inputs.weekly_time_confirmed_minimum is True
    assert inputs.evidence_ids == ("evidence-1",)
    encoded = json.loads(inputs.model_dump_json())
    assert encoded["capital_at_risk_usd"] == {"low": 4.0, "base": 5.0, "high": 6.0}
    assert encoded["evidence_ids"] == ["evidence-1"]


def test_risk_set_preserves_unknowns_and_explicit_critical_values():
    unknown = RiskSet()
    explicit = RiskSet(capital_security=RiskLevel.CRITICAL)

    assert set(unknown.model_dump().values()) == {None}
    assert explicit.capital_security is RiskLevel.CRITICAL
    assert explicit.project_failure is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("weekly_maintenance_hours", -0.1),
        ("project_quality", 101),
        ("official_multiwallet_policy", "maybe"),
        ("official_airdrop_evidence_count_a", -1),
        ("project_failure_risk", "extreme"),
        ("opportunity_timing", "early"),
        ("profile_fit", "partial"),
    ],
)
def test_opportunity_inputs_enforces_bounds_and_literals(field, value):
    data = {
        "project_id": "project-1",
        "confidence": confidence_data(),
        "risks": risk_data(),
        field: value,
    }
    with pytest.raises(ValidationError):
        OpportunityInputs(**data)


def test_tuple_defaults_are_empty_and_not_lists():
    inputs = OpportunityInputs(
        project_id="project-1",
        confidence=ConfidenceSet(**confidence_data()),
        risks=RiskSet(**risk_data()),
    )
    decision = DecisionResult(
        status="MONITOR",
        public_label="WATCH",
        recommended_action="Wait.",
        review_at=NOW,
        expires_at=NOW,
    )
    assessment = OpportunityAssessment(**assessment_data(factor_snapshot={}))

    assert inputs.critical_unknowns == ()
    assert inputs.evidence_ids == ()
    assert decision.blocker_codes == ()
    assert decision.watch_reason_codes == ()
    assert decision.ignore_reason_codes == ()
    assert decision.requires_remediation is False
    assert assessment.blocker_codes == ()
    assert assessment.watch_reason_codes == ()
    assert assessment.ignore_reason_codes == ()
    assert assessment.requires_remediation is False
    assert assessment.evidence_ids == ()


def test_models_reject_assignment():
    probability = ProbabilityRange(low=0.2, base=0.5, high=0.8)
    inputs = OpportunityInputs(
        project_id="project-1",
        confidence=ConfidenceSet(**confidence_data()),
        risks=RiskSet(**risk_data()),
    )

    with pytest.raises(ValidationError):
        probability.base = 0.6
    with pytest.raises(ValidationError):
        inputs.project_id = "changed"
    with pytest.raises(ValidationError):
        DEFAULT_PROFILE.wallet_count_min = 4


def test_opportunity_assessment_constructs_and_serializes():
    assessment = OpportunityAssessment(**assessment_data(capital_at_risk_usd={"low": 4, "base": 5, "high": 6}))

    dumped = assessment.model_dump(mode="json")
    encoded = json.loads(assessment.model_dump_json())

    assert assessment.status is DecisionStatus.MONITOR
    assert assessment.capital_at_risk_usd == MoneyRange(low=4, base=5, high=6)
    assert dumped["capital_at_risk_usd"] == {"low": 4.0, "base": 5.0, "high": 6.0}
    assert dumped["factor_snapshot"] == assessment_data()["factor_snapshot"]
    assert encoded == dumped
    assert isinstance(dumped["factor_snapshot"], dict)
    assert isinstance(dumped["factor_snapshot"]["sources"], list)


def test_remediation_flag_round_trips_for_blocked_snapshots():
    decision = DecisionResult(
        status="BLOCKED",
        public_label="IGNORE",
        blocker_codes=("SAFETY_BLOCK",),
        recommended_action="Do not interact.",
        review_at=NOW,
        expires_at=NOW,
        requires_remediation=True,
    )
    assessment = OpportunityAssessment(
        **assessment_data(
            status="BLOCKED",
            public_label="IGNORE",
            blocker_codes=("SAFETY_BLOCK",),
            requires_remediation=True,
        )
    )

    assert decision.requires_remediation is True
    assert assessment.requires_remediation is True
    assert assessment.model_dump(mode="json")["requires_remediation"] is True


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (
            DecisionResult,
            {
                "status": "BLOCKED",
                "public_label": "IGNORE",
                "recommended_action": "Do not interact.",
                "review_at": NOW,
                "expires_at": NOW,
                "requires_remediation": False,
            },
        ),
        (
            DecisionResult,
            {
                "status": "MONITOR",
                "public_label": "WATCH",
                "recommended_action": "Wait.",
                "review_at": NOW,
                "expires_at": NOW,
                "requires_remediation": True,
            },
        ),
        (
            OpportunityAssessment,
            assessment_data(status="BLOCKED", public_label="IGNORE"),
        ),
        (
            OpportunityAssessment,
            assessment_data(requires_remediation=True),
        ),
    ],
)
def test_remediation_must_match_blocked_status(model, data):
    with pytest.raises(ValidationError, match="requires_remediation"):
        model(**data)


def test_assessment_json_validation_enforces_remediation_invariant():
    payload = assessment_data(status="BLOCKED", public_label="IGNORE")

    with pytest.raises(ValidationError, match="requires_remediation"):
        OpportunityAssessment.model_validate_json(json.dumps(payload, default=str))


def test_factor_snapshot_public_annotation_is_immutable_mapping():
    assert OpportunityAssessment.model_fields["factor_snapshot"].annotation == Mapping[str, Any]


@pytest.mark.parametrize(
    "non_finite",
    [float("nan"), float("inf"), float("-inf")],
    ids=["nan", "positive-infinity", "negative-infinity"],
)
def test_assessment_rejects_nested_non_finite_json_numbers(non_finite):
    with pytest.raises(ValidationError, match="finite"):
        OpportunityAssessment(**assessment_data(factor_snapshot={"nested": [{"number": non_finite}]}))


def test_json_payload_dump_paths_are_strict_json_safe():
    models = [
        EvidenceRecord(**evidence_data(value={"nested": [1.5, -2.0]})),
        OpportunityAssessment(**assessment_data(factor_snapshot={"nested": [1.5, -2.0]})),
    ]

    for model in models:
        json.dumps(model.model_dump(mode="json"), allow_nan=False)
        json.loads(
            model.model_dump_json(),
            parse_constant=lambda value: pytest.fail(f"non-finite JSON constant serialized: {value}"),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("model_version", "opportunity-v3.0"),
        ("profile_version", "other-profile"),
        ("status", "PENDING"),
        ("public_label", "SKIP"),
    ],
)
def test_opportunity_assessment_enforces_literals(field, value):
    with pytest.raises(ValidationError):
        OpportunityAssessment(**assessment_data(**{field: value}))


def test_assessment_factor_snapshot_is_deeply_immutable_and_detached():
    input_snapshot = {"signals": [{"weights": [0.6, 0.4]}]}
    assessment = OpportunityAssessment(**assessment_data(factor_snapshot=input_snapshot))

    input_snapshot["signals"][0]["weights"][0] = 1.0
    assert assessment.factor_snapshot["signals"][0]["weights"][0] == 0.6
    with pytest.raises(TypeError):
        assessment.factor_snapshot["signals"][0]["weights"][0] = 1.0
    with pytest.raises((AttributeError, TypeError)):
        assessment.factor_snapshot["signals"].append("new")
