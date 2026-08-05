import math
from datetime import UTC, datetime, timedelta
from itertools import product

import pytest

from app.opportunity.evidence import build_inputs
from app.opportunity.models import EvidenceRecord, ProbabilityRange
from app.opportunity.probability import (
    ELIGIBILITY_RULES,
    EVENT_RULES,
    SURVIVAL_RULES,
    derive_probability_inputs,
    joint_probability,
)
from app.opportunity.profile import DEFAULT_PROFILE


def _record(
    factor: str,
    value,
    *,
    evidence_id: str | None = None,
    grade: str = "A",
    status: str = "verified",
    value_type: str | None = None,
    observation_type: str = "observed",
    observed_at: str = "2026-07-14T00:00:00Z",
    expires_at: str | None = None,
    project_id: str | None = "p1",
) -> EvidenceRecord:
    if value_type is None:
        if isinstance(value, bool):
            value_type = "bool"
        elif isinstance(value, dict):
            value_type = "range"
        else:
            value_type = "string"
    return EvidenceRecord(
        evidence_id=evidence_id or factor,
        project_id=project_id,
        factor_key=factor,
        value=value,
        value_type=value_type,
        observation_type=observation_type,
        source_url="https://project.example/rules",
        source_type="official_docs",
        source_grade=grade,
        observed_at=observed_at,
        expires_at=expires_at,
        verification_status=status,
        independence_group=f"source-{factor}",
    )


def _derive(records: list[EvidenceRecord], *, inputs_records=None):
    normalized_records = records if inputs_records is None else inputs_records
    inputs = build_inputs({"id": "p1", "meta": "{}"}, normalized_records, DEFAULT_PROFILE)
    return derive_probability_inputs(inputs, records, DEFAULT_PROFILE)


def test_rule_tables_are_exact():
    assert {key: value.model_dump() for key, value in EVENT_RULES.items()} == {
        "official_distribution_and_catalyst": {"low": 0.65, "base": 0.78, "high": 0.90},
        "official_distribution": {"low": 0.55, "base": 0.70, "high": 0.85},
        "official_points_value": {"low": 0.50, "base": 0.65, "high": 0.80},
    }
    assert {key: value.model_dump() for key, value in ELIGIBILITY_RULES.items()} == {
        "deterministic_open_within_budget": {"low": 0.65, "base": 0.80, "high": 0.90},
        "points_open_within_budget": {"low": 0.50, "base": 0.67, "high": 0.82},
        "behavioral_open_within_budget": {"low": 0.40, "base": 0.58, "high": 0.75},
    }
    assert {key: value.model_dump() for key, value in SURVIVAL_RULES.items()} == {
        "allowed": {"low": 0.75, "base": 0.88, "high": 0.95},
        "not_forbidden": {"low": 0.60, "base": 0.75, "high": 0.88},
        "forbidden": {"low": 0.0, "base": 0.0, "high": 0.0},
    }


def test_joint_probability_base_is_the_product_of_bases():
    result = joint_probability(
        ProbabilityRange(low=0.60, base=0.70, high=0.80),
        ProbabilityRange(low=0.55, base=0.65, high=0.75),
        ProbabilityRange(low=0.70, base=0.80, high=0.90),
    )
    assert result.base == pytest.approx(0.70 * 0.65 * 0.80)


def test_joint_probability_combines_uncertainty_in_quadrature_not_per_quantile():
    """区间端点按相对不确定度平方和合成，而非 low×low×low。

    逐分位连乘要求三因子完全同向，与 base 所依赖的独立性假设直接矛盾；
    对本算例它给出 0.231–0.540，而 40 万次独立三角分布抽样的真实 p10–p90
    只有约 0.283–0.446。平方和合成给出 0.275–0.453，仍略偏保守但不再自相矛盾。
    """
    result = joint_probability(
        ProbabilityRange(low=0.60, base=0.70, high=0.80),
        ProbabilityRange(low=0.55, base=0.65, high=0.75),
        ProbabilityRange(low=0.70, base=0.80, high=0.90),
    )
    assert result.low == pytest.approx(0.275060, abs=1e-6)
    assert result.high == pytest.approx(0.452940, abs=1e-6)
    # 严格窄于逐分位连乘的旧区间，且仍包住 base
    assert result.low > 0.60 * 0.55 * 0.70
    assert result.high < 0.80 * 0.75 * 0.90
    assert result.low <= result.base <= result.high


@pytest.mark.parametrize(
    ("event_key", "eligibility_key", "survival_key"),
    [
        ("official_distribution_and_catalyst", "deterministic_open_within_budget", "allowed"),
        ("official_distribution", "points_open_within_budget", "not_forbidden"),
        ("official_points_value", "behavioral_open_within_budget", "not_forbidden"),
    ],
)
def test_joint_probability_is_bounded_and_ordered_for_every_rule_stack(event_key, eligibility_key, survival_key):
    result = joint_probability(
        EVENT_RULES[event_key],
        ELIGIBILITY_RULES[eligibility_key],
        SURVIVAL_RULES[survival_key],
    )
    assert 0.0 <= result.low <= result.base <= result.high <= 1.0


def test_mid_tier_rule_stack_can_clear_the_farm_probability_gate():
    """decision 用 reward_probability.low >= 0.20 作为 FARM 门槛。

    旧的逐分位连乘让"官方分发 + 积分制资格 + 未禁止多钱包"这一档的 joint.low
    恒为 0.55*0.50*0.60 = 0.1650，无论证据多强都无法通过门槛——纯粹是区间
    算法造成的数学假象。修正后该档为 0.2154，门槛重新可达。
    """
    result = joint_probability(
        EVENT_RULES["official_distribution"],
        ELIGIBILITY_RULES["points_open_within_budget"],
        SURVIVAL_RULES["not_forbidden"],
    )
    assert 0.55 * 0.50 * 0.60 < 0.20 <= result.low


def test_joint_probability_degenerates_to_zero_when_any_factor_is_impossible():
    result = joint_probability(
        EVENT_RULES["official_distribution"],
        ELIGIBILITY_RULES["points_open_within_budget"],
        SURVIVAL_RULES["forbidden"],
    )
    assert (result.low, result.base, result.high) == (0.0, 0.0, 0.0)


def test_joint_probability_matches_monte_carlo_within_conservative_bounds():
    """合成区间必须覆盖真实分布的 p10–p90，且不得比逐分位连乘更宽。"""
    import random

    factors = (
        ProbabilityRange(low=0.65, base=0.78, high=0.90),
        ProbabilityRange(low=0.65, base=0.80, high=0.90),
        ProbabilityRange(low=0.75, base=0.88, high=0.95),
    )
    rng = random.Random(20260726)  # noqa: S311 — 蒙特卡洛抽样，非加密用途；固定种子保证可复现
    draws = sorted(math.prod(rng.triangular(f.low, f.high, f.base) for f in factors) for _ in range(40_000))
    p10 = draws[int(0.10 * len(draws))]
    p90 = draws[int(0.90 * len(draws))]

    result = joint_probability(*factors)
    assert result.low < p10 and p90 < result.high, "合成区间必须覆盖真实 p10–p90"
    assert result.low > factors[0].low * factors[1].low * factors[2].low
    assert result.high < factors[0].high * factors[1].high * factors[2].high


def test_explicit_probability_ranges_are_preserved():
    records = [
        _record("event_probability", {"low": 0.11, "base": 0.22, "high": 0.33}),
        _record("eligibility_probability", {"low": 0.21, "base": 0.32, "high": 0.43}),
        _record("survival_probability", {"low": 0.31, "base": 0.42, "high": 0.53}),
        _record("multiwallet_policy", "forbidden"),
    ]
    inputs = build_inputs({"id": "p1", "meta": "{}"}, records, DEFAULT_PROFILE)

    assert derive_probability_inputs(inputs, records, DEFAULT_PROFILE) == (
        inputs.event_probability,
        inputs.eligibility_probability,
        inputs.survival_probability,
    )


@pytest.mark.parametrize("temporal_field", ["observed_at", "effective_at"])
def test_future_evidence_cannot_derive_probabilities(temporal_field):
    now = datetime(2026, 7, 14, tzinfo=UTC)
    future = now + timedelta(seconds=1)
    record = _record("official_airdrop_statement", True).model_copy(update={temporal_field: future})
    inputs = build_inputs({"id": "p1", "meta": "{}"}, [record], DEFAULT_PROFILE, now=now)

    assert derive_probability_inputs(inputs, [record], DEFAULT_PROFILE, now=now) == (
        None,
        None,
        None,
    )


@pytest.mark.parametrize(
    "factor",
    ["event_probability", "eligibility_probability", "survival_probability"],
)
def test_explicit_range_is_not_trusted_when_omitted_from_current_evidence(factor):
    record = _record(factor, {"low": 0.2, "base": 0.4, "high": 0.6})
    inputs = build_inputs({"id": "p1", "meta": "{}"}, [record], DEFAULT_PROFILE)

    result = derive_probability_inputs(inputs, [], DEFAULT_PROFILE)

    assert result[{"event_probability": 0, "eligibility_probability": 1, "survival_probability": 2}[factor]] is None


@pytest.mark.parametrize(
    "factor",
    ["event_probability", "eligibility_probability", "survival_probability"],
)
def test_explicit_range_is_not_trusted_when_current_evidence_is_revoked(factor):
    active = _record(factor, {"low": 0.2, "base": 0.4, "high": 0.6})
    revoked = active.model_copy(update={"verification_status": "invalidated"})
    inputs = build_inputs({"id": "p1", "meta": "{}"}, [active], DEFAULT_PROFILE)

    result = derive_probability_inputs(inputs, [revoked], DEFAULT_PROFILE)

    assert result[{"event_probability": 0, "eligibility_probability": 1, "survival_probability": 2}[factor]] is None


@pytest.mark.parametrize("observation_type", ["estimated", "assumed"])
@pytest.mark.parametrize(
    "factor",
    ["event_probability", "eligibility_probability", "survival_probability"],
)
def test_explicit_ranges_reject_estimated_and_assumed_provenance(factor, observation_type):
    record = _record(
        factor,
        {"low": 0.2, "base": 0.4, "high": 0.6},
        observation_type=observation_type,
    )
    inputs = build_inputs({"id": "p1", "meta": "{}"}, [record], DEFAULT_PROFILE)
    result = derive_probability_inputs(inputs, [record], DEFAULT_PROFILE)
    assert result[{"event_probability": 0, "eligibility_probability": 1, "survival_probability": 2}[factor]] is None


@pytest.mark.parametrize("observation_type", ["observed", "derived"])
def test_explicit_ranges_accept_observed_and_derived_provenance(observation_type):
    record = _record(
        "event_probability",
        {"low": 0.2, "base": 0.4, "high": 0.6},
        observation_type=observation_type,
    )
    inputs = build_inputs({"id": "p1", "meta": "{}"}, [record], DEFAULT_PROFILE)
    event, _, _ = derive_probability_inputs(inputs, [record], DEFAULT_PROFILE)
    assert event == ProbabilityRange(low=0.2, base=0.4, high=0.6)


@pytest.mark.parametrize(
    ("basis", "extra", "expected_key"),
    [
        ("official_airdrop_statement", [], "official_distribution"),
        ("community_allocation", [], "official_distribution"),
        (
            "official_airdrop_statement",
            [("distribution_catalyst_3_6m", True)],
            "official_distribution_and_catalyst",
        ),
        ("official_points_future_value", [], "official_points_value"),
    ],
)
def test_verified_official_basis_derives_exact_event_rule(basis, extra, expected_key):
    records = [_record("participation_open", True), _record(basis, True)]
    records.extend(_record(factor, value) for factor, value in extra)

    event, _, _ = _derive(records)

    assert event == EVENT_RULES[expected_key]


def test_official_distribution_takes_precedence_over_points_rule():
    records = [
        _record("official_airdrop_statement", True),
        _record("official_points_future_value", True),
    ]
    event, _, _ = _derive(records)
    assert event == EVENT_RULES["official_distribution"]


@pytest.mark.parametrize("grade", ["B", "C", "D", "U"])
def test_event_derivation_requires_official_a_grade_basis(grade):
    event, _, _ = _derive([_record("official_airdrop_statement", True, grade=grade)])
    assert event is None


@pytest.mark.parametrize("observation_type", ["estimated", "assumed"])
@pytest.mark.parametrize(
    "factor", ["official_airdrop_statement", "community_allocation", "official_points_future_value"]
)
def test_event_basis_rejects_estimated_and_assumed_provenance(factor, observation_type):
    event, _, _ = _derive([_record(factor, True, observation_type=observation_type)])
    assert event is None


@pytest.mark.parametrize("observation_type", ["observed", "derived"])
@pytest.mark.parametrize(
    "factor", ["official_airdrop_statement", "community_allocation", "official_points_future_value"]
)
def test_event_basis_accepts_observed_and_derived_provenance(factor, observation_type):
    event, _, _ = _derive([_record(factor, True, observation_type=observation_type)])
    expected = "official_points_value" if factor == "official_points_future_value" else "official_distribution"
    assert event == EVENT_RULES[expected]


@pytest.mark.parametrize("grade", ["B", "C", "D", "U"])
def test_event_catalyst_requires_a_grade(grade):
    event, _, _ = _derive(
        [
            _record("official_airdrop_statement", True),
            _record("distribution_catalyst_3_6m", True, grade=grade),
        ]
    )
    assert event == EVENT_RULES["official_distribution"]


@pytest.mark.parametrize(
    ("observation_type", "uses_catalyst"),
    [("observed", True), ("derived", True), ("estimated", False), ("assumed", False)],
)
def test_event_catalyst_enforces_every_provenance_class(observation_type, uses_catalyst):
    event, _, _ = _derive(
        [
            _record("official_airdrop_statement", True),
            _record(
                "distribution_catalyst_3_6m",
                True,
                observation_type=observation_type,
            ),
        ]
    )
    expected = "official_distribution_and_catalyst" if uses_catalyst else "official_distribution"
    assert event == EVENT_RULES[expected]


def test_legacy_no_token_funding_task_and_narrative_never_derive_event():
    row = {
        "id": "p1",
        "meta": (
            '{"signals":{"no_token_yet":true,"funding_million":100,"has_task_portal":true,"narrative_heat":"high"}}'
        ),
    }
    inputs = build_inputs(row, [], DEFAULT_PROFILE)
    event, _, _ = derive_probability_inputs(inputs, [], DEFAULT_PROFILE)
    assert event is None


@pytest.mark.parametrize(
    ("mechanism", "expected_key"),
    [
        ("deterministic", "deterministic_open_within_budget"),
        ("points_based", "points_open_within_budget"),
        ("behavioral", "behavioral_open_within_budget"),
    ],
)
def test_open_known_within_budget_eligibility_uses_exact_mechanism_rule(mechanism, expected_key):
    records = [
        _record("participation_open", True),
        _record("hard_cost_usd", {"low": 1, "base": 10, "high": 12}),
        _record("eligibility_mechanism", mechanism),
    ]
    _, eligibility, _ = _derive(records)
    assert eligibility == ELIGIBILITY_RULES[expected_key]


@pytest.mark.parametrize("grade", ["A", "B"])
def test_eligibility_gate_factors_accept_a_or_b_grade(grade):
    records = [
        _record("participation_open", True, grade=grade),
        _record("hard_cost_usd", {"low": 1, "base": 10, "high": 12}, grade=grade),
        _record("eligibility_mechanism", "deterministic", grade=grade),
    ]
    _, eligibility, _ = _derive(records)
    assert eligibility == ELIGIBILITY_RULES["deterministic_open_within_budget"]


@pytest.mark.parametrize("factor", ["participation_open", "hard_cost_usd", "eligibility_mechanism"])
@pytest.mark.parametrize("grade", ["C", "D", "U"])
def test_eligibility_gate_factors_reject_below_b_grade(factor, grade):
    values = {
        "participation_open": True,
        "hard_cost_usd": {"low": 1, "base": 10, "high": 12},
        "eligibility_mechanism": "deterministic",
    }
    records = [_record(key, value, grade=grade if key == factor else "A") for key, value in values.items()]
    _, eligibility, _ = _derive(records)
    assert eligibility is None


@pytest.mark.parametrize("factor", ["participation_open", "hard_cost_usd", "eligibility_mechanism"])
@pytest.mark.parametrize("observation_type", ["estimated", "assumed"])
def test_eligibility_gate_factors_reject_unapproved_provenance(factor, observation_type):
    values = {
        "participation_open": True,
        "hard_cost_usd": {"low": 1, "base": 10, "high": 12},
        "eligibility_mechanism": "deterministic",
    }
    records = [
        _record(key, value, observation_type=observation_type if key == factor else "observed")
        for key, value in values.items()
    ]
    _, eligibility, _ = _derive(records)
    assert eligibility is None


@pytest.mark.parametrize("factor", ["participation_open", "hard_cost_usd", "eligibility_mechanism"])
@pytest.mark.parametrize("observation_type", ["observed", "derived"])
def test_eligibility_gate_factors_accept_approved_provenance(factor, observation_type):
    values = {
        "participation_open": True,
        "hard_cost_usd": {"low": 1, "base": 10, "high": 12},
        "eligibility_mechanism": "deterministic",
    }
    records = [
        _record(key, value, observation_type=observation_type if key == factor else "observed")
        for key, value in values.items()
    ]
    _, eligibility, _ = _derive(records)
    assert eligibility == ELIGIBILITY_RULES["deterministic_open_within_budget"]


def test_eligibility_accepts_exact_profile_cost_boundary():
    records = [
        _record("participation_open", True),
        _record("hard_cost_usd", {"low": 10, "base": 10, "high": 10}),
        _record("eligibility_mechanism", "deterministic"),
    ]
    _, eligibility, _ = _derive(records)
    assert eligibility == ELIGIBILITY_RULES["deterministic_open_within_budget"]


@pytest.mark.parametrize(
    "records",
    [
        [_record("hard_cost_usd", {"low": 0, "base": 1, "high": 2}), _record("eligibility_mechanism", "deterministic")],
        [
            _record("participation_open", False),
            _record("hard_cost_usd", {"low": 0, "base": 1, "high": 2}),
            _record("eligibility_mechanism", "deterministic"),
        ],
        [_record("participation_open", True), _record("eligibility_mechanism", "deterministic")],
        [
            _record("participation_open", True),
            _record("hard_cost_usd", {"low": 1, "base": 10.01, "high": 12}),
            _record("eligibility_mechanism", "deterministic"),
        ],
        [
            _record("participation_open", True),
            _record("hard_cost_usd", {"low": 0, "base": 1, "high": 2}),
            _record("eligibility_mechanism", "opaque"),
        ],
    ],
    ids=["open-unknown", "closed", "cost-unknown", "over-budget", "opaque"],
)
def test_eligibility_remains_unknown_without_every_confident_gate(records):
    _, eligibility, _ = _derive(records)
    assert eligibility is None


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        ("allowed", SURVIVAL_RULES["allowed"]),
        ("not_forbidden", SURVIVAL_RULES["not_forbidden"]),
        ("forbidden", SURVIVAL_RULES["forbidden"]),
        ("unknown", None),
    ],
)
def test_survival_policy_rules_preserve_unknown_and_zero_forbidden(policy, expected):
    _, _, survival = _derive([_record("multiwallet_policy", policy)])
    assert survival == expected


@pytest.mark.parametrize("grade", ["A", "B"])
def test_survival_policy_accepts_a_or_b_grade(grade):
    _, _, survival = _derive([_record("multiwallet_policy", "allowed", grade=grade)])
    assert survival == SURVIVAL_RULES["allowed"]


@pytest.mark.parametrize("grade", ["C", "D", "U"])
def test_survival_policy_rejects_below_b_grade(grade):
    _, _, survival = _derive([_record("multiwallet_policy", "allowed", grade=grade)])
    assert survival is None


@pytest.mark.parametrize("observation_type", ["estimated", "assumed"])
def test_survival_policy_rejects_unapproved_provenance(observation_type):
    _, _, survival = _derive([_record("multiwallet_policy", "allowed", observation_type=observation_type)])
    assert survival is None


@pytest.mark.parametrize("observation_type", ["observed", "derived"])
def test_survival_policy_accepts_approved_provenance(observation_type):
    _, _, survival = _derive([_record("multiwallet_policy", "allowed", observation_type=observation_type)])
    assert survival == SURVIVAL_RULES["allowed"]


@pytest.mark.parametrize(
    ("factor", "first", "second", "result_index"),
    [
        ("event_probability", {"low": 0.2, "base": 0.4, "high": 0.6}, {"low": 0.3, "base": 0.5, "high": 0.7}, 0),
        ("eligibility_probability", {"low": 0.2, "base": 0.4, "high": 0.6}, {"low": 0.3, "base": 0.5, "high": 0.7}, 1),
        ("survival_probability", {"low": 0.2, "base": 0.4, "high": 0.6}, {"low": 0.3, "base": 0.5, "high": 0.7}, 2),
        ("multiwallet_policy", "allowed", "forbidden", 2),
    ],
)
def test_same_grade_contradictions_remain_unresolved_despite_newer_timestamp(factor, first, second, result_index):
    records = [
        _record(factor, first, evidence_id="old", observed_at="2026-07-10T00:00:00Z"),
        _record(factor, second, evidence_id="new", observed_at="2026-07-14T00:00:00Z"),
    ]
    result = _derive(records)
    assert result[result_index] is None


@pytest.mark.parametrize(
    ("factor", "first", "second"),
    [
        ("official_airdrop_statement", True, False),
        ("community_allocation", True, False),
        ("official_points_future_value", True, False),
    ],
)
def test_same_grade_event_basis_contradiction_yields_no_event(factor, first, second):
    event, _, _ = _derive(
        [
            _record(factor, first, evidence_id="old", observed_at="2026-07-10T00:00:00Z"),
            _record(factor, second, evidence_id="new", observed_at="2026-07-14T00:00:00Z"),
        ]
    )
    assert event is None


@pytest.mark.parametrize(
    ("factor", "first", "second"),
    [
        ("participation_open", True, False),
        ("eligibility_mechanism", "deterministic", "points_based"),
        (
            "hard_cost_usd",
            {"low": 1, "base": 2, "high": 3},
            {"low": 2, "base": 3, "high": 4},
        ),
    ],
)
def test_same_grade_eligibility_gate_contradiction_yields_no_eligibility(factor, first, second):
    values = {
        "participation_open": True,
        "hard_cost_usd": {"low": 1, "base": 2, "high": 3},
        "eligibility_mechanism": "deterministic",
    }
    records = [_record(key, value, evidence_id=f"base-{key}") for key, value in values.items() if key != factor]
    records.extend(
        [
            _record(factor, first, evidence_id="old", observed_at="2026-07-10T00:00:00Z"),
            _record(factor, second, evidence_id="new", observed_at="2026-07-14T00:00:00Z"),
        ]
    )
    _, eligibility, _ = _derive(records)
    assert eligibility is None


@pytest.mark.parametrize("status", ["partially_verified", "unverified", "conflicted", "invalidated"])
def test_derivation_rejects_non_verified_evidence(status):
    records = [_record("official_airdrop_statement", True, status=status)]
    event, _, _ = _derive(records)
    assert event is None


def test_derivation_rejects_evidence_not_id_gated_by_inputs():
    trusted = [_record("official_identity", True, evidence_id="trusted")]
    injected = _record("official_airdrop_statement", True, evidence_id="injected")

    event, _, _ = _derive([*trusted, injected], inputs_records=trusted)

    assert event is None


@pytest.mark.parametrize("foreign_project", ["p2", None], ids=["other-project", "missing-project"])
def test_explicit_event_range_requires_matching_project_even_with_accepted_id(
    foreign_project,
):
    own = _record(
        "event_probability",
        {"low": 0.2, "base": 0.4, "high": 0.6},
        evidence_id="event",
    )
    inputs = build_inputs({"id": "p1", "meta": "{}"}, [own], DEFAULT_PROFILE)
    foreign = own.model_copy(update={"project_id": foreign_project})

    event, _, _ = derive_probability_inputs(inputs, [foreign], DEFAULT_PROFILE)

    assert event is None


@pytest.mark.parametrize("foreign_project", ["p2", None], ids=["other-project", "missing-project"])
def test_derived_event_requires_matching_project_even_with_accepted_id(foreign_project):
    own = _record("official_airdrop_statement", True, evidence_id="basis")
    inputs = build_inputs({"id": "p1", "meta": "{}"}, [own], DEFAULT_PROFILE)
    foreign = own.model_copy(update={"project_id": foreign_project})

    event, _, _ = derive_probability_inputs(inputs, [foreign], DEFAULT_PROFILE)

    assert event is None


@pytest.mark.parametrize("foreign_project", ["p2", None], ids=["other-project", "missing-project"])
def test_eligibility_requires_matching_project_even_with_accepted_ids(foreign_project):
    own = [
        _record("participation_open", True, evidence_id="open"),
        _record(
            "hard_cost_usd",
            {"low": 1, "base": 2, "high": 3},
            evidence_id="cost",
        ),
        _record("eligibility_mechanism", "deterministic", evidence_id="mechanism"),
    ]
    inputs = build_inputs({"id": "p1", "meta": "{}"}, own, DEFAULT_PROFILE)
    foreign = [record.model_copy(update={"project_id": foreign_project}) for record in own]

    _, eligibility, _ = derive_probability_inputs(inputs, foreign, DEFAULT_PROFILE)

    assert eligibility is None


@pytest.mark.parametrize("foreign_project", ["p2", None], ids=["other-project", "missing-project"])
def test_survival_requires_matching_project_even_with_accepted_id(foreign_project):
    own = _record("multiwallet_policy", "allowed", evidence_id="policy")
    inputs = build_inputs({"id": "p1", "meta": "{}"}, [own], DEFAULT_PROFILE)
    foreign = own.model_copy(update={"project_id": foreign_project})

    _, _, survival = derive_probability_inputs(inputs, [foreign], DEFAULT_PROFILE)

    assert survival is None


def test_survival_derivation_requires_id_gated_policy_evidence():
    policy = _record("multiwallet_policy", "allowed", evidence_id="policy")
    inputs = build_inputs({"id": "p1", "meta": "{}"}, [policy], DEFAULT_PROFILE)

    _, _, survival = derive_probability_inputs(inputs, [], DEFAULT_PROFILE)

    assert survival is None


def test_derivation_uses_evidence_normalization_instead_of_truthy_raw_values():
    malformed = _record(
        "official_airdrop_statement",
        "true",
        evidence_id="malformed",
        value_type="bool",
    )
    event, _, _ = _derive([malformed])
    assert event is None


def test_joint_probability_is_never_wider_than_per_quantile_product():
    """合成区间必须恒为逐分位连乘区间的子集。

    相对不确定度之和可能超过 100%（例如某因子 low=0），此时 base×(1−rel) 会变成
    负数并被夹到 0——那比连乘还悲观，与"只收紧不放宽"的前提矛盾。

    这里用 0.2 网格穷举（约 17 万组，含 low=0 与 base≈0 的全部边界形态）。
    ADR-014 记录了同一断言在 0.1 网格上的 2334 万组全穷举结果：0 违例。
    """
    grid = [i / 5 for i in range(6)]
    ranges = [
        ProbabilityRange(low=low, base=base, high=high)
        for low, base, high in product(grid, grid, grid)
        if low <= base <= high
    ]
    for event, eligibility, survival in product(ranges, repeat=3):
        result = joint_probability(event, eligibility, survival)
        assert 0.0 <= result.low <= result.base <= result.high <= 1.0
        assert result.low >= event.low * eligibility.low * survival.low - 1e-12
        assert result.high <= event.high * eligibility.high * survival.high + 1e-12


def test_zero_base_keeps_a_non_zero_optimistic_endpoint():
    """base=0 只说明"最可能不发生"，不代表乐观端也是 0。

    若强行把 high 归零，`gross_reward.high` 随之为 0，会经 DUST_REWARD 门槛
    把项目误判成 30 天 IGNORE。
    """
    result = joint_probability(
        ProbabilityRange(low=0.5, base=0.7, high=0.9),
        ProbabilityRange(low=0.4, base=0.6, high=0.8),
        ProbabilityRange(low=0.0, base=0.0, high=0.9),
    )
    assert result.base == 0.0
    assert result.high == pytest.approx(0.9 * 0.8 * 0.9)


def test_forbidden_survival_still_degenerates_to_a_point():
    result = joint_probability(
        EVENT_RULES["official_distribution"],
        ELIGIBILITY_RULES["points_open_within_budget"],
        SURVIVAL_RULES["forbidden"],
    )
    assert (result.low, result.base, result.high) == (0.0, 0.0, 0.0)
